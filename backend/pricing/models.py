from django.db import models
import uuid


class PlanService(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PricingPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    tagline = models.CharField(max_length=200, blank=True)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    annual_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    unit_limit = models.IntegerField(null=True, blank=True)
    manager_limit = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_custom_pricing = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)
    razorpay_plan_id = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=7, default='#3B82F6')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order']

    def __str__(self):
        return self.name


class PlanFeature(models.Model):
    plan = models.ForeignKey(PricingPlan, on_delete=models.CASCADE, related_name='features')
    feature_name = models.CharField(max_length=200)
    feature_key = models.CharField(max_length=100)
    is_included = models.BooleanField(default=True)
    limit_value = models.CharField(max_length=50, blank=True)
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['display_order']

    def __str__(self):
        return f"{self.plan.name} - {self.feature_name}"


class Subscription(models.Model):
    BILLING_CYCLE = [('monthly', 'Monthly'), ('annual', 'Annual')]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('trialing', 'Trialing'),
        ('past_due', 'Past Due'),
        ('cancelled', 'Cancelled'),
        ('paused', 'Paused'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_schema = models.CharField(max_length=100, unique=True)
    plan = models.ForeignKey(PricingPlan, on_delete=models.PROTECT, related_name='subscriptions')
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE, default='monthly')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trialing')
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    razorpay_subscription_id = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.tenant_schema} - {self.plan.name} ({self.status})"


class PlanServiceMapping(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(PricingPlan, on_delete=models.CASCADE, related_name='service_mappings')
    service = models.ForeignKey(PlanService, on_delete=models.CASCADE, related_name='plan_mappings')
    is_included = models.BooleanField(default=True)

    class Meta:
        unique_together = ('plan', 'service')
        ordering = ['plan__display_order', 'service__name']

    def __str__(self):
        status = 'Included' if self.is_included else 'Add-on'
        return f"{self.plan.name} - {self.service.name} ({status})"


class AddOnRequest(models.Model):
    """A MasterAdmin's request to enable additional services for their organization."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_schema = models.CharField(max_length=100, db_index=True)
    service = models.ForeignKey(PlanService, on_delete=models.CASCADE, related_name='addon_requests')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_by_email = models.EmailField(blank=True)
    requested_by_name = models.CharField(max_length=200, blank=True)
    reviewed_by_name = models.CharField(max_length=200, blank=True)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    quantity = models.IntegerField(default=1)
    notes = models.TextField(blank=True)
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tenant_schema} -> {self.service.name} ({self.status})"


class TenantAddonGrant(models.Model):
    """Tracks which add-on services have been approved/active for a tenant."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_schema = models.CharField(max_length=100, db_index=True)
    service = models.ForeignKey(PlanService, on_delete=models.CASCADE, related_name='grants')
    addon_request = models.OneToOneField(AddOnRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name='grant')
    is_active = models.BooleanField(default=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('tenant_schema', 'service')
        ordering = ['-granted_at']

    def __str__(self):
        return f"{self.tenant_schema} -> {self.service.name} ({'active' if self.is_active else 'revoked'})"


# Signal receiver to keep Client model synchronized
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Subscription)
def sync_tenant_plan_and_features(sender, instance, **kwargs):
    """
    Automatically syncs Client's subscription_plan and features when Subscription plan is updated.
    """
    from tenants.models import Client
    
    tenant_obj = Client.objects.filter(schema_name=instance.tenant_schema).first()
    if tenant_obj:
        plan_slug = instance.plan.slug.lower()
        
        # 1. Update the client's subscription_plan
        tenant_obj.subscription_plan = plan_slug
        
        # 2. Recalculate features based on mapping
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
        new_features = {key: False for key in SERVICE_TO_FEATURE_KEY.values()}
        # Always enable core system features
        new_features.update({
            'property_management': True,
            'unit_database': True,
            'member_portal': True,
            'billing_engine': True,
            'communication_hub': True,
            'dashboard': True,
        })
        
        # Query plan mappings
        mappings = PlanServiceMapping.objects.filter(plan=instance.plan)
        for m in mappings:
            f_key = SERVICE_TO_FEATURE_KEY.get(m.service.name)
            if f_key:
                new_features[f_key] = m.is_included
        
        # Merge with active addons for this tenant
        active_addons = TenantAddonGrant.objects.filter(tenant_schema=instance.tenant_schema, is_active=True).select_related('service')
        for grant in active_addons:
            f_key = SERVICE_TO_FEATURE_KEY.get(grant.service.name)
            if f_key:
                new_features[f_key] = True
                
        tenant_obj.features = new_features
        tenant_obj.save()
