# amenities/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q, Count, Sum, Avg
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from datetime import datetime, timedelta
from decimal import Decimal
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from accounts.permissions import ModulePermissionMixin, HasModulePermission

from .models import (
    Amenity, AmenityBooking, AmenityReview, AmenityMaintenance,
    AmenityUsageLog, AmenityRule, AmenityBlockAssignment
)
from .serializers import (
    AmenitySerializer, AmenityListSerializer, AmenityBookingSerializer,
    AmenityBookingCreateSerializer, AmenityReviewSerializer,
    AmenityMaintenanceSerializer, AmenityUsageLogSerializer,
    AmenityRuleSerializer, AmenityDashboardSerializer
)
from properties.models import Building, Block, Unit
from payments.models import Invoice
from notifications.services import NotificationService


def _is_facility_manager(user):
    return bool(user and user.is_authenticated and getattr(user, 'role', None) == 'facility_manager')


def _get_user_block_ids(user):
    if not user or not user.is_authenticated:
        return []
        
    b_name = (user.building_name or '').strip()
    u_num = (user.unit_number or '').strip()
    
    if not b_name:
        return []

    # Get units for this user (could be multiple if they have multiple leases)
    units_qs = Unit.objects.filter(building__name__iexact=b_name)
    if u_num:
        units_qs = units_qs.filter(unit_number__iexact=u_num)
    
    # 1. Direct floor_ref -> block lookup
    block_ids = set(
        units_qs.exclude(floor_ref__block__isnull=True).values_list('floor_ref__block_id', flat=True)
    )

    # 2. String-based fallback (matching Block name to Unit.block field)
    if not block_ids:
        block_names = [
            str(name).strip()
            for name in units_qs.exclude(block__isnull=True).exclude(block='').values_list('block', flat=True)
            if str(name).strip()
        ]
        if block_names:
            mapped = Block.objects.filter(
                building__name__iexact=b_name,
                name__in=block_names,
            ).values_list('id', flat=True)
            block_ids.update(mapped)

    # 3. Last resort: If no blocks found but we have a building, maybe show all blocks in that building?
    # No, that might be too much. We stay strict to assignments or global.
    
    return list(block_ids)

def _get_manager_block_ids(user):
    if not _is_facility_manager(user):
        return None
    try:
        return list(user.managed_blocks.values_list('id', flat=True))
    except Exception:
        return []


class AmenityViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'amenities'
    queryset = Amenity.objects.all().select_related('created_by')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['amenity_type', 'status', 'is_bookable', 'building']
    search_fields = ['name', 'description', 'location_details']
    ordering_fields = ['name', 'created_at', 'rating_average']
    ordering = ['name']

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related('block_assignments__block__building')
        user = self.request.user

        if not user or not user.is_authenticated:
            return queryset.none()

        role = getattr(user, 'role', None)
        
        # Base filter: either assigned to specific blocks or global (no assignments)
        if _is_facility_manager(user):
            from accounts.fm_scope import get_fm_building_ids
            building_ids = get_fm_building_ids(user)
            block_ids = _get_manager_block_ids(user)
            
            if block_ids:
                queryset = queryset.filter(
                    Q(block_assignments__block_id__in=block_ids) | 
                    Q(block_assignments__isnull=True)
                )
            elif building_ids:
                queryset = queryset.filter(
                    Q(block_assignments__block__building_id__in=list(building_ids)) |
                    Q(block_assignments__isnull=True)
                )
            else:
                # If FM has no assignments, show only global amenities
                queryset = queryset.filter(block_assignments__isnull=True)
            
            queryset = queryset.distinct()
        elif role in ['tenant', 'owner', 'tenant_vendor']:
            user_block_ids = _get_user_block_ids(user)
            if user_block_ids:
                queryset = queryset.filter(
                    Q(block_assignments__block_id__in=user_block_ids) | Q(block_assignments__isnull=True)
                ).distinct()
            else:
                # Fallback for residents without clear block mapping: show global amenities
                queryset = queryset.filter(block_assignments__isnull=True)

        return queryset
    
    def get_serializer_class(self):
        if self.action == 'list':
            return AmenityListSerializer
        return AmenitySerializer
    
    @action(detail=False, methods=['get'])
    def available(self, request):
        amenities = self.get_queryset().filter(status='available', is_bookable=True)
        serializer = self.get_serializer(amenities, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def availability(self, request, pk=None):
        amenity = self.get_object()
        date_str = request.query_params.get('date', timezone.now().date().isoformat())
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        bookings = AmenityBooking.objects.filter(
            amenity=amenity,
            booking_date=date,
            status__in=['approved', 'confirmed', 'checked_in']
        ).order_by('start_time')
        
        booked_slots = [
            {
                'start_time': b.start_time.strftime('%H:%M'),
                'end_time': b.end_time.strftime('%H:%M'),
                'booking_id': str(b.id)
            }
            for b in bookings
        ]
        
        return Response({
            'amenity': amenity.name,
            'date': date.isoformat(),
            'is_available': amenity.status == 'available',
            'booked_slots': booked_slots
        })
    
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        amenity = self.get_object()
        period = int(request.query_params.get('days', 30))
        start_date = timezone.now() - timedelta(days=period)
        
        stats = amenity.bookings.filter(created_at__gte=start_date).aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            cancelled=Count('id', filter=Q(status='cancelled')),
            no_show=Count('id', filter=Q(status='no_show')),
            revenue=Sum('total_amount', filter=Q(payment_status='paid'))
        )
        
        return Response({
            'total_bookings': stats['total'] or 0,
            'completed_bookings': stats['completed'] or 0,
            'cancelled_bookings': stats['cancelled'] or 0,
            'no_shows': stats['no_show'] or 0,
            'average_rating': amenity.rating_average,
            'total_reviews': amenity.review_count,
            'total_revenue': stats['revenue'] or 0
        })

    @action(detail=True, methods=['post'])
    def assign_blocks(self, request, pk=None):
        amenity = self.get_object()
        block_ids = request.data.get('block_ids', [])
        if block_ids is None:
            block_ids = []
        if not isinstance(block_ids, list):
            return Response({'error': 'block_ids must be a list.'}, status=status.HTTP_400_BAD_REQUEST)

        blocks = Block.objects.filter(id__in=block_ids).select_related('building')
        if len(block_ids) != blocks.count():
            return Response({'error': 'One or more blocks are invalid.'}, status=status.HTTP_400_BAD_REQUEST)

        if _is_facility_manager(request.user):
            allowed_buildings = set(
                Building.objects.filter(
                    Q(managed_by=request.user) | Q(township__managed_by=request.user)
                ).values_list('id', flat=True)
            )
            allowed_block_ids = set(_get_manager_block_ids(request.user) or [])
            if not allowed_block_ids:
                return Response(
                    {'error': 'You do not have any assigned blocks.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if any(block.id not in allowed_block_ids for block in blocks):
                return Response(
                    {'error': 'You can assign only your assigned blocks.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        amenity.block_assignments.exclude(block_id__in=[b.id for b in blocks]).delete()
        existing_ids = set(amenity.block_assignments.values_list('block_id', flat=True))
        create_rows = [
            AmenityBlockAssignment(amenity=amenity, block=block, created_by=request.user)
            for block in blocks
            if block.id not in existing_ids
        ]
        if create_rows:
            AmenityBlockAssignment.objects.bulk_create(create_rows)

        serializer = AmenitySerializer(amenity, context={'request': request})
        return Response({'message': 'Block assignments updated successfully.', 'amenity': serializer.data})


class AmenityBookingViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'amenities'
    queryset = AmenityBooking.objects.all().select_related('amenity', 'booked_by', 'approved_by')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['amenity', 'status', 'payment_status', 'booking_date']
    search_fields = ['booking_number', 'purpose']
    ordering_fields = ['booking_date', 'created_at']
    ordering = ['-booking_date', '-start_time']

    def get_queryset(self):
        queryset = super().get_queryset().select_related('amenity', 'booked_by', 'approved_by')
        user = self.request.user

        if not user or not user.is_authenticated:
            return queryset.none()

        role = getattr(user, 'role', None)
        if _is_facility_manager(user):
            from accounts.fm_scope import get_fm_building_names
            building_names = get_fm_building_names(user)
            
            if building_names:
                queryset = queryset.filter(
                    Q(booked_by__building_name__in=building_names) |
                    Q(amenity__block_assignments__block_id__in=_get_manager_block_ids(user) or []) |
                    Q(amenity__block_assignments__isnull=True)  # See global amenity bookings too
                ).distinct()
            else:
                # If no specific buildings assigned, only show global amenity bookings
                queryset = queryset.filter(amenity__block_assignments__isnull=True)
        elif role in ['tenant', 'owner', 'tenant_vendor']:
            queryset = queryset.filter(booked_by=user)

        return queryset
    
    def get_required_permission(self):
        if self.action in ['create', 'cancel', 'checkin', 'checkout']:
            return 'amenities.book'
            
        # Fallback to default
        action = getattr(self, 'action', None)
        if action:
            from accounts.permissions import HasModulePermission
            suffix = HasModulePermission.ACTION_MAP.get(action, action)
            return f"{self.module}.{suffix}"
            
        return f"{self.module}.view"
        
    def list(self, request, *args, **kwargs):
        # Auto-heal any stale 'pending' bookings that were paid prior to the sync hook
        try:
            from payments.models import Invoice
            pending_bookings = AmenityBooking.objects.filter(payment_status='pending', total_amount__gt=0)
            # Limit to prevent long load times if there's a massive backlog
            for booking in pending_bookings[:50]:
                invoice = Invoice.objects.filter(
                    invoice_type='amenity_fee',
                    status='paid',
                    notes__icontains=booking.booking_number
                ).first()
                if invoice:
                    booking.payment_status = 'paid'
                    booking.payment_reference = invoice.invoice_number
                    booking.save(update_fields=['payment_status', 'payment_reference', 'updated_at'])
        except Exception as e:
            pass
            
        return super().list(request, *args, **kwargs)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return AmenityBookingCreateSerializer
        return AmenityBookingSerializer
    
    def perform_create(self, serializer):
        booking = serializer.save(booked_by=self.request.user)
        
        if booking.amenity.requires_approval:
            booking.status = 'pending'
        else:
            booking.status = 'confirmed'
        booking.save()

        # Send Notification
        if booking.status == 'pending':
            NotificationService.send_amenity_notification(booking, 'booking_requested')
        else:
            NotificationService.send_amenity_notification(booking, 'booking_confirmed')
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        booking = self.get_object()
        
        if booking.status != 'pending':
            return Response({'error': 'Booking is not pending'}, status=status.HTTP_400_BAD_REQUEST)
        
        booking.status = 'approved'
        booking.approved_by = request.user
        booking.approved_at = timezone.now()
        
        # Force-recalculate total_amount if the amenity is paid but total_amount is 0
        # This handles bookings that may have been created with a stale/missing price
        if booking.amenity.is_paid and (not booking.total_amount or booking.total_amount == 0):
            from decimal import Decimal
            duration = Decimal(str(booking.duration_hours or 0))
            booking.booking_fee = booking.amenity.price_per_hour * duration
            booking.security_deposit = booking.amenity.security_deposit
            booking.total_amount = booking.booking_fee + booking.security_deposit
        
        booking.save()

        # Send Notification
        NotificationService.send_amenity_notification(booking, 'booking_approved')
        
        return Response({
            'message': 'Booking approved successfully',
            'booking': AmenityBookingSerializer(booking).data
        })
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        booking = self.get_object()
        
        if booking.status != 'pending':
            return Response({'error': 'Booking is not pending'}, status=status.HTTP_400_BAD_REQUEST)
        
        booking.status = 'rejected'
        booking.rejection_reason = request.data.get('reason', '')
        booking.save()

        # Send Notification
        NotificationService.send_amenity_notification(booking, 'booking_rejected')
        
        return Response({
            'message': 'Booking rejected',
            'booking': AmenityBookingSerializer(booking).data
        })
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        
        if booking.status in ['cancelled', 'completed']:
            return Response({'error': 'Cannot cancel this booking'}, status=status.HTTP_400_BAD_REQUEST)
        
        booking.status = 'cancelled'
        booking.cancelled_at = timezone.now()
        booking.cancelled_by = request.user
        booking.cancellation_reason = request.data.get('reason', '')
        booking.save()

        # Send Notification
        NotificationService.send_amenity_notification(booking, 'booking_cancelled')
        
        # Calculate refund
        if booking.total_amount > 0:
            booking.refund_amount = booking.total_amount - booking.amenity.cancellation_fee
            booking.payment_status = 'refunded'
            booking.save()
        
        return Response({
            'message': 'Booking cancelled',
            'refund_amount': float(booking.refund_amount),
            'booking': AmenityBookingSerializer(booking).data
        })
    
    @action(detail=True, methods=['post'])
    def checkin(self, request, pk=None):
        booking = self.get_object()
        
        if booking.status != 'confirmed':
            return Response({'error': 'Booking must be confirmed'}, status=status.HTTP_400_BAD_REQUEST)
        
        booking.checked_in_at = timezone.now()
        booking.checked_in_by = request.user
        booking.status = 'checked_in'
        booking.save()
        
        return Response({
            'message': 'Checked in successfully',
            'booking': AmenityBookingSerializer(booking).data
        })
    
    @action(detail=True, methods=['post'])
    def checkout(self, request, pk=None):
        booking = self.get_object()
        
        if booking.status != 'checked_in':
            return Response({'error': 'Must be checked in first'}, status=status.HTTP_400_BAD_REQUEST)
        
        booking.checked_out_at = timezone.now()
        booking.status = 'completed'
        booking.save()

        if booking.checked_in_at:
            duration_minutes = int((booking.checked_out_at - booking.checked_in_at).total_seconds() // 60)
            entry_time = booking.checked_in_at
        else:
            duration_minutes = int(float(booking.duration_hours or 0) * 60)
            entry_time = booking.checked_out_at - timedelta(minutes=duration_minutes)

        AmenityUsageLog.objects.create(
            amenity=booking.amenity,
            booking=booking,
            user=booking.booked_by,
            entry_time=entry_time,
            exit_time=booking.checked_out_at,
            duration_minutes=max(duration_minutes, 0),
            people_count=booking.number_of_people,
            entry_method='booking',
            verified_by=request.user,
        )
        
        return Response({
            'message': 'Checked out successfully',
            'booking': AmenityBookingSerializer(booking).data
        })
    
    @action(detail=False, methods=['get'])
    def my_bookings(self, request):
        bookings = self.queryset.filter(booked_by=request.user)
        serializer = self.get_serializer(bookings, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        today = timezone.now().date()
        bookings = self.queryset.filter(
            booking_date__gte=today,
            status__in=['confirmed', 'approved', 'pending']
        )
        serializer = self.get_serializer(bookings, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def usage_summary(self, request):
        qs = self.get_queryset().filter(status='completed')

        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        amenity_id = request.query_params.get('amenity')
        block_id = request.query_params.get('block')

        if start_date:
            qs = qs.filter(booking_date__gte=start_date)
        if end_date:
            qs = qs.filter(booking_date__lte=end_date)
        if amenity_id:
            qs = qs.filter(amenity_id=amenity_id)
        if block_id:
            qs = qs.filter(amenity__block_assignments__block_id=block_id)

        summary = []
        for row in qs.values('amenity_id', 'amenity__name').annotate(
            total_bookings=Count('id'),
            total_hours=Sum('duration_hours'),
            total_people=Sum('number_of_people'),
            usage_revenue=Sum('total_amount'),
        ):
            summary.append(
                {
                    'amenity_id': str(row['amenity_id']),
                    'amenity_name': row['amenity__name'],
                    'total_bookings': row['total_bookings'] or 0,
                    'total_hours': float(row['total_hours'] or 0),
                    'total_people': row['total_people'] or 0,
                    'usage_revenue': float(row['usage_revenue'] or 0),
                }
            )

        return Response(
            {
                'start_date': start_date,
                'end_date': end_date,
                'results': summary,
            }
        )

    @action(detail=False, methods=['post'])
    def generate_usage_bills(self, request):
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        amenity_id = request.data.get('amenity')
        block_id = request.data.get('block')

        bookings = self.get_queryset().filter(status='completed', amenity__is_paid=True)
        if start_date:
            bookings = bookings.filter(booking_date__gte=start_date)
        if end_date:
            bookings = bookings.filter(booking_date__lte=end_date)
        if amenity_id:
            bookings = bookings.filter(amenity_id=amenity_id)
        if block_id:
            bookings = bookings.filter(amenity__block_assignments__block_id=block_id)

        created = 0
        skipped = 0
        generated_invoices = []

        for booking in bookings.select_related('amenity', 'booked_by').distinct():
            existing = Invoice.objects.filter(
                invoice_type='amenity_fee',
                notes__icontains=booking.booking_number,
            ).first()
            if existing:
                skipped += 1
                continue

            amount = Decimal(str(booking.total_amount or 0))
            if amount <= 0:
                calculated_amount = Decimal(str(booking.amenity.price_per_hour or 0)) * Decimal(
                    str(booking.duration_hours or 0)
                )
                amount = calculated_amount

            if amount <= 0:
                skipped += 1
                continue

            invoice = Invoice.objects.create(
                user=booking.booked_by,
                invoice_type='amenity_fee',
                building=booking.booked_by.building_name or booking.amenity.building or 'N/A',
                unit_number=booking.booked_by.unit_number or 'N/A',
                subtotal=amount,
                issue_date=timezone.now().date(),
                due_date=booking.booking_date,
                description=f"Amenity usage fee - {booking.amenity.name}",
                notes=f"Booking #{booking.booking_number}",
                status='sent',
                created_by=request.user,
            )
            created += 1
            generated_invoices.append({'invoice_id': str(invoice.id), 'invoice_number': invoice.invoice_number})

        return Response(
            {
                'message': 'Usage billing run completed.',
                'created_invoices': created,
                'skipped_bookings': skipped,
                'invoices': generated_invoices,
            },
            status=status.HTTP_200_OK,
        )


class AmenityReviewViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'amenities'
    queryset = AmenityReview.objects.all().select_related('amenity', 'user', 'booking')
    serializer_class = AmenityReviewSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['amenity', 'rating', 'is_published']
    ordering_fields = ['created_at', 'rating', 'helpful_count']
    ordering = ['-created_at']
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def mark_helpful(self, request, pk=None):
        review = self.get_object()
        review.helpful_count += 1
        review.save()
        return Response({'helpful_count': review.helpful_count})
    
    @action(detail=True, methods=['post'])
    def respond(self, request, pk=None):
        review = self.get_object()
        response = request.data.get('response', '')
        
        review.management_response = response
        review.responded_at = timezone.now()
        review.responded_by = request.user
        review.save()
        
        return Response({
            'message': 'Response added successfully',
            'review': AmenityReviewSerializer(review).data
        })


class AmenityMaintenanceViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'amenities'
    queryset = AmenityMaintenance.objects.all().select_related('amenity', 'assigned_to', 'created_by')
    serializer_class = AmenityMaintenanceSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['amenity', 'status', 'maintenance_type']
    ordering_fields = ['scheduled_date', 'created_at']
    ordering = ['-scheduled_date']
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        maintenance = self.get_object()
        
        maintenance.status = 'completed'
        maintenance.actual_end = timezone.now()
        maintenance.completed_by = request.user
        maintenance.completion_notes = request.data.get('notes', '')
        maintenance.actual_cost = request.data.get('actual_cost', 0)
        maintenance.save()
        
        return Response({
            'message': 'Maintenance completed',
            'maintenance': AmenityMaintenanceSerializer(maintenance).data
        })


class AmenityUsageLogViewSet(ModulePermissionMixin, viewsets.ReadOnlyModelViewSet):
    module = 'amenities'
    queryset = AmenityUsageLog.objects.all().select_related('amenity', 'user', 'booking')
    serializer_class = AmenityUsageLogSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['amenity', 'user']
    ordering = ['-entry_time']


class AmenityRuleViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'amenities'
    queryset = AmenityRule.objects.all().select_related('amenity', 'created_by')
    serializer_class = AmenityRuleSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['amenity', 'is_active', 'is_mandatory']
    ordering = ['-priority']


@cache_page(300)
@extend_schema(responses=AmenityDashboardSerializer)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def amenity_dashboard(request):
    amenity_stats = Amenity.objects.aggregate(
        total=Count('id'),
        available=Count('id', filter=Q(status='available'))
    )
    
    today = timezone.now().date()
    current_month = timezone.now().replace(day=1)
    
    booking_stats = AmenityBooking.objects.aggregate(
        today_bookings=Count('id', filter=Q(booking_date=today)),
        active_bookings=Count('id', filter=Q(status='checked_in')),
        pending_approvals=Count('id', filter=Q(status='pending')),
        revenue=Sum('total_amount', filter=Q(created_at__gte=current_month, payment_status='paid'))
    )
    
    data = {
        'total_amenities': amenity_stats['total'] or 0,
        'available_amenities': amenity_stats['available'] or 0,
        'total_bookings_today': booking_stats['today_bookings'] or 0,
        'active_bookings': booking_stats['active_bookings'] or 0,
        'pending_approvals': booking_stats['pending_approvals'] or 0,
        'revenue_this_month': booking_stats['revenue'] or 0
    }
    
    serializer = AmenityDashboardSerializer(data)
    return Response(serializer.data)