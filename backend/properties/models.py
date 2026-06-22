# properties/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings
import uuid

User = get_user_model()


# ======================================================
# CITY / AREA / ZONE HIERARCHY (under company/tenant scope)
# ======================================================

class PropertyCity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    state = models.CharField(max_length=120, default='')
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = ('name', 'state')
        verbose_name = 'City'
        verbose_name_plural = 'Cities'

    def __str__(self):
        return f"{self.name}{f', {self.state}' if self.state else ''}"


class AreaZone(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    city_ref = models.ForeignKey(
        PropertyCity,
        on_delete=models.CASCADE,
        related_name='area_zones',
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['city_ref__name', 'name']
        unique_together = ('city_ref', 'name')
        verbose_name = 'Area / Zone'
        verbose_name_plural = 'Areas / Zones'

    def __str__(self):
        return f"{self.name} ({self.city_ref.name})"


# ======================================================
# TOWNSHIP (top-level grouping)
# ======================================================

class Township(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    city_ref = models.ForeignKey(
        PropertyCity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='townships',
    )
    area_zone = models.ForeignKey(
        AreaZone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='townships',
    )
    address = models.TextField(blank=True, default='')
    address_line1 = models.CharField(max_length=255, blank=True, default='')
    address_line2 = models.CharField(max_length=255, blank=True, default='')
    address_line3 = models.CharField(max_length=255, blank=True, default='')
    landmark = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, default='')
    district = models.CharField(max_length=100, blank=True, default='')

    state = models.CharField(max_length=100, default='')
    postal_code = models.CharField(max_length=20, default='', blank=True)
    country = models.CharField(max_length=100, default='India')
    managed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_townships',
        db_constraint=False
    )
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True, help_text="Soft delete / activation flag")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.city})"

    @property
    def complete_address(self):
        parts = [
            self.address_line1,
            self.address_line2,
            self.address_line3,
            self.landmark,
            self.city,
            self.state,
            self.postal_code,
            self.country,
        ]
        return ', '.join([p.strip() for p in parts if p and p.strip()])

    class Meta:
        ordering = ['name']
        verbose_name = 'Township'
        verbose_name_plural = 'Townships'


class Building(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    township = models.ForeignKey(
        Township,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='buildings',
    )
    name = models.CharField(max_length=200)
    address = models.TextField()
    address_line1 = models.CharField(max_length=255, blank=True, default='')
    address_line2 = models.CharField(max_length=255, blank=True, default='')
    address_line3 = models.CharField(max_length=255, blank=True, default='')
    landmark = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, default='')
    district = models.CharField(max_length=100, blank=True, default='')

    state = models.CharField(max_length=100, default='')
    postal_code = models.CharField(max_length=20, default='', blank=True)
    country = models.CharField(max_length=100, default='India')
    blocks = models.JSONField(default=list, blank=True, help_text="List of block names")
    num_blocks = models.IntegerField(default=0, help_text="Number of blocks in this building")
    total_floors = models.IntegerField(null=True, blank=True)
    apartments_per_floor = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        help_text="Number of apartments on each floor (legacy/fallback)",
    )
    total_units = models.IntegerField(null=True, blank=True)
    building_type = models.CharField(
        max_length=50,
        choices=[
            ('residential', 'Residential'),
            ('commercial', 'Commercial'),
            ('mixed', 'Mixed Use'),
            ('apartment', 'Apartment'),
        ],
        default='residential',
        null=True,
        blank=True
    )
    year_built = models.IntegerField(null=True, blank=True)
    amenities = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True, default='')
    managed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_buildings',
        db_constraint=False
    )
    is_active = models.BooleanField(default=True, help_text="Soft delete / activation flag")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name

    @property
    def complete_address(self):
        parts = [
            self.address_line1,
            self.address_line2,
            self.address_line3,
            self.landmark,
            self.city,
            self.state,
            self.postal_code,
            self.country,
        ]
        cleaned_parts = [part.strip() for part in parts if part and str(part).strip()]
        return ', '.join(cleaned_parts)
    
    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['city', 'state']),
            models.Index(fields=['created_at']),
        ]

# ======================================================
# BLOCK (under Building)
# ======================================================

class Block(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name='block_set',
    )
    name = models.CharField(max_length=100, help_text='Block identifier e.g. A, B, North Wing')
    building_type = models.CharField(
        max_length=50,
        choices=[
            ('residential', 'Residential'),
            ('commercial', 'Commercial'),
            ('mixed', 'Mixed Use'),
            ('apartment', 'Apartment'),
        ],
        default='residential'
    )
    year_built = models.IntegerField(null=True, blank=True)
    total_floors = models.IntegerField(default=0)
    apartments_per_floor = models.IntegerField(default=0, help_text="Number of apartments on each floor")
    total_units = models.IntegerField(default=0)
    property_area = models.FloatField(null=True, blank=True, help_text="Total property area in sq ft")
    business_name = models.CharField(max_length=255, blank=True, default='', help_text="Business name (for commercial/mixed wings)")
    business_registration_number = models.CharField(max_length=100, blank=True, default='', help_text="Business registration / GST number")
    address_line1 = models.CharField(max_length=255, blank=True, default='')
    address_line2 = models.CharField(max_length=255, blank=True, default='')
    address_line3 = models.CharField(max_length=255, blank=True, default='')
    landmark = models.CharField(max_length=255, blank=True, default='')
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True, help_text="Soft delete / activation flag")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.building.name} – Block {self.name}"

    class Meta:
        ordering = ['building', 'name']
        unique_together = ('building', 'name')
        verbose_name = 'Block'
        verbose_name_plural = 'Blocks'


# ======================================================
# FLOOR (under Block)
# ======================================================

class Floor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name='floors',
    )
    floor_number = models.IntegerField()
    label = models.CharField(max_length=50, blank=True, default='', help_text='Optional label e.g. Ground, Mezzanine')
    is_active = models.BooleanField(default=True, help_text="Soft delete / activation flag")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.block} – Floor {self.floor_number}"

    class Meta:
        ordering = ['block', 'floor_number']
        unique_together = ('block', 'floor_number')
        verbose_name = 'Floor'
        verbose_name_plural = 'Floors'


# ======================================================
# UNIT (existing, extended with optional FK to Floor)
# ======================================================

class Unit(models.Model):
    UNIT_TYPE_CHOICES = [
        ('owner_occupied', 'Owner Occupied'),
        ('tenant_occupied', 'Tenant Occupied'),
        ('vacant', 'Vacant'),
    ]

    STATUS_CHOICES = [
        ('available', 'Available'),
        ('occupied', 'Occupied'),
        ('maintenance', 'Maintenance'),
        ('reserved', 'Reserved'),
    ]

    CURRENCY_CHOICES = [
        ('USD', 'USD'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    building = models.ForeignKey(Building, related_name='units', on_delete=models.CASCADE)
    # Optional FK to the new hierarchical Floor model (nullable for backward compat)
    floor_ref = models.ForeignKey(
        'Floor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='apartments',
        help_text='Links this unit to a hierarchical Floor record',
    )
    unit_number = models.CharField(max_length=50)
    block = models.CharField(max_length=50, blank=True, null=True)
    floor = models.IntegerField(blank=True, null=True)
    unit_type = models.CharField(max_length=20, choices=UNIT_TYPE_CHOICES, default='vacant')
    unit_category = models.CharField(
        max_length=20,
        choices=[('residential', 'Residential'), ('commercial', 'Commercial')],
        default='residential',
        help_text='Category for mixed-use wings'
    )
    property_area = models.FloatField(null=True, blank=True, help_text="Unit area in sq ft (auto-filled from wing)")
    business_name = models.CharField(max_length=255, blank=True, default='', help_text="Business name (required for commercial units)")
    business_registration_number = models.CharField(max_length=100, blank=True, default='', help_text="Business registration / GST number")
    bedrooms = models.IntegerField(blank=True, null=True)
    bathrooms = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True)
    square_feet = models.IntegerField(blank=True, null=True)
    maintenance_rate_rupees = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    maintenance_rate_sqfeet = models.IntegerField(blank=True, null=True)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    monthly_maintenance = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    association_dues = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='USD')
    owner_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='owned_units',
        db_constraint=False
    )
    owner_first_name = models.CharField(max_length=100, blank=True, null=True)
    owner_last_name = models.CharField(max_length=100, blank=True, null=True)
    owner_email = models.EmailField(blank=True, null=True)
    owner_phone = models.CharField(max_length=30, blank=True, null=True)
    owner_address = models.TextField(blank=True, null=True)
    
    # Management Fee Override for this specific unit
    management_fee_override_type = models.CharField(
        max_length=20,
        choices=[('none', 'Use Global Default'), ('percentage', 'Percentage'), ('fixed', 'Fixed Amount')],
        default='none',
        help_text="Override the global management fee for this unit"
    )
    management_fee_override_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Override value if type is percentage or fixed"
    )

    current_resident = models.CharField(max_length=255, blank=True, null=True)
    gst_applicable = models.BooleanField(default=False)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    is_occupied = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, help_text="Soft delete / activation flag")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('building', 'unit_number')
        ordering = ['building', 'floor', 'unit_number']
        indexes = [
            models.Index(fields=['building', 'unit_number']),
            models.Index(fields=['status']),
            models.Index(fields=['unit_type']),
        ]

    def __str__(self):
        return f"{self.building.name} - {self.unit_number}"

class Lease(models.Model):
    LEASE_STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('terminated', 'Terminated'),
        ('pending', 'Pending'),
        ('suspended', 'Suspended'),   # Auto-set when parent colony is deactivated
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='leases')
    tenant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leases', db_constraint=False)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=LEASE_STATUS_CHOICES, default='pending')
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    security_deposit = models.DecimalField(max_digits=10, decimal_places=2)
    maintenance_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    late_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    late_fee_applicable_date = models.DateField(null=True, blank=True)
    agreement_signed = models.BooleanField(default=False)
    agreement_signed_date = models.DateField(null=True, blank=True)
    agreement_document = models.FileField(upload_to='lease_agreements/', null=True, blank=True)
    terms_and_conditions = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_leases', db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['status', 'end_date']),
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['unit', 'status']),
        ]

    def __str__(self):
        return f"Lease: {self.unit} - {self.tenant.get_full_name()}"

class PropertyDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('lease_agreement', 'Lease Agreement'),
        ('property_deed', 'Property Deed'),
        ('insurance', 'Insurance'),
        ('tax_document', 'Tax Document'),
        ('utility_bill', 'Utility Bill'),
        ('maintenance_record', 'Maintenance Record'),
        ('inspection_report', 'Inspection Report'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    lease = models.ForeignKey(Lease, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    title = models.CharField(max_length=200)
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to='property_documents/')
    description = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, db_constraint=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['document_type', 'uploaded_at']),
        ]

    def __str__(self):
        return self.title


# ======================================================
# FACILITY MANAGER ASSIGNMENT
# ======================================================

class FacilityManagerAssignment(models.Model):
    """
    Explicit assignment of a Facility Manager to a Township, Building, or Block.

    Replaces the single managed_by FK pattern with a proper many-to-many
    relationship that supports multiple FMs per entity.

    Hierarchy rules:
      township → FM gains access to all buildings/blocks/units within
      building → FM gains access to all blocks/units within
      block    → FM gains access to that block's units only
    """
    SCOPE_CHOICES = [
        ('township', 'Township / Colony'),
        ('building', 'Building'),
        ('block', 'Block / Sector'),
    ]

    facility_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='fm_assignments',
        limit_choices_to={'role': 'facility_manager'},
        db_constraint=False
    )
    scope_type = models.CharField(max_length=10, choices=SCOPE_CHOICES)

    # Exactly one of the following should be populated, matching scope_type
    township = models.ForeignKey(
        Township, null=True, blank=True,
        on_delete=models.CASCADE, related_name='fm_assignments',
    )
    building = models.ForeignKey(
        Building, null=True, blank=True,
        on_delete=models.CASCADE, related_name='fm_assignments',
    )
    block = models.ForeignKey(
        Block, null=True, blank=True,
        on_delete=models.CASCADE, related_name='fm_assignments',
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fm_assignments_given',
        db_constraint=False,
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-assigned_at']
        verbose_name = 'FM Assignment'
        verbose_name_plural = 'FM Assignments'

    def __str__(self):
        if self.scope_type == 'township' and self.township_id:
            target = str(self.township)
        elif self.scope_type == 'building' and self.building_id:
            target = str(self.building)
        elif self.scope_type == 'block' and self.block_id:
            target = str(self.block)
        else:
            target = '—'
        return f"{self.facility_manager} -> {target}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.scope_type == 'township' and not self.township_id:
            raise ValidationError('township is required for township scope.')
        if self.scope_type == 'building' and not self.building_id:
            raise ValidationError('building is required for building scope.')
        if self.scope_type == 'block' and not self.block_id:
            raise ValidationError('block is required for block scope.')