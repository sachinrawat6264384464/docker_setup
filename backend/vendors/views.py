# vendors/views.py
from rest_framework import viewsets, status, filters, mixins, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound, PermissionDenied
from django.db import connection
import logging
from django.db.models import Q, Avg, Count, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from datetime import datetime, timedelta

logger = logging.getLogger('django')
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from maintenance.models import MaintenanceRequest, MaintenanceSchedule
from maintenance.serializers import MaintenanceScheduleSerializer
from notifications.models import Notification
from notifications.serializers import NotificationSerializer
from maintenance.models import MaintenanceRequest

from .models import (
    VendorCategory, Vendor, VendorService, VendorContract,
    VendorReview, VendorPayment, VendorInsurance
)
from .serializers import (
    VendorCategorySerializer, VendorSerializer, VendorServiceSerializer,
    VendorContractSerializer, VendorReviewSerializer, VendorPaymentSerializer,
    VendorInsuranceSerializer, VendorWorkOrderSerializer
)


def sync_vendor_categories_from_maintenance_choices():
    """Ensure vendor categories mirror maintenance categories."""
    maintenance_labels = [label for _, label in MaintenanceRequest.CATEGORY_CHOICES]

    for label in maintenance_labels:
        category, created = VendorCategory.objects.get_or_create(
            name=label,
            defaults={
                'description': f'Auto-synced from maintenance category: {label}',
                'is_active': True,
            },
        )

        if not created and not category.is_active:
            category.is_active = True
            category.save(update_fields=['is_active'])


class IsVendorPortalUser(permissions.BasePermission):
    """Allow only vendor users and internal admins to access the portal APIs."""

    allowed_roles = {'tenant_vendor', 'master_admin', 'super_admin'}

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in self.allowed_roles)


def _resolve_vendor_for_user(user):
    if not user or not user.is_authenticated:
        return None

    vendor = getattr(user, 'vendor_profile', None)
    if vendor:
        return vendor

    vendor = Vendor.objects.filter(user=user).first()
    if vendor:
        return vendor

    if getattr(user, 'email', None):
        vendor = Vendor.objects.filter(email__iexact=user.email).first()
        if vendor:
            return vendor

    return None


class VendorPortalViewSet(viewsets.GenericViewSet):
    permission_classes = [IsVendorPortalUser]
    serializer_class = VendorSerializer

    def get_vendor(self):
        vendor = _resolve_vendor_for_user(self.request.user)
        if not vendor:
            raise NotFound('Vendor profile is not linked to this account.')
        return vendor

    @action(detail=False, methods=['get'])
    def test_data(self, request):
        """Diagnostic endpoint to see all requests in schema."""
        all_requests = MaintenanceRequest.objects.all()
        data = []
        for r in all_requests:
            data.append({
                'id': str(r.id),
                'title': r.title,
                'status': r.status,
                'assigned_to_id': str(r.assigned_to_id) if r.assigned_to_id else None,
                'assigned_to_username': r.assigned_to.username if r.assigned_to else None,
            })
        return Response({
            'total_in_schema': all_requests.count(),
            'current_user_id': str(request.user.id),
            'current_user_username': request.user.username,
            'requests': data
        })

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        vendor = self.get_vendor()
        today = timezone.now().date()
        soon_threshold = today + timedelta(days=30)

        work_orders = MaintenanceRequest.objects.filter(assigned_to=request.user)
        contracts = vendor.contracts.all()
        payments = vendor.payments.all()
        reviews = vendor.reviews.all()
        insurance = vendor.insurance_policies.all()

        wo_stats = work_orders.aggregate(
            total=Count('id'),
            assigned=Count('id', filter=~Q(status__in=['completed', 'cancelled'])),
            upcoming=Count('id', filter=Q(preferred_date__gte=today) | Q(status__in=['assigned', 'in_progress'])),
            overdue=Count('id', filter=Q(status__in=['assigned', 'in_progress'], preferred_date__lt=today)),
            submitted=Count('id', filter=Q(status='submitted'))
        )

        contract_stats = contracts.aggregate(
            draft=Count('id', filter=Q(status='draft')),
            active=Count('id', filter=Q(status='active'))
        )

        payment_stats = payments.aggregate(
            total_paid=Sum('amount', filter=Q(status='paid')),
            total_pending=Sum('amount', filter=Q(status__in=['pending', 'processing'])),
            overdue_amount=Sum('amount', filter=Q(status__in=['pending', 'processing'], due_date__lt=today)),
            count_paid=Count('id', filter=Q(status='paid')),
            count_pending=Count('id', filter=Q(status__in=['pending', 'processing']))
        )

        review_stats = reviews.aggregate(
            total=Count('id'),
            recommend_count=Count('id', filter=Q(would_recommend=True))
        )
        total_reviews = review_stats['total'] or 0

        insurance_expiring_soon = insurance.filter(expiry_date__gte=today, expiry_date__lte=soon_threshold).count()
        notifications_count = Notification.objects.filter(recipient=request.user).count()
        recent_notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:5]

        # Diagnostic: Count all requests in this schema to see if they exist at all
        all_requests_count = MaintenanceRequest.objects.count()
        logger.info(f"VENDOR DASHBOARD: User='{request.user.username}' (ID: {request.user.id}) Schema='{connection.schema_name}' Total Requests in Schema={all_requests_count} Assigned to this user={wo_stats['total']}")

        return Response({
            'vendor': VendorSerializer(vendor, context={'request': request}).data,
            'debug': {
                'user_id': str(request.user.id),
                'username': request.user.username,
                'total_requests_in_schema': all_requests_count,
                'assigned_to_user_count': wo_stats['total'] or 0,
            },
            'metrics': {
                'assigned_work_orders': wo_stats['assigned'] or 0,
                'upcoming_jobs': wo_stats['upcoming'] or 0,
                'overdue_jobs': wo_stats['overdue'] or 0,
                'pending_approvals': (contract_stats['draft'] or 0) + (wo_stats['submitted'] or 0),
                'active_contracts': contract_stats['active'] or 0,
                'payment_summary': {
                    'paid': float(payment_stats['total_paid'] or 0),
                    'pending': float(payment_stats['total_pending'] or 0),
                    'overdue': float(payment_stats['overdue_amount'] or 0),
                    'count_paid': payment_stats['count_paid'] or 0,
                    'count_pending': payment_stats['count_pending'] or 0,
                },
                'rating_summary': {
                    'average_rating': float(vendor.average_rating),
                    'total_reviews': vendor.total_reviews,
                    'recommendation_rate': round((review_stats['recommend_count'] / total_reviews) * 100, 2) if total_reviews > 0 else 0,
                },
                'document_summary': {
                    'license_expiring_soon': bool(vendor.license_expiry and today <= vendor.license_expiry <= soon_threshold),
                    'insurance_expiring_soon': insurance_expiring_soon,
                },
                'notifications_count': notifications_count,
            },
            'recent_work_orders': VendorWorkOrderSerializer(
                work_orders.order_by('-assigned_date', '-requested_date')[:5],
                many=True,
                context={'request': request},
            ).data,
            'recent_contracts': VendorContractSerializer(
                contracts.order_by('-created_at')[:5],
                many=True,
                context={'request': request},
            ).data,
            'recent_payments': VendorPaymentSerializer(
                payments.order_by('-created_at')[:5],
                many=True,
                context={'request': request},
            ).data,
            'recent_notifications': NotificationSerializer(recent_notifications, many=True).data,
        })

    @action(detail=False, methods=['get', 'patch'])
    def profile(self, request):
        vendor = self.get_vendor()

        if request.method == 'PATCH':
            serializer = VendorSerializer(vendor, data=request.data, partial=True, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        serializer = VendorSerializer(vendor, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get', 'patch'])
    def schedule(self, request):
        vendor = self.get_vendor()
        schedules = MaintenanceSchedule.objects.filter(assigned_to=request.user).order_by('next_due_date')

        if request.method == 'PATCH':
            vendor.availability_preferences = request.data.get('availability_preferences', request.data)
            vendor.save(update_fields=['availability_preferences', 'updated_at'])
            return Response({
                'availability_preferences': vendor.availability_preferences,
                'message': 'Availability updated successfully',
            })

        return Response({
            'availability_preferences': vendor.availability_preferences or {},
            'schedules': MaintenanceScheduleSerializer(schedules, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def contracts(self, request):
        vendor = self.get_vendor()
        contracts = vendor.contracts.select_related('created_by').order_by('-created_at')
        return Response(VendorContractSerializer(contracts, many=True, context={'request': request}).data)

    @action(detail=False, methods=['post'], url_path=r'contracts/(?P<contract_id>[^/.]+)/sign')
    def sign_contract(self, request, contract_id=None):
        vendor = self.get_vendor()
        contract = vendor.contracts.filter(pk=contract_id).first()

        if not contract:
            raise NotFound('Contract not found.')

        contract.signed_by_vendor = True
        contract.vendor_signature_date = timezone.now()
        if contract.signed_by_management:
            contract.status = 'active'
        contract.save()

        return Response(VendorContractSerializer(contract, context={'request': request}).data)

    @action(detail=False, methods=['get'])
    def payments(self, request):
        vendor = self.get_vendor()
        payments = vendor.payments.select_related('contract', 'created_by', 'approved_by').order_by('-created_at')
        return Response(VendorPaymentSerializer(payments, many=True, context={'request': request}).data)

    @action(detail=False, methods=['get'])
    def reviews(self, request):
        vendor = self.get_vendor()
        reviews = vendor.reviews.select_related('reviewed_by').order_by('-created_at')
        return Response(VendorReviewSerializer(reviews, many=True, context={'request': request}).data)

    @action(detail=False, methods=['post'], url_path=r'reviews/(?P<review_id>[^/.]+)/respond')
    def respond_review(self, request, review_id=None):
        vendor = self.get_vendor()
        review = vendor.reviews.filter(pk=review_id).first()

        if not review:
            raise NotFound('Review not found.')

        response_text = (request.data.get('response') or '').strip()
        if not response_text:
            return Response({'detail': 'Response text is required.'}, status=status.HTTP_400_BAD_REQUEST)

        review.vendor_response = response_text
        review.responded_at = timezone.now()
        review.save(update_fields=['vendor_response', 'responded_at'])

        return Response(VendorReviewSerializer(review, context={'request': request}).data)

    @action(detail=False, methods=['get'])
    def documents(self, request):
        vendor = self.get_vendor()
        insurance = vendor.insurance_policies.select_related('verified_by').order_by('-expiry_date')
        expiring_soon = insurance.filter(
            expiry_date__gte=timezone.now().date(),
            expiry_date__lte=timezone.now().date() + timedelta(days=30),
        )

        return Response({
            'vendor': VendorSerializer(vendor, context={'request': request}).data,
            'w9_form': vendor.w9_form.url if vendor.w9_form else None,
            'insurance_policies': VendorInsuranceSerializer(insurance, many=True, context={'request': request}).data,
            'insurance_expiring_soon': VendorInsuranceSerializer(expiring_soon, many=True, context={'request': request}).data,
        })

    @action(detail=False, methods=['get'])
    def notifications(self, request):
        notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:50]
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data)


class VendorWorkOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsVendorPortalUser]
    serializer_class = VendorWorkOrderSerializer

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(assigned_to=self.request.user).select_related(
            'requested_by', 'assigned_to', 'unit', 'lease', 'tenant_user', 'owner_user'
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        status_filter = request.query_params.get('status')
        if status_filter and status_filter != 'all':
            queryset = queryset.filter(status=status_filter)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        allowed_fields = {
            'status', 'work_performed', 'parts_used', 'parts_cost',
            'labor_cost', 'total_cost', 'photos_before', 'photos_after',
            'technician_notes',
        }
        payload = {key: value for key, value in request.data.items() if key in allowed_fields}

        if not payload:
            return Response({'detail': 'No vendor-editable fields provided.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(instance, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if serializer.instance.status == 'completed' and not serializer.instance.completed_date:
            serializer.instance.completed_date = timezone.now()
            serializer.instance.save(update_fields=['completed_date'])

        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        instance = self.get_object()
        payload = {
            'status': 'completed',
        }

        for field in ['work_performed', 'parts_used', 'parts_cost', 'labor_cost', 'total_cost', 'photos_after', 'technician_notes']:
            if field in request.data:
                payload[field] = request.data[field]

        serializer = self.get_serializer(instance, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        serializer.instance.completed_date = timezone.now()
        serializer.instance.save(update_fields=['completed_date'])

        return Response(serializer.data)


class VendorCategoryViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing vendor categories
    """
    module = 'vendors'
    queryset = VendorCategory.objects.all()
    serializer_class = VendorCategorySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    
    def get_queryset(self):
        sync_vendor_categories_from_maintenance_choices()
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        return queryset.annotate(vendor_count=Count('vendors'))


class VendorViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing vendors
    """
    module = 'vendors'
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = [
        'vendor_number', 'company_name', 'contact_person',
        'email', 'phone', 'city', 'license_number'
    ]
    ordering_fields = ['company_name', 'average_rating', 'created_at', 'total_jobs']
    filterset_fields = ['status', 'vendor_type', 'is_preferred', 'is_verified']
    
    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related('categories', 'services')
        
        # Filter by category
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(categories__id=category)
        
        # Filter by minimum rating
        min_rating = self.request.query_params.get('min_rating')
        if min_rating:
            queryset = queryset.filter(average_rating__gte=float(min_rating))
        
        return queryset
    
    def perform_create(self, serializer):
        vendor = serializer.save()
        user = vendor.user
        if user and getattr(user, '_raw_password', None):
            try:
                from accounts.email_service import EmailService
                EmailService.send_welcome_email(user, raw_password=user._raw_password)
                logger.info(f"Auto-sent welcome email to vendor {user.email}")
            except Exception as e:
                logger.error(f"Failed to send welcome email to vendor: {e}")
                
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            import logging
            logging.getLogger('django.request').error(f"VENDOR VALIDATION FAILED: {serializer.errors}")
            # fall back to default behavior
            serializer.is_valid(raise_exception=True)
        return super().create(request, *args, **kwargs)
    
    @action(detail=False, methods=['get'], url_path='module-statistics')
    def module_statistics(self, request):
        """Get global vendor module statistics"""
        queryset = self.get_queryset()
        
        vendor_stats = queryset.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(status='active')),
            pending=Count('id', filter=Q(status='pending')),
            preferred=Count('id', filter=Q(is_preferred=True)),
            verified=Count('id', filter=Q(is_verified=True)),
            avg_rating=Avg('average_rating')
        )
        
        from .models import VendorPayment
        payment_stats = VendorPayment.objects.aggregate(
            paid=Sum('amount', filter=Q(status='paid')),
            pending=Sum('amount', filter=Q(status='pending'))
        )
        total_paid = payment_stats['paid'] or 0
        total_pending = payment_stats['pending'] or 0
        
        from maintenance.models import MaintenanceRequest
        # Filter maintenance requests that are assigned to users with vendor roles
        wo_stats = MaintenanceRequest.objects.filter(assigned_to__role__icontains='vendor').aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            in_progress=Count('id', filter=Q(status='in_progress'))
        )
        
        return Response({
            'vendors': {
                'total': vendor_stats['total'] or 0,
                'active': vendor_stats['active'] or 0,
                'pending': vendor_stats['pending'] or 0,
                'preferred': vendor_stats['preferred'] or 0,
                'verified': vendor_stats['verified'] or 0,
            },
            'payments': {
                'total_paid': float(total_paid),
                'total_pending': float(total_pending),
                'total_invoiced': float(total_paid + total_pending),
            },
            'work_orders': {
                'total': wo_stats['total'] or 0,
                'completed': wo_stats['completed'] or 0,
                'in_progress': wo_stats['in_progress'] or 0,
            },
            'avg_rating': float(vendor_stats['avg_rating'] or 0)
        })
    
    @action(detail=False, methods=['get'])
    def preferred_vendors(self, request):
        """Get list of preferred vendors"""
        vendors = self.get_queryset().filter(
            is_preferred=True,
            status='active'
        ).order_by('-average_rating')
        
        page = self.paginate_queryset(vendors)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(vendors, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def top_rated(self, request):
        """Get top rated vendors"""
        limit = int(request.query_params.get('limit', 10))
        
        vendors = self.get_queryset().filter(
            status='active',
            total_reviews__gte=3  # At least 3 reviews
        ).order_by('-average_rating')[:limit]
        
        serializer = self.get_serializer(vendors, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """Verify a vendor"""
        vendor = self.get_object()
        
        if not request.user.is_staff:
            return Response(
                {'error': 'Only staff can verify vendors'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        vendor.is_verified = True
        vendor.verified_by = request.user
        vendor.verified_at = timezone.now()
        vendor.save()
        
        serializer = self.get_serializer(vendor)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def mark_preferred(self, request, pk=None):
        """Mark vendor as preferred"""
        vendor = self.get_object()
        
        vendor.is_preferred = True
        vendor.save()
        
        return Response({'status': 'vendor marked as preferred'})
    
    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        """Suspend a vendor"""
        vendor = self.get_object()
        reason = request.data.get('reason', '')
        
        vendor.status = 'suspended'
        vendor.notes = f"SUSPENDED: {reason}\n{vendor.notes}"
        vendor.save()
        
        return Response({'status': 'vendor suspended'})
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a suspended vendor"""
        vendor = self.get_object()
        
        vendor.status = 'active'
        vendor.save()
        
        return Response({'status': 'vendor activated'})
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """Get vendor statistics"""
        vendor = self.get_object()
        
        contract_stats = vendor.contracts.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(status='active')),
            total_value=Sum('contract_value')
        )
        
        payment_stats = vendor.payments.aggregate(
            paid=Sum('amount', filter=Q(status='paid')),
            pending=Sum('amount', filter=Q(status='pending'))
        )
        total_paid = payment_stats['paid'] or 0
        pending_amount = payment_stats['pending'] or 0
        
        review_stats = vendor.reviews.aggregate(
            total=Count('id'),
            avg_quality=Avg('quality_rating'),
            avg_timeliness=Avg('timeliness_rating'),
            recommend_count=Count('id', filter=Q(would_recommend=True))
        )
        total_reviews = review_stats['total'] or 0
        recommendation_rate = (review_stats['recommend_count'] / total_reviews * 100) if total_reviews > 0 else 0
        
        return Response({
            'vendor': {
                'total_jobs': vendor.total_jobs,
                'total_reviews': vendor.total_reviews,
                'average_rating': float(vendor.average_rating)
            },
            'contracts': {
                'total': contract_stats['total'] or 0,
                'active': contract_stats['active'] or 0,
                'total_value': float(contract_stats['total_value'] or 0)
            },
            'payments': {
                'total_paid': float(total_paid),
                'pending': float(pending_amount),
                'total_invoiced': float(total_paid + pending_amount)
            },
            'reviews': {
                'total': total_reviews,
                'average_quality': review_stats['avg_quality'] or 0,
                'average_timeliness': review_stats['avg_timeliness'] or 0,
                'recommendation_rate': recommendation_rate
            }
        })


class VendorServiceViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing vendor services
    """
    module = 'vendors'
    queryset = VendorService.objects.all()
    serializer_class = VendorServiceSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['service_name', 'description']
    ordering_fields = ['service_name', 'base_price', 'created_at']
    filterset_fields = ['vendor', 'category', 'pricing_type', 'is_active']
    
    def get_queryset(self):
        return super().get_queryset().select_related('vendor', 'category')


class VendorContractViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing vendor contracts
    """
    module = 'vendors'
    queryset = VendorContract.objects.all()
    serializer_class = VendorContractSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['contract_number', 'title', 'vendor__company_name']
    ordering_fields = ['created_at', 'start_date', 'contract_value']
    filterset_fields = ['status', 'contract_type', 'vendor']
    
    def get_queryset(self):
        return super().get_queryset().select_related('vendor', 'created_by')
    
    @action(detail=False, methods=['get'])
    def active_contracts(self, request):
        """Get active contracts"""
        contracts = self.get_queryset().filter(
            status='active',
            start_date__lte=timezone.now().date()
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.now().date())
        )
        
        page = self.paginate_queryset(contracts)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(contracts, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        """Get contracts expiring within 30 days"""
        days = int(request.query_params.get('days', 30))
        end_date = timezone.now().date() + timedelta(days=days)
        
        contracts = self.get_queryset().filter(
            status='active',
            end_date__lte=end_date,
            end_date__gte=timezone.now().date()
        ).order_by('end_date')
        
        serializer = self.get_serializer(contracts, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def sign_by_vendor(self, request, pk=None):
        """Mark contract as signed by vendor"""
        contract = self.get_object()
        
        contract.signed_by_vendor = True
        contract.vendor_signature_date = timezone.now()
        
        # Auto-activate if both parties signed
        if contract.signed_by_management:
            contract.status = 'active'
        
        contract.save()
        
        serializer = self.get_serializer(contract)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def sign_by_management(self, request, pk=None):
        """Mark contract as signed by management"""
        contract = self.get_object()
        
        contract.signed_by_management = True
        contract.management_signature_date = timezone.now()
        
        # Auto-activate if both parties signed
        if contract.signed_by_vendor:
            contract.status = 'active'
        
        contract.save()
        
        serializer = self.get_serializer(contract)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def terminate(self, request, pk=None):
        """Terminate a contract"""
        contract = self.get_object()
        
        contract.status = 'terminated'
        contract.save()
        
        return Response({'status': 'contract terminated'})


class VendorReviewViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing vendor reviews
    """
    module = 'vendors'
    queryset = VendorReview.objects.all()
    serializer_class = VendorReviewSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['title', 'comment', 'vendor__company_name']
    ordering_fields = ['created_at', 'overall_rating']
    filterset_fields = ['vendor', 'overall_rating', 'would_recommend', 'is_verified']
    
    def get_queryset(self):
        queryset = super().get_queryset().select_related('vendor', 'reviewed_by')
        
        # Filter by minimum rating
        min_rating = self.request.query_params.get('min_rating')
        if min_rating:
            queryset = queryset.filter(overall_rating__gte=int(min_rating))
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """Verify a review"""
        review = self.get_object()
        
        if not request.user.is_staff:
            return Response(
                {'error': 'Only staff can verify reviews'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        review.is_verified = True
        review.save()
        
        return Response({'status': 'review verified'})
    
    @action(detail=True, methods=['post'])
    def add_response(self, request, pk=None):
        """Add vendor response to review"""
        review = self.get_object()
        response_text = request.data.get('response', '')
        
        if not response_text:
            return Response(
                {'error': 'Response text is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        review.vendor_response = response_text
        review.responded_at = timezone.now()
        review.save()
        
        serializer = self.get_serializer(review)
        return Response(serializer.data)


class VendorPaymentViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing vendor payments
    """
    module = 'vendors'
    queryset = VendorPayment.objects.all()
    serializer_class = VendorPaymentSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['payment_number', 'invoice_number', 'vendor__company_name']
    ordering_fields = ['created_at', 'due_date', 'amount']
    filterset_fields = ['status', 'vendor', 'contract']
    
    def get_queryset(self):
        return super().get_queryset().select_related(
            'vendor', 'contract', 'created_by', 'approved_by'
        )
    
    @action(detail=False, methods=['get'])
    def pending_payments(self, request):
        """Get pending payments"""
        payments = self.get_queryset().filter(
            status='pending'
        ).order_by('due_date')
        
        page = self.paginate_queryset(payments)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(payments, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def overdue_payments(self, request):
        """Get overdue payments"""
        payments = self.get_queryset().filter(
            status__in=['pending', 'processing'],
            due_date__lt=timezone.now().date()
        ).order_by('due_date')
        
        serializer = self.get_serializer(payments, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a payment"""
        payment = self.get_object()
        
        if payment.status != 'pending':
            return Response(
                {'error': 'Only pending payments can be approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment.status = 'processing'
        payment.approved_by = request.user
        payment.approved_at = timezone.now()
        payment.save()
        
        serializer = self.get_serializer(payment)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """Mark payment as paid"""
        payment = self.get_object()
        
        payment.status = 'paid'
        payment.paid_date = timezone.now().date()
        payment.save()
        
        serializer = self.get_serializer(payment)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def payment_summary(self, request):
        """Get payment summary statistics"""
        payments = self.get_queryset()
        
        total_paid = payments.filter(status='paid').aggregate(
            total=Sum('amount')
        )['total'] or 0
        
        total_pending = payments.filter(status='pending').aggregate(
            total=Sum('amount')
        )['total'] or 0
        
        total_overdue = payments.filter(
            status__in=['pending', 'processing'],
            due_date__lt=timezone.now().date()
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_paid': float(total_paid),
            'total_pending': float(total_pending),
            'total_overdue': float(total_overdue),
            'count_paid': payments.filter(status='paid').count(),
            'count_pending': payments.filter(status='pending').count(),
            'count_overdue': payments.filter(
                status__in=['pending', 'processing'],
                due_date__lt=timezone.now().date()
            ).count()
        })


class VendorInsuranceViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing vendor insurance certificates
    """
    module = 'vendors'
    queryset = VendorInsurance.objects.all()
    serializer_class = VendorInsuranceSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['policy_number', 'insurance_company', 'vendor__company_name']
    ordering_fields = ['expiry_date', 'created_at']
    filterset_fields = ['vendor', 'insurance_type', 'is_verified']
    
    def get_queryset(self):
        return super().get_queryset().select_related('vendor', 'verified_by')
    
    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        """Get insurance expiring within 60 days"""
        days = int(request.query_params.get('days', 60))
        end_date = timezone.now().date() + timedelta(days=days)
        
        insurance = self.get_queryset().filter(
            expiry_date__lte=end_date,
            expiry_date__gte=timezone.now().date()
        ).order_by('expiry_date')
        
        serializer = self.get_serializer(insurance, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def expired(self, request):
        """Get expired insurance"""
        insurance = self.get_queryset().filter(
            expiry_date__lt=timezone.now().date()
        ).order_by('-expiry_date')
        
        serializer = self.get_serializer(insurance, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """Verify insurance certificate"""
        insurance = self.get_object()
        
        if not request.user.is_staff:
            return Response(
                {'error': 'Only staff can verify insurance'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        insurance.is_verified = True
        insurance.verified_by = request.user
        insurance.verified_at = timezone.now()
        insurance.save()
        
        serializer = self.get_serializer(insurance)
        return Response(serializer.data)