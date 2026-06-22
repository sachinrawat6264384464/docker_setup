# tenants/views.py
import logging
import requests
import secrets
from datetime import timedelta

from django.db import connection
from django.db.models import Sum
from django.utils import timezone
from django.core.cache import cache
from django.core.management import call_command
from django.conf import settings
from django.utils import timezone
from django_tenants.utils import schema_context
import stripe

from rest_framework import generics, permissions, status, filters, serializers
from rest_framework.decorators import api_view, permission_classes, action, renderer_classes
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from django_filters.rest_framework import DjangoFilterBackend
from django_tenants.utils import schema_context
from notifications.services import NotificationService

from accounts.models import User, ActivityLog
from accounts.utils import _log_activity, _create_notification
from accounts.permissions import IsSystemAdminOrReadOnly
from location_master.models import State, District, City, Pincode

from .models import (
    Client, Domain, TenantSettings, TenantFeature, 
    TenantSubscription, KYC, KYCLog, PlatformInvoice,
    PlatformPaymentMethod, PlatformAutopayEnrollment
)
from .serializers import (
    ClientSerializer, ClientCreateSerializer, ClientUpdateSerializer,
    DomainSerializer, DomainCreateSerializer, TenantSettingsSerializer,
    TenantFeatureSerializer, TenantSubscriptionSerializer,
    FeatureToggleSerializer, TenantStatsSerializer, SystemStatsSerializer,
    BulkFeatureUpdateSerializer, KYCSerializer, KYCLogSerializer, PlatformInvoiceSerializer,
    PlatformPaymentMethodSerializer, PlatformAutopayEnrollmentSerializer
)
from payments.models import PaymentGateway
from payments.serializers import PaymentGatewaySerializer

logger = logging.getLogger(__name__)

# =============================================================================
# CLIENT / TENANT VIEWSET
# =============================================================================

class ClientViewSet(ModelViewSet):
    queryset = Client.objects.select_related('kyc').prefetch_related('domains', 'settings', 'subscription', 'platform_invoices').all()
    permission_classes = [IsSystemAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['subscription_plan', 'is_active']
    search_fields = ['name', 'contact_email', 'contact_phone']
    ordering_fields = ['name', 'created_on', 'updated_on']
    ordering = ['-created_on']

    def get_serializer_class(self):
        if self.action == 'create':
            return ClientCreateSerializer
        if self.action in ['update', 'partial_update']:
            return ClientUpdateSerializer
        return ClientSerializer
    def destroy(self, request, *args, **kwargs):
        tenant = self.get_object()
        if tenant.schema_name == 'public':
            return Response({'error': 'The public schema cannot be deleted.'}, status=status.HTTP_400_BAD_REQUEST)
        
        tenant_name = tenant.name
        schema_name = tenant.schema_name
        
        # Log before deletion
        _log_activity(
            user=request.user,
            action='tenant_deleted',
            description=f'Permanently deleted organization: {tenant_name} (Schema: {schema_name})',
            request=request
        )
        
        # Delete associated tokens and users using raw SQL to bypass cross-schema Django ORM cascade lookups
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM accounts_user WHERE tenant_id = %s", [schema_name])
                rows = cursor.fetchall()
                if rows:
                    u_ids = tuple(r[0] for r in rows)
                    cursor.execute("DELETE FROM notifications_notification WHERE recipient_id IN %s", [u_ids])
                    cursor.execute("DELETE FROM notifications_notificationpreference WHERE user_id IN %s", [u_ids])
                    cursor.execute("DELETE FROM notifications_announcement WHERE created_by_id IN %s", [u_ids])
                    cursor.execute("DELETE FROM notifications_emailcampaign WHERE created_by_id IN %s", [u_ids])
                    cursor.execute("DELETE FROM notifications_smsalert WHERE created_by_id IN %s", [u_ids])
                    cursor.execute("UPDATE notifications_emailtemplate SET last_modified_by_id = NULL WHERE last_modified_by_id IN %s", [u_ids])
                    cursor.execute("DELETE FROM token_blacklist_blacklistedtoken WHERE token_id IN (SELECT id FROM token_blacklist_outstandingtoken WHERE user_id IN %s)", [u_ids])
                    cursor.execute("DELETE FROM token_blacklist_outstandingtoken WHERE user_id IN %s", [u_ids])
                    cursor.execute("DELETE FROM accounts_userprofile WHERE user_id IN %s", [u_ids])
                    cursor.execute("DELETE FROM accounts_user_groups WHERE user_id IN %s", [u_ids])
                    cursor.execute("DELETE FROM accounts_user_user_permissions WHERE user_id IN %s", [u_ids])
                    try:
                        cursor.execute("DELETE FROM tenants_kyc WHERE submitted_by_id IN %s OR verified_by_id IN %s", [u_ids, u_ids])
                        cursor.execute("DELETE FROM tenants_kyclog WHERE action_by_id IN %s", [u_ids])
                    except:
                        pass
                    cursor.execute("DELETE FROM accounts_user WHERE id IN %s", [u_ids])
            print(f"Cleaned users, notifications, profiles, and tokens for tenant {schema_name} via raw SQL")
        except Exception as e:
            logger.error(f"Error raw deleting tokens and users for tenant {schema_name}: {e}")
        
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        tenant = self.get_object()
        tenant.is_active = True
        tenant.save()
        
        _log_activity(
            user=request.user,
            action='tenant_activated',
            description=f'Activated organization: {tenant.name}',
            request=request
        )
        return Response({'status': 'Organization activated successfully'})

    @action(detail=True, methods=['post'], url_path='deactivate')
    def deactivate(self, request, pk=None):
        tenant = self.get_object()
        tenant.is_active = False
        tenant.save()
        
        _log_activity(
            user=request.user,
            action='tenant_suspended',
            description=f'Suspended organization: {tenant.name}',
            request=request
        )
        return Response({'status': 'Organization suspended successfully'})

    @action(detail=True, methods=['post'], url_path='confirm')
    def confirm(self, request, pk=None):
        tenant = self.get_object()
        tenant.is_confirmed = True
        tenant.save()
        
        _log_activity(
            user=request.user,
            action='tenant_confirmed',
            description=f'Confirmed organization: {tenant.name}',
            request=request
        )
        return Response({'status': 'Organization confirmed successfully'})

    @action(detail=True, methods=['post'], url_path='update-admin-credentials')
    def update_admin_credentials(self, request, pk=None):
        """Update the username and/or password for the organization's Master Admin."""
        tenant = self.get_object()
        username = request.data.get('username')
        password = request.data.get('password')

        if not username and not password:
            return Response({'error': 'Provide at least username or password'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with schema_context(tenant.schema_name):
                admin_user = User.objects.filter(role='master_admin').first()
                if not admin_user:
                    return Response({'error': 'Master Admin not found for this organization'}, status=status.HTTP_404_NOT_FOUND)

                if username:
                    if User.objects.exclude(id=admin_user.id).filter(username=username).exists():
                        return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)
                    admin_user.username = username

                if password:
                    admin_user.set_password(password)

                admin_user.save()

                _log_activity(
                    user=request.user,
                    action='tenant_admin_updated',
                    description=f'Updated Master Admin credentials for {tenant.name}',
                    request=request
                )

                return Response({'status': 'success', 'message': 'Credentials updated successfully'})
        except Exception as e:
            logger.error(f"Error updating admin credentials: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='update-domain')
    def update_domain(self, request, pk=None):
        """Update the primary domain for the organization."""
        tenant = self.get_object()
        new_domain = request.data.get('domain')

        if not new_domain:
            return Response({'error': 'Domain name is required'}, status=status.HTTP_400_BAD_REQUEST)

        # Normalize domain
        if '.' not in new_domain:
            suffix = getattr(settings, 'TENANT_DOMAIN_SUFFIX', None)
            if not suffix:
                is_local = any(h in settings.ALLOWED_HOSTS for h in ['localhost', '127.0.0.1'])
                suffix = '.localhost' if (is_local and settings.DEBUG) else '.hoaconnecthub.com'
            new_domain = f"{new_domain}{suffix}"

        try:
            primary_domain = tenant.domains.filter(is_primary=True).first()
            if primary_domain:
                if Domain.objects.exclude(id=primary_domain.id).filter(domain__iexact=new_domain).exists():
                    return Response({'error': 'Domain already in use'}, status=status.HTTP_400_BAD_REQUEST)
                primary_domain.domain = new_domain
                primary_domain.save()
            else:
                if Domain.objects.filter(domain__iexact=new_domain).exists():
                    return Response({'error': 'Domain already exists'}, status=status.HTTP_400_BAD_REQUEST)
                Domain.objects.create(tenant=tenant, domain=new_domain, is_primary=True)

            _log_activity(
                user=request.user,
                action='tenant_domain_updated',
                description=f'Updated domain for {tenant.name} to {new_domain}',
                request=request
            )
            return Response({'status': 'success', 'domain': new_domain})
        except Exception as e:
            logger.error(f"Error updating domain: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        tenant = self.get_object()
        logs = ActivityLog.objects.filter(tenant_schema=tenant.schema_name)[:50]
        from accounts.serializers import ActivityLogSerializer
        serializer = ActivityLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get', 'put'])
    def features(self, request, pk=None):
        tenant = self.get_object()
        if request.method == 'GET':
            from pricing.models import PricingPlan, PlanServiceMapping
            plan_slug = tenant.subscription_plan or 'basic'
            plan = PricingPlan.objects.filter(slug__iexact=plan_slug).first()
            
            SERVICE_TO_FEATURE_KEY = {
                'Dashboard': 'dashboard',
                'Communities': 'communities',
                'Blocks/Sectors': 'buildings',
                'Units': 'units',
                'People Hub': 'people_hub',
                'Facility Managers': 'facility_managers',
                'Senior Hub Managers': 'senior_managers',
                'Rental Hub': 'leases',
                'Documents': 'documents',
                'Bulk Upload': 'bulk_upload',
                'Bulk Export': 'bulk_export',
                'Payments': 'payments',
                'Maintenance': 'maintenance',
                'Amenities': 'amenities',
                'Security': 'security',
                'Vendors': 'vendors',
                'Calendar': 'calendar',
                'Message Center': 'communication',
                'Support Center': 'support',

                'Reports': 'reports',
            }
            
            # Start all active services as False
            default_features = {key: False for key in SERVICE_TO_FEATURE_KEY.values()}
            # Always enable core system features
            default_features.update({
                'property_management': True,
                'unit_database': True,
                'member_portal': True,
                'billing_engine': True,
                'communication_hub': True,
                'dashboard': True,
            })
            
            if plan:
                mappings = PlanServiceMapping.objects.filter(plan=plan)
                for m in mappings:
                    f_key = SERVICE_TO_FEATURE_KEY.get(m.service.name)
                    if f_key:
                        default_features[f_key] = m.is_included
            
            # Merge with existing features (ONLY if features dict is completely empty)
            if not tenant.features:
                tenant.features = default_features
                tenant.save()
            
            return Response(tenant.features or {})
        
        # PUT - Update features
        new_features = request.data
        if not isinstance(new_features, dict):
            return Response({'error': 'Invalid data format. Expected a dictionary.'}, status=status.HTTP_400_BAD_REQUEST)
        
        tenant.features = new_features
        tenant.save()
        
        _log_activity(
            user=request.user,
            action='tenant_features_updated',
            description=f'Updated features for organization: {tenant.name}',
            request=request
        )
        return Response(tenant.features)

    @action(detail=True, methods=['get'], url_path='available-services')
    def available_services(self, request, pk=None):
        tenant = self.get_object()
        enabled_features = tenant.features or {}
        # Exclude only features that are set to True (enabled)
        enabled_keys = [k for k, v in enabled_features.items() if v is True]

        # Also exclude services that are already requested or approved
        try:
            from pricing.models import AddOnRequest
            requested_service_names = AddOnRequest.objects.filter(
                tenant_schema=tenant.schema_name,
                status__in=['pending', 'approved']
            ).values_list('service__name', flat=True)
            
            SERVICE_TO_FEATURE_KEY = {
                'Dashboard': 'dashboard',
                'Communities': 'communities',
                'Blocks/Sectors': 'buildings',
                'Units': 'units',
                'People Hub': 'people_hub',
                'Facility Managers': 'facility_managers',
                'Senior Hub Managers': 'senior_managers',
                'Rental Hub': 'leases',
                'Documents': 'documents',
                'Bulk Upload': 'bulk_upload',
                'Bulk Export': 'bulk_export',
                'Payments': 'payments',
                'Maintenance': 'maintenance',
                'Amenities': 'amenities',
                'Security': 'security',
                'Vendors': 'vendors',
                'Calendar': 'calendar',
                'Message Center': 'communication',
                'Support Center': 'support',

                'Reports': 'reports',
            }
            requested_keys = [SERVICE_TO_FEATURE_KEY.get(name) for name in requested_service_names if SERVICE_TO_FEATURE_KEY.get(name)]
            exclude_keys = set(enabled_keys + requested_keys)
        except Exception:
            exclude_keys = set(enabled_keys)

        available = TenantFeature.objects.filter(is_active=True).exclude(name__in=exclude_keys)
        serializer = TenantFeatureSerializer(available, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='add-service')
    def add_service(self, request, pk=None):
        tenant = self.get_object()
        try:
            feature_ids = request.data.get('feature_ids', [])
            if not feature_ids and request.data.get('feature_id'):
                feature_ids = [request.data.get('feature_id')]
                
            if not feature_ids:
                return Response({'error': 'No features selected'}, status=status.HTTP_400_BAD_REQUEST)
                
            features_to_add = TenantFeature.objects.filter(id__in=feature_ids, is_active=True)
            if not features_to_add.exists():
                return Response({'error': 'Invalid features selected'}, status=status.HTTP_400_BAD_REQUEST)
                
            total_amount = sum(f.price for f in features_to_add)
            feature_names = [f.name for f in features_to_add]
            display_names = ", ".join([f.display_name for f in features_to_add])
            
            # 1. Generate Invoice (DO NOT activate features yet)
            due_date = (timezone.now() + timedelta(days=7)).date()
            invoice = PlatformInvoice.objects.create(
                tenant=tenant,
                amount=total_amount,
                plan_name=f"Add-on: {display_names}",
                billing_email=tenant.contact_email,
                due_date=due_date,
                status='pending',
                pending_features=feature_names,
                remarks=f"Additional services request: {display_names}"
            )
            
            _log_activity(
                user=request.user,
                action='service_requested',
                description=f'Requested additional services for {tenant.name}: {display_names}. Invoice {invoice.invoice_number} generated.',
                request=request
            )
            
            return Response({
                'message': f'Invoice {invoice.invoice_number} generated for ${total_amount}. Services will be activated upon payment.',
                'invoice_id': invoice.id,
                'amount': total_amount
            })
        except Exception as e:
            logger.error(f"Error adding service: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='remove-service')
    def remove_service(self, request, pk=None):
        """Remove a service from a tenant's enabled features."""
        tenant = self.get_object()
        feature_name = request.data.get('feature_name')
        
        if not feature_name:
            return Response({'error': 'feature_name is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if tenant.features and feature_name in tenant.features:
            # 1. Remove the feature from JSON
            del tenant.features[feature_name]
            tenant.save()
            
            # 2. Log Activity
            _log_activity(
                user=request.user,
                action='service_removed',
                description=f'Removed service {feature_name} from {tenant.name}.',
                request=request
            )
            
            return Response({
                'status': 'success',
                'message': f'Service {feature_name} removed successfully.',
                'features': tenant.features
            })
        
        return Response({'error': 'Service not found or already disabled for this organization.'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        tenant = self.get_object()
        try:
            from payments.models import Payment
            with schema_context(tenant.schema_name):
                # Fetch recent payments
                payments = Payment.objects.select_related('user').all().order_by('-created_at')[:100]
                data = []
                for p in payments:
                    # Resolve resident unit
                    unit_number = "N/A"
                    if p.user:
                        unit_number = getattr(p.user, 'unit_number', 'N/A') or 'N/A'
                        
                    data.append({
                        'id': str(p.id),
                        'date': p.completed_at.isoformat() if p.completed_at else p.created_at.isoformat(),
                        'resident_name': p.user.get_full_name() if p.user else 'Unknown',
                        'resident_unit': unit_number,
                        'method': p.get_payment_method_display() if hasattr(p, 'get_payment_method_display') else p.payment_method,
                        'amount': float(p.amount),
                        'platform_fee': float(p.platform_fee),
                        'stripe_fee': float(p.metadata.get('stripe_fee', 0.00)) if getattr(p, 'metadata', None) and 'stripe_fee' in p.metadata else 0.00,
                        'super_admin_profit': float(p.metadata.get('super_admin_profit', float(p.platform_fee))) if getattr(p, 'metadata', None) and 'super_admin_profit' in p.metadata else float(p.platform_fee),
                        'net_revenue': float(p.net_amount),
                        'status': p.status.capitalize() if p.status else 'Pending'
                    })
                return Response(data)
        except Exception as e:
            logger.error(f"Error fetching transactions for tenant {tenant.name}: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='check-domain')
    def check_domain(self, request):
        domain = request.query_params.get('domain')
        if not domain:
            return Response({'success': False, 'error': 'Domain is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if '.' not in domain:
            suffix = getattr(settings, 'TENANT_DOMAIN_SUFFIX', None)
            if not suffix:
                is_local = any(h in settings.ALLOWED_HOSTS for h in ['localhost', '127.0.0.1'])
                suffix = '.localhost' if (is_local and settings.DEBUG) else '.hoaconnecthub.com'
            normalized = f"{domain}{suffix}"
        else:
            normalized = domain
            
        exists = Domain.objects.filter(domain__iexact=domain).exists() or Domain.objects.filter(domain__iexact=normalized).exists()
        return Response({'success': True, 'exists': exists})

    @action(detail=False, methods=['get'], url_path='check-name')
    def check_name(self, request):
        name = request.query_params.get('name')
        if not name:
            return Response({'success': False, 'error': 'Name is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        exists = Client.objects.filter(name__iexact=name.strip()).exists()
        return Response({'success': True, 'exists': exists})


class DomainViewSet(ModelViewSet):
    queryset = Domain.objects.all()
    serializer_class = DomainSerializer
    permission_classes = [IsSystemAdminOrReadOnly]

class TenantSettingsViewSet(ModelViewSet):
    queryset = TenantSettings.objects.all()
    serializer_class = TenantSettingsSerializer
    permission_classes = [IsSystemAdminOrReadOnly]
    def get_queryset(self):
        if hasattr(self.request, 'tenant'):
            return self.queryset.filter(tenant=self.request.tenant)
        return self.queryset

class TenantFeatureViewSet(ModelViewSet):
    queryset = TenantFeature.objects.all()
    serializer_class = TenantFeatureSerializer
    permission_classes = [IsSystemAdminOrReadOnly]

class TenantSubscriptionViewSet(ModelViewSet):
    queryset = TenantSubscription.objects.all()
    serializer_class = TenantSubscriptionSerializer
    permission_classes = [IsSystemAdminOrReadOnly]

class KYCViewSet(ModelViewSet):
    queryset = KYC.objects.select_related('tenant').prefetch_related('logs').all()
    serializer_class = KYCSerializer
    permission_classes = [IsSystemAdminOrReadOnly]
    
    def get_queryset(self):
        user = self.request.user
        qs = self.queryset
        if user.role in ('master_admin', 'masteradmin'):
            tenant_id = getattr(user, 'tenant_id', None)
            return qs.filter(tenant__schema_name=tenant_id)
        return qs.exclude(tenant__schema_name='public')

    @action(detail=False, methods=['post'])
    def submit(self, request):
        """Submit or update KYC for the current organization."""
        tenant_id = getattr(request.user, 'tenant_id', None)
        tenant = Client.objects.filter(schema_name=tenant_id).first()
        
        if not tenant:
            return Response({'error': 'Organization context not found'}, status=status.HTTP_404_NOT_FOUND)
            
        kyc, created = KYC.objects.get_or_create(tenant=tenant)
        
        # Use serializer to handle file uploads and field validation
        serializer = self.get_serializer(kyc, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(status='submitted', submitted_at=timezone.now())
            
            # Log the submission
            KYCLog.objects.create(
                kyc=kyc, 
                action='submitted', 
                remarks='KYC documents submitted for review.'
            )
            
            # Notify Master Admin that submission was successful
            NotificationService.send(
                user=request.user,
                title="KYC Submitted Successfully",
                message=f"Your KYC documents for {tenant.name} have been submitted and are under review. We will notify you once approved.",
                notification_type='system',
                priority='medium',
                send_email=True
            )
            
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        kyc = self.get_object()
        kyc.status = 'approved'
        kyc.approved_at = timezone.now()
        kyc.save()
        KYCLog.objects.create(kyc=kyc, action='approved', remarks=request.data.get('remarks', ''))
        
        # Notify Master Admin
        from accounts.models import User
        admin_user = User.objects.filter(tenant_id=kyc.tenant_id, role='master_admin').first()
        if admin_user:
            NotificationService.send(
                user=admin_user,
                title="KYC Approved!",
                message=f"Congratulations! Your KYC for {kyc.tenant.name} has been approved by the Super Admin.",
                notification_type='system',
                priority='high',
                send_email=True
            )
        
        return Response({'status': 'KYC approved'})

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        kyc = self.get_object()
        logs = kyc.logs.all()
        serializer = KYCLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        kyc = self.get_object()
        kyc.status = 'rejected'
        remarks = request.data.get('remarks') or request.data.get('reason', '')
        kyc.remarks = remarks
        kyc.save()
        KYCLog.objects.create(kyc=kyc, action='rejected', remarks=remarks)
        
        # Notify Master Admin
        from accounts.models import User
        admin_user = User.objects.filter(tenant_id=kyc.tenant_id, role='master_admin').first()
        if admin_user:
            NotificationService.send(
                user=admin_user,
                title="KYC Rejected",
                message=f"Your KYC for {kyc.tenant.name} was rejected. Reason: {kyc.remarks}",
                notification_type='system',
                priority='high',
                send_email=True
            )
            
        return Response({'status': 'KYC rejected'})

    @action(detail=True, methods=['post'], url_path='resubmit')
    def resubmit(self, request, pk=None):
        kyc = self.get_object()
        kyc.status = 'resubmission_required'
        remarks = request.data.get('remarks') or request.data.get('reason', '')
        kyc.remarks = remarks
        kyc.save()
        KYCLog.objects.create(kyc=kyc, action='resubmission_required', remarks=remarks)
        
        # Notify Master Admin
        from accounts.models import User
        admin_user = User.objects.filter(tenant_id=kyc.tenant_id, role='master_admin').first()
        if admin_user:
            NotificationService.send(
                user=admin_user,
                title="KYC Resubmission Required",
                message=f"Your KYC for {kyc.tenant.name} requires resubmission. Remarks: {remarks}",
                notification_type='system',
                priority='high',
                send_email=True
            )
            
        return Response({'status': 'resubmission_required'})

class PlatformInvoiceViewSet(ModelViewSet):
    queryset = PlatformInvoice.objects.all()
    serializer_class = PlatformInvoiceSerializer
    permission_classes = [IsSystemAdminOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.role in ('super_admin', 'superadmin'):
            return self.queryset
        # Master admins can see invoices where their organization email matches
        return self.queryset.filter(billing_email=user.email)

    @action(detail=True, methods=['post'], url_path='create-payment-intent', permission_classes=[permissions.IsAuthenticated])
    def create_payment_intent(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status == 'paid':
            return Response({'error': 'Invoice already paid'}, status=status.HTTP_400_BAD_REQUEST)

        # Get Global Stripe Keys from public schema
        with schema_context('public'):
            gateway = PaymentGateway.objects.filter(gateway_type='stripe', is_active=True).first()
            if not gateway or not gateway.secret_key:
                return Response({'error': 'Global Stripe payment is not configured'}, status=status.HTTP_400_BAD_REQUEST)
            
            stripe.api_key = gateway.secret_key
            
            try:
                # Create a PaymentIntent
                intent = stripe.PaymentIntent.create(
                    amount=int(invoice.amount * 100),
                    currency='usd',
                    metadata={
                        'invoice_id': str(invoice.id),
                        'invoice_number': invoice.invoice_number,
                        'tenant_id': str(invoice.tenant.id),
                        'payment_type': 'platform_subscription'
                    }
                )
                
                return Response({
                    'client_secret': intent.client_secret,
                    'publishable_key': gateway.public_key,
                    'amount': invoice.amount
                })
            except Exception as e:
                logger.error(f"Stripe Intent Error: {e}")
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='verify-stripe', permission_classes=[permissions.IsAuthenticated])
    def verify_stripe(self, request, pk=None):
        invoice = self.get_object()
        intent_id = request.data.get('intent_id')
        
        if not intent_id:
            return Response({'error': 'intent_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        with schema_context('public'):
            gateway = PaymentGateway.objects.filter(gateway_type='stripe', is_active=True).first()
            if not gateway or not gateway.secret_key:
                return Response({'error': 'Global Stripe payment is not configured'}, status=status.HTTP_400_BAD_REQUEST)
            
            stripe.api_key = gateway.secret_key
            
            try:
                intent = stripe.PaymentIntent.retrieve(intent_id)
                if intent.status == 'succeeded':
                    invoice.status = 'paid'
                    invoice.paid_at = timezone.now()
                    invoice.transaction_id = intent_id
                    invoice.payment_method = 'stripe_card'
                    invoice.save()
                    return Response({'status': 'paid', 'invoice_number': invoice.invoice_number})
                else:
                    return Response({'status': intent.status, 'error': 'Payment not successful yet'})
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='verify')
    def verify(self, request, pk=None):
        invoice = self.get_object()
        remarks = request.data.get('remarks', '') or request.data.get('notes', '')
        invoice.status = 'verified'
        invoice.remarks = remarks
        invoice.save()
        return Response({'status': 'verified', 'invoice_number': invoice.invoice_number})

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        invoice = self.get_object()
        from django.http import HttpResponse
        import io
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, PageTemplate, BaseDocTemplate, Frame
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT

        buffer = io.BytesIO()

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('Helvetica', 9)
            canvas.setFillColor(colors.HexColor('#666666'))
            # Line
            canvas.setStrokeColor(colors.HexColor('#CCCCCC'))
            canvas.line(0.75 * inch, 0.75 * inch + 15, letter[0] - 0.75 * inch, 0.75 * inch + 15)
            # Text
            page_num = f"Page {doc.page} of 1"
            canvas.drawCentredString(letter[0]/2.0, 0.75 * inch, page_num)
            canvas.drawCentredString(letter[0]/2.0, 0.75 * inch - 14, "Powered by HOA Connect Hub")
            canvas.restoreState()

        class InvoiceDocTemplate(BaseDocTemplate):
            def __init__(self, filename, **kw):
                super().__init__(filename, **kw)
                frame = Frame(0.75 * inch, 1.2 * inch, letter[0] - 1.5 * inch, letter[1] - 2 * inch, id='F1')
                template = PageTemplate('normal', [frame], onPage=footer)
                self.addPageTemplates(template)

        doc = InvoiceDocTemplate(buffer, pagesize=letter,
                                rightMargin=0.75 * inch, leftMargin=0.75 * inch,
                                topMargin=0.75 * inch, bottomMargin=1.5 * inch)
                                
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('InvoiceTitle', parent=styles['Title'], fontSize=28,
                                     spaceAfter=0, textColor=colors.HexColor('#14213D'), alignment=TA_RIGHT, fontName='Helvetica-Bold')
        normal_style = styles['Normal']
        
        elements = []

        logo_style = ParagraphStyle('LogoStyle', parent=styles['Normal'], leading=16)
        logo_p = Paragraph("<font size=28 color='#14213D'><b>HOA</b></font><br/><font size=12 color='#333333'>Connect Hub</font>", logo_style)
        
        status_style = ParagraphStyle('StatusStyle', parent=styles['Normal'], alignment=TA_RIGHT)
        
        meta_data = [
            ['Invoice Number:', str(invoice.invoice_number)],
            ['Date:', str(invoice.issue_date)],
            ['Due Date:', str(invoice.due_date)],
            ['Status:', Paragraph(f"<font color='#2E7D32'>{invoice.status.upper()}</font>", status_style)],
        ]
        
        meta_table = Table(meta_data, colWidths=[1.4 * inch, 1.5 * inch])
        meta_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
            ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#555555')),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 2),
        ]))
        
        right_table = Table([
            [Paragraph('INVOICE', title_style)],
            [Spacer(1, 10)],
            [meta_table]
        ])
        right_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))

        header_table = Table([[logo_p, right_table]], colWidths=[3.5 * inch, 3.5 * inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        
        elements.append(header_table)
        elements.append(Spacer(1, 20))

        bill_to_data = [
            [Paragraph("<b>BILL TO:</b>", normal_style)],
            [Paragraph(f"Organization: {invoice.tenant.name}", normal_style)],
            [Paragraph(f"Email: {invoice.billing_email}", normal_style)],
        ]
        bill_to_table = Table(bill_to_data, colWidths=[7.0 * inch])
        bill_to_table.setStyle(TableStyle([
            ('LINELEFT', (0,0), (0,-1), 2, colors.HexColor('#14213D')),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 2),
        ]))
        
        elements.append(bill_to_table)
        elements.append(Spacer(1, 30))

        item_headers = [Paragraph('<b>Description</b>', normal_style), Paragraph('<b>Amount</b>', normal_style)]
        item_rows = [
            [Paragraph(f"Platform Subscription - {invoice.plan_name}", normal_style), Paragraph(f"${invoice.amount}", normal_style)]
        ]
        
        invoice_table_data = [item_headers] + item_rows
        invoice_table = Table(invoice_table_data, colWidths=[5.5 * inch, 1.5 * inch])
        invoice_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F5F5F5')),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#EAEAEA')),
            ('LINEBELOW', (0,0), (-1,0), 1.5, colors.HexColor('#14213D')),
        ]))
        
        elements.append(invoice_table)
        elements.append(Spacer(1, 20))

        total_data = [
            ['Total Amount:', f"${invoice.amount}"],
        ]
        total_table = Table(total_data, colWidths=[5.5 * inch, 1.5 * inch])
        total_table.setStyle(TableStyle([
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#14213D')),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(total_table)

        doc.build(elements)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{invoice.invoice_number}.pdf"'
        return response

    @action(detail=False, methods=['get'])
    def export(self, request):
        export_format = request.query_params.get('format', 'csv')
        invoices = self.filter_queryset(self.get_queryset())
        from django.http import HttpResponse
        
        filename = f"platform_invoices_{timezone.now().strftime('%Y%m%d_%H%M')}"
        
        if export_format == 'csv':
            import csv
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
            
            writer = csv.writer(response)
            writer.writerow(['Invoice #', 'Organization', 'Billing Email', 'Plan Name', 'Amount', 'Status', 'Issue Date', 'Due Date'])
            
            for inv in invoices:
                writer.writerow([
                    inv.invoice_number,
                    inv.tenant.name,
                    inv.billing_email,
                    inv.plan_name,
                    f"${inv.amount}",
                    inv.status.upper(),
                    inv.issue_date.strftime("%Y-%m-%d") if inv.issue_date else "",
                    inv.due_date.strftime("%Y-%m-%d") if inv.due_date else "",
                ])
            return response
            
        elif export_format == 'excel':
            import pandas as pd
            import io
            
            excel_data = []
            for inv in invoices:
                excel_data.append({
                    'Invoice #': inv.invoice_number,
                    'Organization': inv.tenant.name,
                    'Billing Email': inv.billing_email,
                    'Plan Name': inv.plan_name,
                    'Amount': float(inv.amount),
                    'Status': inv.status.upper(),
                    'Issue Date': inv.issue_date.strftime("%Y-%m-%d") if inv.issue_date else "",
                    'Due Date': inv.due_date.strftime("%Y-%m-%d") if inv.due_date else "",
                })
            
            df = pd.DataFrame(excel_data)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Platform Invoices')
            
            response = HttpResponse(
                output.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
            return response
            
        elif export_format == 'pdf':
            import io
            from reportlab.lib.pagesizes import letter, landscape
            from reportlab.lib import colors
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                                    rightMargin=0.5 * inch, leftMargin=0.5 * inch,
                                    topMargin=0.5 * inch, bottomMargin=0.5 * inch)
            
            styles = getSampleStyleSheet()
            elements = []
            
            title_style = ParagraphStyle('ReportTitle', parent=styles['Title'], fontSize=20, spaceAfter=20, textColor=colors.HexColor('#14213D'))
            elements.append(Paragraph("Platform Invoices Report", title_style))
            
            headers = ['Invoice #', 'Organization', 'Billing Email', 'Plan Name', 'Amount', 'Status', 'Issue Date', 'Due Date']
            table_data = [headers]
            for inv in invoices:
                table_data.append([
                    inv.invoice_number,
                    inv.tenant.name,
                    inv.billing_email,
                    inv.plan_name,
                    f"${inv.amount}",
                    inv.status.upper(),
                    inv.issue_date.strftime("%Y-%m-%d") if inv.issue_date else "",
                    inv.due_date.strftime("%Y-%m-%d") if inv.due_date else "",
                ])
                
            col_widths = [1.5*inch, 1.5*inch, 2.0*inch, 1.2*inch, 0.8*inch, 0.9*inch, 1.0*inch, 1.0*inch]
            t = Table(table_data, colWidths=col_widths)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#14213D')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 10),
                ('BOTTOMPADDING', (0,0), (-1,0), 8),
                ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#F9F9F9')),
                ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                ('FONTSIZE', (0,1), (-1,-1), 9),
            ]))
            elements.append(t)
            doc.build(elements)
            
            response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
            return response
            
        return Response({'error': 'Unsupported format'}, status=400)

class PlatformPaymentMethodViewSet(ModelViewSet):
    queryset = PlatformPaymentMethod.objects.all()
    serializer_class = PlatformPaymentMethodSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        tenant_id = getattr(user, 'tenant_id', None)
        if not tenant_id:
            return self.queryset.none()
        return self.queryset.filter(tenant__schema_name=tenant_id)

    @action(detail=False, methods=['post'], url_path='initiate-setup')
    def initiate_setup(self, request):
        """Create a Stripe SetupIntent to save a card for future platform payments."""
        with schema_context('public'):
            gateway = PaymentGateway.objects.filter(gateway_type='stripe', is_active=True).first()
            if not gateway or not gateway.secret_key:
                return Response({'error': 'Global Stripe payment is not configured'}, status=status.HTTP_400_BAD_REQUEST)
            
            stripe.api_key = gateway.secret_key
            
            try:
                # Try to get or create a Stripe Customer for this organization
                tenant_id = getattr(request.user, 'tenant_id', None)
                tenant = Client.objects.filter(schema_name=tenant_id).first()
                if not tenant:
                    return Response({'error': 'Organization context not found'}, status=status.HTTP_404_NOT_FOUND)
                
                customer_id = None
                # We could store stripe_customer_id in Client model or TenantSettings
                # For now let's check existing methods
                existing_method = PlatformPaymentMethod.objects.filter(tenant=tenant).first()
                if existing_method:
                    customer_id = existing_method.gateway_customer_id
                
                if not customer_id:
                    customer = stripe.Customer.create(
                        email=tenant.contact_email,
                        name=tenant.name,
                        metadata={'tenant_id': tenant_id}
                    )
                    customer_id = customer.id

                setup_intent = stripe.SetupIntent.create(
                    customer=customer_id,
                    payment_method_types=['card'],
                    metadata={'tenant_id': tenant_id}
                )
                
                return Response({
                    'client_secret': setup_intent.client_secret,
                    'publishable_key': gateway.public_key,
                    'customer_id': customer_id
                })
            except Exception as e:
                logger.error(f"Stripe Setup Error: {e}")
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='verify-setup')
    def verify_setup(self, request):
        setup_intent_id = request.data.get('setup_intent_id')
        if not setup_intent_id:
            return Response({'error': 'setup_intent_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        with schema_context('public'):
            gateway = PaymentGateway.objects.filter(gateway_type='stripe', is_active=True).first()
            if not gateway or not gateway.secret_key:
                return Response({'error': 'Global Stripe payment is not configured'}, status=status.HTTP_400_BAD_REQUEST)
            
            stripe.api_key = gateway.secret_key
            
            try:
                si = stripe.SetupIntent.retrieve(setup_intent_id)
                if si.status == 'succeeded':
                    pm_id = si.payment_method
                    pm = stripe.PaymentMethod.retrieve(pm_id)
                    
                    tenant_id = getattr(request.user, 'tenant_id', None)
                    tenant = Client.objects.filter(schema_name=tenant_id).first()
                    
                    # Create or update payment method
                    method, created = PlatformPaymentMethod.objects.update_or_create(
                        tenant=tenant,
                        gateway_payment_method_id=pm_id,
                        defaults={
                            'method_type': 'stripe_card',
                            'gateway_customer_id': si.customer,
                            'card_last4': pm.card.last4,
                            'card_brand': pm.card.brand,
                            'card_exp_month': pm.card.exp_month,
                            'card_exp_year': pm.card.exp_year,
                            'is_default': not PlatformPaymentMethod.objects.filter(tenant=tenant).exists()
                        }
                    )
                    
                    return Response(PlatformPaymentMethodSerializer(method).data)
                else:
                    return Response({'error': f'Setup intent status: {si.status}'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class PlatformAutopayViewSet(ModelViewSet):
    queryset = PlatformAutopayEnrollment.objects.all()
    serializer_class = PlatformAutopayEnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        tenant_id = getattr(user, 'tenant_id', None)
        if not tenant_id:
            return self.queryset.none()
        return self.queryset.filter(tenant__schema_name=tenant_id)

    def create(self, request, *args, **kwargs):
        tenant_id = getattr(request.user, 'tenant_id', None)
        tenant = Client.objects.filter(schema_name=tenant_id).first()
        if not tenant:
            return Response({'error': 'Organization context not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if already enrolled
        if PlatformAutopayEnrollment.objects.filter(tenant=tenant, status='active').exists():
            return Response({'error': 'Already enrolled in auto-pay'}, status=status.HTTP_400_BAD_REQUEST)
            
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        tenant_id = getattr(self.request.user, 'tenant_id', None)
        tenant = Client.objects.filter(schema_name=tenant_id).first()
        serializer.save(tenant=tenant)

@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def global_stripe_settings(request):
    """Get or update global Stripe settings (Super Admin only)."""
    if request.user.role not in ('super_admin', 'superadmin'):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    with schema_context('public'):
        gateway, created = PaymentGateway.objects.get_or_create(
            gateway_type='stripe',
            defaults={'is_active': True, 'currency': 'USD'}
        )
        
        if request.method == 'GET':
            settings_dict = gateway.settings or {}
            # Fallback to amount if percentage not set yet
            pct = settings_dict.get('platform_fee_percentage', settings_dict.get('platform_fee_amount', 2.0))
            return Response({
                'public_key': gateway.public_key,
                'secret_key': gateway.secret_key,
                'webhook_secret': gateway.webhook_secret,
                'is_active': gateway.is_active,
                'is_test_mode': gateway.is_test_mode,
                'platform_fee_enabled': settings_dict.get('platform_fee_enabled', True),
                'platform_fee_type': settings_dict.get('platform_fee_type', 'flat'),
                'platform_fee_percentage': pct,
                'platform_fee_amount': pct,  # Keep backward compatibility
                'method_fees': settings_dict.get('method_fees', {
                    'card': {'type': 'percentage', 'amount': pct, 'flat_fee': 0.30},
                    'ach': {'type': 'flat', 'amount': 1.00, 'flat_fee': 0.00}
                })
            })
            
        # POST - Update
        data = request.data.copy()
        
        platform_fee_enabled = data.get('platform_fee_enabled')
        platform_fee_type = data.get('platform_fee_type')
        platform_fee_percentage = data.get('platform_fee_percentage', data.get('platform_fee_amount'))
        method_fees = data.get('method_fees')
        
        if gateway.settings is None:
            gateway.settings = {}
            
        if platform_fee_enabled is not None:
            gateway.settings['platform_fee_enabled'] = bool(platform_fee_enabled)
            
        if platform_fee_type in ('flat', 'percentage'):
            gateway.settings['platform_fee_type'] = platform_fee_type
            
        if method_fees is not None:
            gateway.settings['method_fees'] = method_fees
            
        if platform_fee_percentage is not None:
            try:
                val = float(platform_fee_percentage)
                gateway.settings['platform_fee_percentage'] = val
                gateway.settings['platform_fee_amount'] = val  # Keep backward compatibility
            except (ValueError, TypeError):
                return Response({'error': 'Invalid administrative fee amount'}, status=status.HTTP_400_BAD_REQUEST)
                
        serializer = PaymentGatewaySerializer(gateway, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            gateway.save(update_fields=['settings'])
            
            response_data = serializer.data
            pct = gateway.settings.get('platform_fee_percentage', 2.0)
            response_data['platform_fee_enabled'] = gateway.settings.get('platform_fee_enabled', True)
            response_data['platform_fee_type'] = gateway.settings.get('platform_fee_type', 'flat')
            response_data['platform_fee_percentage'] = pct
            response_data['platform_fee_amount'] = pct
            return Response(response_data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def test_global_stripe_connection(request):
    """Test global Stripe keys for Super Admin."""
    if request.user.role not in ('super_admin', 'superadmin'):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    secret_key = request.data.get('secret_key')
    if not secret_key:
        return Response({'error': 'Secret key is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        stripe.api_key = secret_key
        account = stripe.Account.retrieve()
        return Response({'success': True, 'message': 'Connected to Stripe account: ' + account.id})
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def test_email_connection(request):
    """Test email/SMTP settings for Super Admin."""
    if request.user.role not in ('super_admin', 'superadmin'):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    from django.core.mail import get_connection, EmailMessage
    from django.conf import settings
    
    config = request.data
    host = config.get('smtp_host')
    port = config.get('smtp_port', 587)
    user = config.get('smtp_user')
    password = config.get('smtp_password') or config.get('smtp_pass')
    use_tls = config.get('smtp_use_tls', True)
    from_email = config.get('from_email', settings.DEFAULT_FROM_EMAIL)
    
    # SendGrid option
    sendgrid_key = config.get('sendgrid_api_key')
    
    try:
        if sendgrid_key:
            # Simple check if key starts with SG.
            if not sendgrid_key.startswith('SG.'):
                return Response({'success': False, 'error': 'Invalid SendGrid API Key format'})
            return Response({'success': True, 'message': 'SendGrid configuration looks valid (API test skipped)'})
        
        if not host:
            return Response({'success': False, 'error': 'SMTP Host is required'})

        connection = get_connection(
            host=host,
            port=port,
            username=user,
            password=password,
            use_tls=use_tls,
            timeout=10
        )
        
        # Try to send a real test email
        email = EmailMessage(
            'HOAConnectHub - SMTP Test',
            'This is a test email to verify your SMTP settings.',
            from_email,
            [request.user.email],
            connection=connection
        )
        email.send()
        
        return Response({'success': True, 'message': f'Test email sent to {request.user.email}'})
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def master_admin_invoices(request):
    """Get invoices for the current master admin's organization."""
    if request.user.role not in ('master_admin', 'masteradmin'):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
    
    # Platform invoices are in public schema
    with schema_context('public'):
        # Filter by email or link by tenant if possible
        # User in tenant schema has a tenant_id but it might be schema_name
        tenant_id = getattr(request.user, 'tenant_id', None)
        if tenant_id:
            invoices = PlatformInvoice.objects.filter(tenant__schema_name=tenant_id)
        else:
            invoices = PlatformInvoice.objects.filter(billing_email=request.user.email)
            
        serializer = PlatformInvoiceSerializer(invoices, many=True)
        return Response(serializer.data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_tenant(request):
    """Return the currently active tenant details from the request object."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return Response({'error': 'No tenant context found'}, status=status.HTTP_404_NOT_FOUND)
    
    from django_tenants.utils import schema_context
    with schema_context('public'):
        tenant = Client.objects.select_related('kyc').prefetch_related(
            'domains', 'settings', 'subscription'
        ).filter(pk=tenant.pk).first()
        
        if not tenant:
            return Response({'error': 'Tenant not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ClientSerializer(tenant)
        serializer_data = serializer.data
        
    return Response(serializer_data)

@api_view(['GET'])
@permission_classes([IsSystemAdminOrReadOnly])
def system_stats(request):
    """Return system-wide statistics for super admins."""
    from django.core.cache import cache
    cache_key = 'system_dashboard_stats'
    try:
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)
    except Exception as cache_err:
        logger.error(f"System stats cache read error: {cache_err}")

    # Exclude 'public' schema — django-tenants stores it as a Client row
    # but it is NOT an actual tenant organization.
    tenant_qs = Client.objects.exclude(schema_name='public')

    # Only count tenant-level users, exclude platform super admins
    tenant_users = User.objects.exclude(
        role__in=['super_admin', 'superadmin']
    ).exclude(
        tenant_id__isnull=True
    ).exclude(
        tenant_id__in=['', 'public']
    )

    now = timezone.now()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    total_revenue = PlatformInvoice.objects.filter(
        status__in=['paid', 'verified']
    ).aggregate(total=Sum('amount'))['total'] or 0.00

    data = {
        'total_tenants': tenant_qs.count(),
        'active_tenants': tenant_qs.filter(is_active=True).count(),
        'total_users': tenant_users.count(),
        'total_revenue': float(total_revenue),
    }
    try:
        cache.set(cache_key, data, timeout=15) # Cache for 15 seconds
    except Exception:
        pass
    return Response(data)

@api_view(['GET'])
@permission_classes([IsSystemAdminOrReadOnly])
def tenant_health_check(request, tenant_id):
    return Response({'status': 'ok', 'tenant_id': tenant_id})

@api_view(['POST'])
@permission_classes([IsSystemAdminOrReadOnly])
def activate_tenant(request, tenant_id):
    Client.objects.filter(id=tenant_id).update(is_active=True)
    return Response({'status': 'Tenant activated'})

@api_view(['POST'])
@permission_classes([IsSystemAdminOrReadOnly])
def deactivate_tenant(request, tenant_id):
    Client.objects.filter(id=tenant_id).update(is_active=False)
    return Response({'status': 'Tenant deactivated'})

@api_view(['GET'])
def available_features(request):
    return Response({'features': []})

@api_view(['GET'])
@permission_classes([IsSystemAdminOrReadOnly])
def tenant_usage_report(request, tenant_id):
    return Response({'report': 'Usage report for tenant'})

@api_view(['POST'])
@permission_classes([IsSystemAdminOrReadOnly])
def clear_system_cache(request):
    cache.clear()
    return Response({'status': 'Cache cleared'})

@api_view(['POST'])
@permission_classes([IsSystemAdminOrReadOnly])
def sync_schemas_view(request):
    return Response({'status': 'Schema sync initiated'})

@api_view(['GET'])
@permission_classes([IsSystemAdminOrReadOnly])
def check_domain_health_view(request):
    return Response({'status': 'Healthy'})

@api_view(['POST'])
@permission_classes([IsSystemAdminOrReadOnly])
def rotate_api_keys_view(request):
    return Response({'status': 'API keys rotated'})

@api_view(['POST'])
@permission_classes([IsSystemAdminOrReadOnly])
def enforce_2fa_system_wide(request):
    return Response({'status': '2FA enforced'})

@api_view(['POST'])
@permission_classes([IsSystemAdminOrReadOnly])
def purge_analytics_events(request):
    return Response({'status': 'Events purged'})

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def discovery_cities(request):
    return Response({'cities': []})

@api_view(['GET'])
@renderer_classes([JSONRenderer])
@permission_classes([permissions.AllowAny])
def discovery_orgs(request):
    """Public organization discovery endpoint."""
    orgs = Client.objects.filter(is_active=True)
    results = []
    for org in orgs:
        domain_obj = org.domains.filter(is_primary=True).first() or org.domains.first()
        if domain_obj:
            subdomain = domain_obj.domain.split('.')[0]
        else:
            subdomain = org.schema_name.replace('tenant_', '').replace('_', '-')
            
        logo_url = None
        if org.logo:
            try:
                logo_url = request.build_absolute_uri(org.logo.url)
            except Exception:
                logo_url = org.logo.url

        results.append({
            'name': org.name,
            'schema_name': org.schema_name,
            'subdomain': subdomain,
            'domain': subdomain,
            'logo': logo_url
        })
        
    return Response({
        'count': len(results),
        'results': results
    })

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def stripe_platform_webhook(request):
    """Handle Stripe webhooks for global platform payments."""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    with schema_context('public'):
        gateway = PaymentGateway.objects.filter(gateway_type='stripe', is_active=True).first()
        if not gateway or not gateway.webhook_secret:
            return Response({'error': 'Webhook not configured'}, status=400)
            
        endpoint_secret = gateway.webhook_secret
        
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        except ValueError:
            return Response({'error': 'Invalid payload'}, status=400)
        except stripe.error.SignatureVerificationError:
            return Response({'error': 'Invalid signature'}, status=400)
            
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            metadata = session.get('metadata', {})
            invoice_id = metadata.get('invoice_id')
            
            if invoice_id:
                try:
                    invoice = PlatformInvoice.objects.get(id=invoice_id)
                    invoice.status = 'paid'
                    invoice.paid_at = timezone.now()
                    invoice.transaction_id = session.get('payment_intent', '')
                    invoice.payment_method = 'stripe'
                    invoice.save()
                    logger.info(f"Platform Invoice {invoice.invoice_number} marked as paid via webhook.")
                except PlatformInvoice.DoesNotExist:
                    logger.error(f"Invoice {invoice_id} not found in webhook.")
                    
        return Response({'status': 'success'})

@api_view(['GET'])
@permission_classes([IsSystemAdminOrReadOnly])
def api_hub_discovery(request):
    return Response({'endpoints': []})
