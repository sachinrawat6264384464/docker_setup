# tenants/models.py
import uuid
import datetime
import random
import string
from django.db import models
from django.utils import timezone
from django_tenants.models import TenantMixin, DomainMixin

class Client(TenantMixin):
    """
    Main tenant model - each property management company gets their own schema.
    """
    # Basic company information
    name = models.CharField(max_length=200, help_text="Property company name")
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to='tenant_logos/', blank=True, null=True)
    onboarded_by = models.UUIDField(null=True, blank=True, help_text="ID of the user who created this tenant")
    
    # Contact information
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    district = models.CharField(max_length=100, blank=True, null=True)
    pincode = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    
    # Subscription and billing
    subscription_plan = models.CharField(
        max_length=50,
        choices=[
            ('basic', 'Basic Plan'),
            ('premium', 'Premium Plan'),
            ('enterprise', 'Enterprise Plan'),
        ],
        default='basic'
    )
    
    # Feature toggles for this tenant
    features = models.JSONField(
        default=dict,
        help_text="Available features for this property company"
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    is_confirmed = models.BooleanField(default=False)
    
    @property
    def is_paid(self):
        """Check if any platform invoice has been paid/verified."""
        if hasattr(self, '_prefetched_objects_cache') and 'platform_invoices' in self._prefetched_objects_cache:
            return any(inv.status in ('paid', 'verified') for inv in self.platform_invoices.all())
        return self.platform_invoices.filter(status__in=['paid', 'verified']).exists()
    
    # Verification Requirements (Set by Superadmin)
    expected_pan = models.CharField(max_length=20, blank=True, null=True, help_text="PAN required for verification")
    expected_gst = models.CharField(max_length=30, blank=True, null=True, help_text="GST required for verification")
    
    # US Specific Details
    ein = models.CharField(max_length=50, blank=True, null=True, help_text="Employer Identification Number")
    sos_id = models.CharField(max_length=50, blank=True, null=True, help_text="State Registration Number (SOS ID)")
    
    # Timestamps
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)
    
    # Required django-tenants fields
    auto_create_schema = True
    auto_drop_schema = True
    
    def save(self, *args, **kwargs):
        # Set default features for new tenants
        if not self.features:
            self.features = {
                'people_hub': True,
                'csv_upload': True,
                'properties': True,
                'maintenance': True,
                'payments': True,
                'notifications': True,
                'amenities': False,
                'marketplace': False,
                'analytics': False,
            }
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Property Company"
        verbose_name_plural = "Property Companies"
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['created_on']),
            models.Index(fields=['subscription_plan']),
        ]
    
    def __str__(self):
        return self.name

class Domain(DomainMixin):
    """
    Domain routing for tenants.
    """
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='domains')
    is_primary = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('tenant', 'is_primary')
    
    def __str__(self):
        return f"{self.domain} -> {self.tenant.name}"

class TenantSettings(models.Model):
    """
    Additional settings for each tenant.
    """
    tenant = models.OneToOneField(
        Client, 
        on_delete=models.CASCADE, 
        related_name='settings'
    )
    
    # Branding customization
    primary_color = models.CharField(max_length=7, default='#14213D')
    secondary_color = models.CharField(max_length=7, default='#C1CFEB')
    accent_color = models.CharField(max_length=7, default='#EAB308')
    logo_url = models.URLField(max_length=500, blank=True, null=True)
    favicon_url = models.URLField(max_length=500, blank=True, null=True)
    login_message = models.TextField(blank=True, default='')
    login_page_message = models.TextField(blank=True, default='')
    footer_text = models.TextField(blank=True, default='')
    
    # General Settings
    currency = models.CharField(max_length=10, default='USD')
    date_format = models.CharField(max_length=20, default='MM/DD/YYYY')
    fiscal_year_start = models.CharField(max_length=2, default='01')

    # Notification preferences
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=True)
    payment_reminders = models.BooleanField(default=True)
    payment_reminder_days = models.IntegerField(default=3)
    maintenance_updates = models.BooleanField(default=True)
    lease_expiry_alerts = models.BooleanField(default=True)
    lease_expiry_days = models.IntegerField(default=30)
    security_alerts = models.BooleanField(default=True)
    weekly_digest = models.BooleanField(default=False)
    monthly_report = models.BooleanField(default=True)
    new_resident_welcome = models.BooleanField(default=True)
    document_expiry_alerts = models.BooleanField(default=True)
    
    # OTP settings
    otp_required = models.BooleanField(default=True)
    otp_expire_minutes = models.IntegerField(default=5)
    
    # Payment settings
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    payment_due_days = models.IntegerField(default=5)
    late_fee_enabled = models.BooleanField(default=False)
    late_fee_type = models.CharField(max_length=20, default='percentage')
    late_fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)
    late_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    grace_period_days = models.IntegerField(default=5)
    auto_invoicing = models.BooleanField(default=False)
    invoice_day_of_month = models.IntegerField(default=1)

    # 3-Way Split Management Fee Configuration (Global)
    management_fee_type = models.CharField(
        max_length=20, 
        choices=[('percentage', 'Percentage'), ('fixed', 'Fixed Amount')],
        default='percentage',
        help_text="Global default management cut taken from rent."
    )
    management_fee_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.0,
        help_text="Global management fee percentage or fixed amount"
    )

    # Gateway flags
    razorpay_enabled = models.BooleanField(default=False)
    razorpay_key_id = models.CharField(max_length=100, blank=True, default='')
    razorpay_webhook_secret = models.CharField(max_length=100, blank=True, default='')
    paypal_enabled = models.BooleanField(default=False)
    paypal_client_id = models.CharField(max_length=100, blank=True, default='')
    bank_transfer_enabled = models.BooleanField(default=True)
    bank_name = models.CharField(max_length=200, blank=True, default='')
    bank_account_name = models.CharField(max_length=200, blank=True, default='')
    bank_account_number = models.CharField(max_length=100, blank=True, default='')
    bank_routing_number = models.CharField(max_length=100, blank=True, default='')

    # Integrations
    quickbooks_enabled = models.BooleanField(default=False)
    google_calendar_enabled = models.BooleanField(default=False)
    slack_enabled = models.BooleanField(default=False)
    slack_webhook_url = models.URLField(max_length=500, blank=True, null=True)
    api_enabled = models.BooleanField(default=False)
    api_key = models.CharField(max_length=100, blank=True, default='')
    webhook_url = models.URLField(max_length=500, blank=True, null=True)
    webhook_secret = models.CharField(max_length=100, blank=True, default='')
    
    # Maintenance settings
    auto_assign_maintenance = models.BooleanField(default=False)
    maintenance_categories = models.JSONField(
        default=list,
        help_text="Available maintenance categories"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        if not self.maintenance_categories:
            self.maintenance_categories = [
                {'name': 'Plumbing', 'priority': 'medium'},
                {'name': 'Electrical', 'priority': 'high'},
                {'name': 'HVAC', 'priority': 'medium'},
                {'name': 'Cleaning', 'priority': 'low'},
                {'name': 'Emergency', 'priority': 'urgent'},
            ]
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Settings for {self.tenant.name}"

class TenantFeature(models.Model):
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(
        max_length=50,
        choices=[
            ('primary', 'Primary Modules'),
            ('secondary', 'Secondary Services'),
            ('advanced', 'Advanced Tools'),
            ('setup', 'Onboarding & Setup'),
            # Legacy aliases kept for backward compatibility
            ('basic', 'Basic Features'),
            ('premium', 'Premium Features'),
            ('enterprise', 'Enterprise Features'),
            ('core', 'Core Features'),
        ],
        default='primary'
    )
    is_active = models.BooleanField(default=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.display_name

class TenantSubscription(models.Model):
    tenant = models.OneToOneField(Client, on_delete=models.CASCADE, related_name='subscription')
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    is_trial = models.BooleanField(default=False)
    trial_end_date = models.DateTimeField(null=True, blank=True)
    monthly_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    billing_cycle = models.CharField(
        max_length=20,
        choices=[('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('yearly', 'Yearly')],
        default='monthly'
    )
    max_users = models.IntegerField(default=100)
    max_properties = models.IntegerField(default=10)
    max_units = models.IntegerField(default=500)
    status = models.CharField(
        max_length=20,
        choices=[('active', 'Active'), ('suspended', 'Suspended'), ('expired', 'Expired'), ('cancelled', 'Cancelled')],
        default='active'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    @property
    def is_expired(self):
        return self.end_date and self.end_date < timezone.now()
    
    @property
    def days_remaining(self):
        if self.end_date:
            delta = self.end_date - timezone.now()
            return max(0, delta.days)
        return None

class KYC(models.Model):
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('resubmission_required', 'Resubmission Required'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(Client, on_delete=models.CASCADE, related_name='kyc')
    full_name = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    pan_number = models.CharField(max_length=20, blank=True, null=True)
    id_proof = models.FileField(upload_to='kyc_docs/id/', blank=True, null=True)
    pan_card = models.FileField(upload_to='kyc_docs/pan/', blank=True, null=True)
    business_name = models.CharField(max_length=255, blank=True, null=True)
    business_address = models.TextField(blank=True, null=True)
    business_reg = models.FileField(upload_to='kyc_docs/business/', blank=True, null=True)
    gst_number = models.CharField(max_length=30, blank=True, null=True)
    gst_cert = models.FileField(upload_to='kyc_docs/gst/', blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='not_started')
    remarks = models.TextField(blank=True, null=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"KYC for {self.tenant.name}"

class KYCLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kyc = models.ForeignKey(KYC, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=50)
    remarks = models.TextField(blank=True, null=True)
    created_by_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class PlatformInvoice(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('paid', 'Paid'), ('verified', 'Verified'), ('cancelled', 'Cancelled')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='platform_invoices')
    invoice_number = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    plan_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    billing_email = models.EmailField()
    issue_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    paid_at = models.DateTimeField(null=True, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    remarks = models.TextField(blank=True)
    pending_features = models.JSONField(default=list, blank=True, help_text="Features to activate upon payment")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        old_status = None
        if not is_new:
            try:
                old_status = PlatformInvoice.objects.get(pk=self.pk).status
            except PlatformInvoice.DoesNotExist:
                pass

        if self.status in ['paid', 'verified'] and not self.paid_at:
            from django.utils import timezone
            self.paid_at = timezone.now()

        if not self.invoice_number:
            import random, string, datetime
            year = datetime.datetime.now().year
            random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            count = PlatformInvoice.objects.count() + 1
            self.invoice_number = f"PF-ORG-{year}-{count:04d}-{random_suffix}"
            
        super().save(*args, **kwargs)
        
        # ACTIVATE FEATURES IF PAID OR VERIFIED
        if old_status not in ['paid', 'verified'] and self.status in ['paid', 'verified'] and self.pending_features:
            self.activate_pending_features()

        # Send platform invoice paid notification to Master Admins
        if old_status not in ['paid', 'verified'] and self.status in ['paid', 'verified']:
            try:
                from notifications.services import NotificationService
                from accounts.models import User
                from django_tenants.utils import schema_context
                
                # Switch to tenant schema to save the notification in their schema
                with schema_context(self.tenant.schema_name):
                    admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
                    if not admins.exists() and self.billing_email:
                        admins = User.objects.filter(email__iexact=self.billing_email)
                        
                    for admin in admins:
                        NotificationService.send(
                            user=admin,
                            title=f'Platform Payment Successful - Invoice #{self.invoice_number}',
                            message=f'Your payment of ${self.amount} for plan/addon "{self.plan_name}" has been processed successfully.',
                            notification_type='payment',
                            priority='medium',
                            send_email=True,
                            action_url='/masteradmin/subscription',
                        )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to send platform invoice paid notification: {e}")

    def activate_pending_features(self):
        """Activates features stored in pending_features and updates subscription amount."""
        tenant = self.tenant
        features_added = False
        total_price_increase = 0
        
        if not tenant.features:
            tenant.features = {}
            
        for feature_name in self.pending_features:
            if feature_name not in tenant.features or not tenant.features[feature_name]:
                tenant.features[feature_name] = True
                features_added = True
                # Get feature price to update monthly subscription
                try:
                    feature = TenantFeature.objects.get(name=feature_name)
                    total_price_increase += feature.price
                except TenantFeature.DoesNotExist:
                    pass
                
                # Also activate any matching TenantAddonGrant in pricing app
                try:
                    from pricing.models import PlanService, TenantAddonGrant
                    FEATURE_KEY_TO_SERVICE_NAME = {
                        'dashboard': 'Dashboard',
                        'communities': 'Communities',
                        'buildings': 'Blocks/Sectors',
                        'units': 'Units',
                        'people_hub': 'People Hub',
                        'facility_managers': 'Facility Managers',
                        'senior_managers': 'Senior Hub Managers',
                        'leases': 'Rental Hub',
                        'documents': 'Documents',
                        'bulk_upload': 'Bulk Upload',
                        'bulk_export': 'Bulk Export',
                        'payments': 'Payments',
                        'maintenance': 'Maintenance',
                        'amenities': 'Amenities',
                        'security': 'Security',
                        'vendors': 'Vendors',
                        'calendar': 'Calendar',
                        'communication': 'Message Center',
                        'support': 'Support Center',
                        'developer_portal': 'Developer Portal',
                        'reports': 'Reports',
                    }
                    service_name = FEATURE_KEY_TO_SERVICE_NAME.get(feature_name)
                    if service_name:
                        service = PlanService.objects.filter(name=service_name).first()
                        if service:
                            TenantAddonGrant.objects.filter(
                                tenant_schema=tenant.schema_name,
                                service=service
                            ).update(is_active=True)
                except Exception:
                    pass
        
        if features_added:
            tenant.save()
            # Update subscription monthly amount
            subscription = getattr(tenant, 'subscription', None)
            if subscription:
                subscription.monthly_amount += total_price_increase
                subscription.save()
            
            # Clear pending features to avoid double activation
            PlatformInvoice.objects.filter(pk=self.pk).update(pending_features=[])
            
            try:
                from accounts.models import ActivityLog
                from accounts.models import User
                # Try to log this event
                admin = User.objects.filter(role__in=['super_admin', 'superadmin']).first()
                if admin:
                    ActivityLog.objects.create(
                        user=admin,
                        action='services_activated',
                        description=f'Features {self.pending_features} activated for {tenant.name} after payment of {self.invoice_number}',
                        tenant_schema='public'
                    )
            except Exception:
                pass
class PlatformPaymentMethod(models.Model):
    """Saved payment methods for Master Admins (Organization level)"""
    METHOD_TYPES = [
        ('stripe_card', 'Card (Stripe)'),
        ('bank_account', 'Bank Account'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='payment_methods')
    method_type = models.CharField(max_length=50, choices=METHOD_TYPES)
    
    # Gateway Details
    gateway_customer_id = models.CharField(max_length=200, blank=True)
    gateway_payment_method_id = models.CharField(max_length=200)
    
    # Masked Details
    card_last4 = models.CharField(max_length=4, blank=True)
    card_brand = models.CharField(max_length=50, blank=True)
    card_exp_month = models.IntegerField(null=True, blank=True)
    card_exp_year = models.IntegerField(null=True, blank=True)
    
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.tenant.name} - {self.card_brand} •••• {self.card_last4}"

class PlatformAutopayEnrollment(models.Model):
    """Auto-pay enrollment for Organization platform subscription"""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(Client, on_delete=models.CASCADE, related_name='autopay_enrollment')
    payment_method = models.ForeignKey(PlatformPaymentMethod, on_delete=models.SET_NULL, null=True)
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    frequency = models.CharField(max_length=20, default='monthly')
    
    next_payment_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Autopay for {self.tenant.name} - {self.status}"