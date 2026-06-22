# utilities/models.py - UPDATED WITH INSURANCE
from django.db import models
from django.contrib.auth import get_user_model
from properties.models import Building, Unit
import uuid

User = get_user_model()

class UtilityType(models.Model):
    UTILITY_CATEGORY_CHOICES = [
        ('electricity', 'Electricity'),
        ('water', 'Water'),
        ('gas', 'Gas'),
        ('internet', 'Internet'),
        ('maintenance', 'Maintenance'),
        ('parking', 'Parking'),
        ('security', 'Security'),
        ('waste_management', 'Waste Management'),
        ('property_tax', 'Property Tax'),
        ('insurance', 'Insurance'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50, choices=UTILITY_CATEGORY_CHOICES)
    description = models.TextField(blank=True)
    unit_of_measurement = models.CharField(max_length=50, help_text="e.g., kWh, gallons, cubic meters")
    base_rate = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate per unit")
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'Utility Types'
        ordering = ['category', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

class UtilityBill(models.Model):
    BILL_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utility_type = models.ForeignKey(UtilityType, on_delete=models.CASCADE, related_name='bills')
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='utility_bills')
    tenant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='utility_bills', db_constraint=False)
    
    bill_number = models.CharField(max_length=50, unique=True)
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    
    previous_reading = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    current_reading = models.DecimalField(max_digits=10, decimal_places=2)
    consumption = models.DecimalField(max_digits=10, decimal_places=2)
    
    rate_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    base_amount = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    additional_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=BILL_STATUS_CHOICES, default='pending')
    
    payment_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    invoiced = models.BooleanField(default=False)

    notes = models.TextField(blank=True)
    
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='generated_bills', db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-billing_period_start', '-created_at']
        unique_together = ['utility_type', 'unit', 'billing_period_start', 'billing_period_end']
        indexes = [
            models.Index(fields=['unit', 'billing_period_start']),
            models.Index(fields=['status', 'due_date']),
        ]

    def __str__(self):
        return f"{self.bill_number} - {self.utility_type.name} - {self.unit}"
    
    def save(self, *args, **kwargs):
        if not self.bill_number:
            from django.utils import timezone
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            self.bill_number = f"UTIL-{timestamp}-{str(self.id)[:8]}"
        
        self.consumption = self.current_reading - self.previous_reading
        self.base_amount = self.consumption * self.rate_per_unit
        self.total_amount = self.base_amount + self.tax_amount + self.additional_charges - self.discount
        
        super().save(*args, **kwargs)

class UtilityMeterReading(models.Model):
    READING_TYPE_CHOICES = [
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
        ('estimated', 'Estimated'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utility_type = models.ForeignKey(UtilityType, on_delete=models.CASCADE, related_name='readings')
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='meter_readings')
    
    reading_date = models.DateField()
    reading_value = models.DecimalField(max_digits=10, decimal_places=2)
    reading_type = models.CharField(max_length=20, choices=READING_TYPE_CHOICES, default='manual')
    
    meter_number = models.CharField(max_length=100, blank=True)
    photo = models.ImageField(upload_to='meter_readings/', null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='recorded_readings', db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-reading_date', '-created_at']
        indexes = [
            models.Index(fields=['unit', 'reading_date']),
        ]

    def __str__(self):
        return f"{self.utility_type.name} - {self.unit} - {self.reading_date}"

class UtilityProvider(models.Model):
    PROVIDER_TYPE_CHOICES = [
        ('electricity', 'Electricity'),
        ('water', 'Water'),
        ('gas', 'Gas'),
        ('internet', 'Internet'),
        ('insurance', 'Insurance'),
        ('property_tax', 'Property Tax'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    utility_category = models.CharField(max_length=50, choices=PROVIDER_TYPE_CHOICES)
    
    contact_person = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    
    address = models.TextField(blank=True)
    website = models.URLField(blank=True)
    
    account_number = models.CharField(max_length=100, blank=True)
    
    is_active = models.BooleanField(default=True)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_utility_category_display()})"

class InsuranceProvider(models.Model):
    """Dedicated model for insurance providers like Geico, State Farm, Progressive"""
    
    INSURANCE_TYPE_CHOICES = [
        ('property', 'Property Insurance'),
        ('liability', 'Liability Insurance'),
        ('flood', 'Flood Insurance'),
        ('earthquake', 'Earthquake Insurance'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, help_text="e.g., Geico, State Farm, Progressive")
    insurance_type = models.CharField(max_length=50, choices=INSURANCE_TYPE_CHOICES, default='property')
    
    contact_person = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    
    policy_number = models.CharField(max_length=100, blank=True)
    coverage_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    premium_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    policy_start_date = models.DateField(null=True, blank=True)
    policy_end_date = models.DateField(null=True, blank=True)
    
    address = models.TextField(blank=True)
    website = models.URLField(blank=True)
    
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        verbose_name = 'Insurance Provider'
        verbose_name_plural = 'Insurance Providers'
    
    def __str__(self):
        return f"{self.name} - {self.get_insurance_type_display()}"

class BuildingUtilityConnection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='utility_connections')
    provider = models.ForeignKey(UtilityProvider, on_delete=models.CASCADE, related_name='building_connections')
    utility_type = models.ForeignKey(UtilityType, on_delete=models.CASCADE, related_name='building_connections')
    
    connection_number = models.CharField(max_length=100)
    connection_date = models.DateField()
    
    meter_number = models.CharField(max_length=100, blank=True)
    
    is_active = models.BooleanField(default=True)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['building', 'utility_type']
        unique_together = ['building', 'provider', 'connection_number']
    
    def __str__(self):
        return f"{self.building.name} - {self.provider.name} - {self.utility_type.name}"

class BuildingInsurance(models.Model):
    """Link buildings to insurance providers"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='insurances')
    provider = models.ForeignKey(InsuranceProvider, on_delete=models.CASCADE, related_name='building_insurances')
    
    policy_number = models.CharField(max_length=100)
    coverage_amount = models.DecimalField(max_digits=12, decimal_places=2)
    premium_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    policy_start_date = models.DateField()
    policy_end_date = models.DateField()
    
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-policy_start_date']
        verbose_name = 'Building Insurance'
        verbose_name_plural = 'Building Insurances'
    
    def __str__(self):
        return f"{self.building.name} - {self.provider.name}"