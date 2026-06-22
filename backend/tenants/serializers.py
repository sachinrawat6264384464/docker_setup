# tenants/serializers.py
import re
import logging
from rest_framework import serializers
from django.utils import timezone
from django.conf import settings
from django_tenants.utils import schema_context

from accounts.models import User
from .models import (
    Client, Domain, TenantSettings, TenantFeature, 
    TenantSubscription, KYC, KYCLog, PlatformInvoice,
    PlatformPaymentMethod, PlatformAutopayEnrollment
)

logger = logging.getLogger(__name__)

class DomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = Domain
        fields = ['id', 'domain', 'is_primary']

    def validate_domain(self, value):
        domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
        if not re.match(domain_pattern, value):
            raise serializers.ValidationError("Invalid domain format")
        
        suffix = getattr(settings, 'TENANT_DOMAIN_SUFFIX', None)
        if not suffix:
            is_localhost = ('localhost' in getattr(settings, 'FRONTEND_URL', '')) or settings.DEBUG
            suffix = '.localhost' if is_localhost else '.hoaconnecthub.com'
        normalized = value if '.' in value else f"{value}{suffix}"
        
        qs = Domain.objects.filter(domain__iexact=value)
        qs_normalized = Domain.objects.filter(domain__iexact=normalized)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
            qs_normalized = qs_normalized.exclude(id=self.instance.id)
            
        if qs.exists() or qs_normalized.exists():
            raise serializers.ValidationError("Domain already exists")
        return value

class TenantFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantFeature
        fields = ['id', 'name', 'display_name', 'description', 'category', 'is_active', 'price']

    def validate_name(self, value):
        value = value.strip().lower()
        if not value:
            raise serializers.ValidationError("Feature Slug is required.")
        if len(value) > 50:
            raise serializers.ValidationError("Slug must be 50 characters or fewer.")
        if not re.match(r'^[a-z0-9_]+$', value):
            raise serializers.ValidationError("Slug must only contain lowercase letters, numbers, and underscores.")
        # Check for SQL injection patterns
        sql_patterns = [r"['\";\-]", r"\b(union|select|insert|update|delete|drop|alter|where|from|truncate)\b"]
        for pattern in sql_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise serializers.ValidationError("Invalid characters or SQL payload detected in Slug.")
        return value

    def validate_display_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Display Name is required.")
        if len(value) > 80:
            raise serializers.ValidationError("Display Name must be 80 characters or fewer.")
        # Reject numbers
        if re.search(r'\d', value):
            raise serializers.ValidationError("Display Name cannot contain numbers.")
        # Reject script tags or HTML tags
        if re.search(r'<[^>]*>|javascript:|on\w+\s*=|data:', value, re.IGNORECASE):
            raise serializers.ValidationError("Display Name contains invalid characters or unsafe HTML/scripts.")
        return value

    def validate_description(self, value):
        if value:
            value = value.strip()
            if len(value) > 255:
                raise serializers.ValidationError("Description must be 255 characters or fewer.")
            if re.search(r'<[^>]*>|javascript:|on\w+\s*=|data:', value, re.IGNORECASE):
                raise serializers.ValidationError("Description contains invalid characters or unsafe HTML/scripts.")
        return value

class TenantSubscriptionSerializer(serializers.ModelSerializer):
    is_expired = serializers.ReadOnlyField()
    days_remaining = serializers.ReadOnlyField()
    
    class Meta:
        model = TenantSubscription
        fields = [
            'id', 'start_date', 'end_date', 'is_trial', 'trial_end_date',
            'monthly_amount', 'billing_cycle', 'max_users', 'max_properties', 
            'max_units', 'status', 'is_expired', 'days_remaining',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

class TenantSettingsSerializer(serializers.ModelSerializer):
    maintenance_categories = serializers.JSONField(required=False, default=list)
    
    class Meta:
        model = TenantSettings
        fields = [
            'id', 'primary_color', 'secondary_color', 'accent_color',
            'logo_url', 'favicon_url', 'login_message', 'login_page_message', 'footer_text',
            'currency', 'date_format', 'fiscal_year_start',
            'email_notifications', 'sms_notifications', 'push_notifications',
            'payment_reminders', 'payment_reminder_days', 'maintenance_updates',
            'lease_expiry_alerts', 'lease_expiry_days', 'security_alerts',
            'weekly_digest', 'monthly_report', 'new_resident_welcome',
            'document_expiry_alerts', 'otp_required', 'otp_expire_minutes',
            'tax_percentage', 'payment_due_days', 'late_fee_enabled', 'late_fee_type',
            'late_fee_percentage', 'late_fee_amount', 'grace_period_days',
            'auto_invoicing', 'invoice_day_of_month', 'razorpay_enabled',
            'razorpay_key_id', 'razorpay_webhook_secret', 'paypal_enabled',
            'paypal_client_id', 'bank_transfer_enabled', 'bank_name',
            'bank_account_name', 'bank_account_number', 'bank_routing_number',
            'management_fee_type', 'management_fee_value',
            'quickbooks_enabled', 'google_calendar_enabled', 'slack_enabled',
            'slack_webhook_url', 'api_enabled', 'api_key', 'webhook_url',
            'webhook_secret', 'auto_assign_maintenance', 'maintenance_categories',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate(self, attrs):
        numeric_fields = [
            'payment_reminder_days', 'lease_expiry_days', 'otp_expire_minutes',
            'tax_percentage', 'payment_due_days', 'late_fee_percentage', 'late_fee_amount',
            'grace_period_days', 'invoice_day_of_month'
        ]
        for field in numeric_fields:
            if field in attrs and attrs[field] is not None:
                if attrs[field] < 0:
                    raise serializers.ValidationError({field: f"{field.replace('_', ' ').capitalize()} cannot be negative."})
        return attrs

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            # Mask sensitive fields for roles that are not platform admins or facility managers
            allowed_roles = ('master_admin', 'masteradmin', 'super_admin', 'superadmin', 'facility_manager')
            if request.user.role not in allowed_roles:
                sensitive_fields = [
                    'bank_account_number', 'bank_routing_number',
                    'razorpay_webhook_secret', 'slack_webhook_url',
                    'webhook_secret', 'api_key'
                ]
                for field in sensitive_fields:
                    if field in ret and ret[field]:
                        ret[field] = '********'
        return ret

class KYCLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCLog
        fields = '__all__'

class KYCSerializer(serializers.ModelSerializer):
    logs = KYCLogSerializer(many=True, read_only=True)
    organization_name = serializers.CharField(source='tenant.name', read_only=True)
    admin_name = serializers.SerializerMethodField()
    admin_email = serializers.CharField(source='email', read_only=True)

    class Meta:
        model = KYC
        fields = [
            'id', 'tenant', 'organization_name', 'admin_name', 'admin_email',
            'full_name', 'email', 'phone', 'pan_number', 'id_proof', 'pan_card',
            'business_name', 'business_address', 'business_reg', 'gst_number', 'gst_cert',
            'status', 'remarks', 'submitted_at', 'approved_at', 'created_at',
            'updated_at', 'logs'
        ]
        read_only_fields = ['id', 'tenant', 'status', 'submitted_at', 'approved_at', 'created_at', 'updated_at']

    def get_admin_name(self, obj):
        request = self.context.get('request')
        is_admin = False
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            if request.user.role in ('super_admin', 'superadmin', 'master_admin', 'masteradmin'):
                is_admin = True
        
        schema_name = getattr(obj.tenant, 'schema_name', None) if hasattr(obj, 'tenant') else getattr(obj, 'tenant_id', None)
        if not schema_name or not is_admin:
            return obj.full_name or "Unknown Admin"

        from django.core.cache import cache
        cache_key = f"tenant_admin_name_{schema_name}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        # Check if the active schema is the tenant's schema and request user is master_admin
        from django.db import connection
        if getattr(connection, 'schema_name', 'public') == schema_name:
            if request and getattr(request, 'user', None) and request.user.is_authenticated:
                if request.user.role in ('master_admin', 'masteradmin'):
                    name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
                    cache.set(cache_key, name, 300) # Cache for 5 minutes
                    return name

        try:
            # Attempt to find the Master Admin in the current connection schema first.
            # Master Admins are created in the public schema with tenant_id=schema_name,
            # so querying from the public context does not require an expensive schema context switch.
            admin = User.objects.filter(tenant_id=schema_name, role__in=('master_admin', 'masteradmin')).only('first_name', 'last_name', 'username').first()
            if admin:
                name = f"{admin.first_name} {admin.last_name}".strip() or admin.username
                cache.set(cache_key, name, 300)
                return name
        except Exception:
            pass

        try:
            with schema_context(schema_name):
                admin = User.objects.filter(role__in=('master_admin', 'masteradmin')).only('first_name', 'last_name', 'username').first()
                if admin:
                    name = f"{admin.first_name} {admin.last_name}".strip() or admin.username
                    cache.set(cache_key, name, 300) # Cache for 5 minutes
                    return name
        except Exception:
            pass
        return obj.full_name or "Unknown Admin"

class ClientSerializer(serializers.ModelSerializer):
    domains = DomainSerializer(many=True, read_only=True)
    settings = TenantSettingsSerializer(read_only=True)
    subscription = TenantSubscriptionSerializer(read_only=True)
    kyc_details = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()
    display_domain = serializers.SerializerMethodField()
    
    class Meta:
        model = Client
        fields = [
            'id', 'schema_name', 'name', 'description', 'logo',
            'contact_email', 'contact_phone', 'address',
            'city', 'state', 'district', 'pincode', 'country',
            'subscription_plan', 'features', 'is_active', 'is_confirmed', 'is_paid',
            'created_on', 'updated_on', 'domains', 'settings', 
            'subscription', 'kyc_details', 'stats', 'display_domain'
        ]
        read_only_fields = ['id', 'schema_name', 'created_on', 'updated_on']

    def get_kyc_details(self, obj):
        try:
            kyc = obj.kyc
        except Exception:
            return None

        # Return basic status to save db queries (especially avoid admin_name querying)
        # unless full details are requested.
        request = self.context.get('request')
        include_kyc_details = self.context.get('include_kyc_details', False)
        view = self.context.get('view')
        action = getattr(view, 'action', None)

        if not include_kyc_details and action not in ('retrieve', 'kyc_review', 'approve_kyc', 'reject_kyc'):
            return {
                'id': kyc.id,
                'status': kyc.status,
                'submitted_at': kyc.submitted_at,
                'approved_at': kyc.approved_at
            }
        
        return KYCSerializer(kyc, context=self.context).data

    def get_display_domain(self, obj):
        if hasattr(obj, '_prefetched_objects_cache') and 'domains' in obj._prefetched_objects_cache:
            for domain in obj.domains.all():
                if domain.is_primary:
                    return domain.domain
            return None
        primary_domain = obj.domains.filter(is_primary=True).first()
        if primary_domain:
            return primary_domain.domain
        return None

    def get_stats(self, obj):
        # Do not calculate stats during list, current tenant, or current user requests to avoid N+1 query storms.
        # Compute stats only when explicitly requested in context or in detail (retrieve) view.
        request = self.context.get('request')
        view = self.context.get('view')
        action = getattr(view, 'action', None)
        
        if not self.context.get('include_stats', False) and action != 'retrieve':
            return None

        try:
            from properties.models import Township, Unit
            with schema_context(obj.schema_name):
                total_users = User.objects.count()
                total_units = Unit.objects.count()
                active_units = Unit.objects.filter(status='occupied').count()
                total_colonies = Township.objects.count()
                total_facility_managers = User.objects.filter(role='facility_manager').count()
                master_admin_username = User.objects.filter(role='master_admin').values_list('username', flat=True).first() or 'Not Found'
                
                return {
                    'total_users': total_users,
                    'active_units': active_units,
                    'total_units': total_units,
                    'total_colonies': total_colonies,
                    'total_facility_managers': total_facility_managers,
                    'master_admin_username': master_admin_username
                }
        except Exception as e:
            logger.error(f"Error fetching stats for {obj.schema_name}: {e}")
            return {
                'total_users': 0, 'active_units': 0, 'total_units': 0,
                'total_colonies': 0, 'total_facility_managers': 0,
                'master_admin_username': 'Error'
            }

class ClientCreateSerializer(serializers.ModelSerializer):
    domain = serializers.CharField(write_only=True)
    setup_subscription = serializers.BooleanField(default=True, write_only=True)
    admin_name = serializers.CharField(write_only=True, required=False)
    admin_email = serializers.EmailField(write_only=True, required=False)
    admin_username = serializers.CharField(write_only=True, required=False)
    admin_password = serializers.CharField(write_only=True, required=False)
    addon_service_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)
    
    class Meta:
        model = Client
        fields = [
            'name', 'description', 'contact_email', 'contact_phone',
            'address', 'subscription_plan', 'features', 'domain',
            'setup_subscription', 'admin_name', 'admin_email',
            'admin_username', 'admin_password', 'expected_pan', 'expected_gst',
            'addon_service_ids'
        ]
    
    def validate_domain(self, value):
        domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
        if not re.match(domain_pattern, value):
            raise serializers.ValidationError("Invalid domain format")
        
        suffix = getattr(settings, 'TENANT_DOMAIN_SUFFIX', None)
        if not suffix:
            is_localhost = ('localhost' in getattr(settings, 'FRONTEND_URL', '')) or settings.DEBUG
            suffix = '.localhost' if is_localhost else '.hoaconnecthub.com'
        normalized = value if '.' in value else f"{value}{suffix}"
        
        if Domain.objects.filter(domain__iexact=value).exists() or Domain.objects.filter(domain__iexact=normalized).exists():
            raise serializers.ValidationError("Domain already exists")
        return value
    
    def validate_name(self, value):
        if Client.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError("An organization with this name already exists.")
        return value
    
    def create(self, validated_data):
        domain_name = validated_data.pop('domain')
        setup_subscription = validated_data.pop('setup_subscription', True)
        admin_name = validated_data.pop('admin_name', None)
        admin_email = validated_data.pop('admin_email', None)
        admin_username = validated_data.pop('admin_username', None)
        admin_password = validated_data.pop('admin_password', "Propra@123")
        addon_service_ids = validated_data.pop('addon_service_ids', [])
        
        if admin_username or admin_email:
            target_username = admin_username or (admin_email.split('@')[0] if admin_email else None)
            if target_username and User.objects.filter(username=target_username).exists():
                raise serializers.ValidationError({"error": f"Username '{target_username}' is already taken by another user on the platform. Please choose a different username or email."})
            if admin_email and User.objects.filter(email=admin_email).exists():
                raise serializers.ValidationError({"error": f"Email '{admin_email}' is already registered on the platform. Please use a different email."})
                
        if domain_name and '.' not in domain_name:
            suffix = getattr(settings, 'TENANT_DOMAIN_SUFFIX', None)
            if not suffix:
                is_localhost = ('localhost' in getattr(settings, 'FRONTEND_URL', '')) or settings.DEBUG
                suffix = '.localhost' if is_localhost else '.hoaconnecthub.com'
            domain_name = f"{domain_name}{suffix}"
        
        safe_name = re.sub(r'\W+', '_', validated_data['name'].lower())
        schema_name = f"tenant_{safe_name}"
        
        counter = 1
        original_schema = schema_name
        while Client.objects.filter(schema_name=schema_name).exists():
            schema_name = f"{original_schema}_{counter}"; counter += 1
        
        # 0. Populate default features from plan
        if not validated_data.get('features'):
            from pricing.models import PricingPlan, PlanServiceMapping, PlanService
            plan_slug = validated_data.get('subscription_plan', 'basic')
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
                'Developer Portal': 'developer_portal',
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
                        
            # Enable explicitly selected add-on services
            if addon_service_ids:
                addons = PlanService.objects.filter(id__in=addon_service_ids)
                for addon in addons:
                    f_key = SERVICE_TO_FEATURE_KEY.get(addon.name)
                    if f_key:
                        default_features[f_key] = True
            
            validated_data['features'] = default_features

        tenant = Client.objects.create(schema_name=schema_name, **validated_data)
        Domain.objects.create(domain=domain_name, tenant=tenant, is_primary=True)
        
        if admin_email:
            # Create Master Admin in PUBLIC schema for global visibility
            user = User.objects.create_user(
                username=admin_username or admin_email.split('@')[0],
                email=admin_email, password=admin_password,
                first_name=admin_name.split(' ')[0] if admin_name else "Admin",
                role='master_admin', is_active=True, is_approved=True, tenant_id=tenant.schema_name
            )
            try:
                from accounts.permissions import ALL_PERMISSION_CODES
                user.permissions = list(ALL_PERMISSION_CODES)
                user.save()
            except Exception: pass
            
            # Clone Master Admin user into the tenant schema context
            try:
                # Get all field data from the public user object
                user_data = {}
                for field in user._meta.fields:
                    user_data[field.name] = getattr(user, field.name)
                
                with schema_context(tenant.schema_name):
                    new_user = User(**user_data)
                    new_user.save(force_insert=True)
                    logger.info(f"Cloned Master Admin user '{user.username}' into tenant schema '{tenant.schema_name}' successfully.")
            except Exception as clone_err:
                logger.error(f"Error cloning master admin into tenant schema '{tenant.schema_name}': {clone_err}")

            try:
                from accounts.services.email_service import EmailService
                EmailService.send_organization_credentials_email(user, admin_password, tenant.name, domain_name)
            except Exception: pass
            
            # Now set up any tenant-specific initial data inside the schema if needed
            # (But User is shared, so we don't need context for it)
            
            try:
                kyc, _ = KYC.objects.get_or_create(tenant=tenant, defaults={'full_name': admin_name or "Admin", 'email': admin_email, 'status': 'not_started'})
                if admin_name or admin_email:
                    KYC.objects.filter(pk=kyc.pk).update(full_name=admin_name or kyc.full_name, email=admin_email or kyc.email)
            except Exception: pass

            try:
                PlatformInvoice.objects.filter(tenant=tenant, billing_email='billing@hoaconnecthub.com').update(
                    billing_email=admin_email or tenant.contact_email or 'billing@hoaconnecthub.com'
                )
            except Exception: pass
        
        if setup_subscription:
            try:
                from pricing.models import PricingPlan, Subscription
                plan = PricingPlan.objects.filter(slug__iexact=tenant.subscription_plan or 'basic').first() or PricingPlan.objects.filter(is_active=True).first()
                if plan: Subscription.objects.update_or_create(tenant_schema=tenant.schema_name, defaults={'plan': plan, 'status': 'active', 'billing_cycle': 'monthly', 'current_period_start': timezone.now()})
            except Exception: pass
        return tenant

class ClientUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ['name', 'description', 'logo', 'contact_email', 'contact_phone', 'address', 'subscription_plan', 'features', 'is_active']

class FeatureToggleSerializer(serializers.Serializer):
    features = serializers.JSONField()

class TenantStatsSerializer(serializers.Serializer):
    total_users = serializers.IntegerField(read_only=True)
    total_units = serializers.IntegerField(read_only=True)

class SystemStatsSerializer(serializers.Serializer):
    total_tenants = serializers.IntegerField(read_only=True)
    active_tenants = serializers.IntegerField(read_only=True)

class BulkFeatureUpdateSerializer(serializers.Serializer):
    tenant_ids = serializers.ListField(child=serializers.CharField())
    features = serializers.JSONField()

class DomainCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Domain
        fields = ['domain', 'tenant', 'is_primary']

    def validate_domain(self, value):
        domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
        if not re.match(domain_pattern, value):
            raise serializers.ValidationError("Invalid domain format")
        
        suffix = getattr(settings, 'TENANT_DOMAIN_SUFFIX', None)
        if not suffix:
            is_localhost = ('localhost' in getattr(settings, 'FRONTEND_URL', '')) or settings.DEBUG
            suffix = '.localhost' if is_localhost else '.hoaconnecthub.com'
        normalized = value if '.' in value else f"{value}{suffix}"
        
        qs = Domain.objects.filter(domain__iexact=value)
        qs_normalized = Domain.objects.filter(domain__iexact=normalized)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)
            qs_normalized = qs_normalized.exclude(id=self.instance.id)
            
        if qs.exists() or qs_normalized.exists():
            raise serializers.ValidationError("Domain already exists")
        return value

class PlatformInvoiceSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='tenant.name', read_only=True)
    kyc_status = serializers.SerializerMethodField()

    class Meta:
        model = PlatformInvoice
        fields = [
            'id', 'tenant', 'organization_name', 'invoice_number', 'amount', 
            'plan_name', 'status', 'billing_email', 'issue_date', 'due_date', 
            'paid_at', 'transaction_id', 'payment_method', 'remarks', 
            'created_at', 'updated_at', 'kyc_status'
        ]
        read_only_fields = ['id', 'invoice_number', 'issue_date', 'created_at', 'updated_at']

    def get_kyc_status(self, obj):
        try:
            return obj.tenant.kyc.status
        except Exception:
            return 'pending'

class PlatformPaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformPaymentMethod
        fields = '__all__'
        read_only_fields = ['id', 'tenant', 'created_at', 'updated_at']

class PlatformAutopayEnrollmentSerializer(serializers.ModelSerializer):
    payment_method_details = PlatformPaymentMethodSerializer(source='payment_method', read_only=True)
    class Meta:
        model = PlatformAutopayEnrollment
        fields = '__all__'
        read_only_fields = ['id', 'tenant', 'created_at', 'updated_at']

