# vendors/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid

User = get_user_model()


class VendorCategory(models.Model):
    """Categories of vendor services"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="Icon class or name")
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Vendor Categories'
    
    def __str__(self):
        return self.name


class Vendor(models.Model):
    """Vendor/Contractor information"""
    VENDOR_TYPES = [
        ('individual', 'Individual Contractor'),
        ('company', 'Company'),
        ('agency', 'Agency'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
        ('blacklisted', 'Blacklisted'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_number = models.CharField(max_length=50, unique=True, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendor_profile',
        db_constraint=False,
        help_text='Authenticated user account for the vendor portal'
    )
    
    # Basic Information
    company_name = models.CharField(max_length=200)
    vendor_type = models.CharField(max_length=20, choices=VENDOR_TYPES, default='company')
    categories = models.ManyToManyField(VendorCategory, related_name='vendors')
    
    # Contact Information
    contact_person = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    alternate_phone = models.CharField(max_length=20, blank=True)
    website = models.URLField(blank=True)
    
    # Address
    address_line1 = models.CharField(max_length=200)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    district = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='USA')
    
    # Business Details
    tax_id = models.CharField(max_length=50, blank=True, help_text="Tax ID / EIN")
    license_number = models.CharField(max_length=100, blank=True)
    license_expiry = models.DateField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    is_preferred = models.BooleanField(default=False, help_text="Preferred vendor")
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_vendors', db_constraint=False)
    
    # Ratings
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    total_reviews = models.IntegerField(default=0)
    total_jobs = models.IntegerField(default=0)
    
    # Financial
    payment_terms = models.CharField(max_length=200, blank=True, help_text="e.g., Net 30")
    contract_start_date = models.DateField(null=True, blank=True)
    contract_end_date = models.DateField(null=True, blank=True)
    contract_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Documents
    w9_form = models.FileField(upload_to='vendors/w9/', blank=True, null=True)
    
    # Notes
    notes = models.TextField(blank=True)

    # Portal preferences
    availability_preferences = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_job_date = models.DateField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['is_preferred']),
            models.Index(fields=['-average_rating']),
            models.Index(fields=['status', 'company_name']),
            models.Index(fields=['vendor_type']),
        ]

    def __str__(self):
        return f"{self.vendor_number} - {self.company_name}"
    
    def save(self, *args, **kwargs):
        if not self.vendor_number:
            from datetime import datetime
            year_month = datetime.now().strftime('%Y%m')
            last_vendor = Vendor.objects.filter(
                vendor_number__startswith=f'VEN-{year_month}'
            ).order_by('-vendor_number').first()
            
            if last_vendor:
                last_number = int(last_vendor.vendor_number.split('-')[-1])
                new_number = last_number + 1
            else:
                new_number = 1
            
            self.vendor_number = f'VEN-{year_month}-{new_number:05d}'
        
        super().save(*args, **kwargs)

    def update_ratings(self):
        """Recalculate aggregate rating fields from related reviews."""
        from django.db.models import Avg

        summary = self.reviews.aggregate(avg=Avg('overall_rating'))
        self.average_rating = round(summary.get('avg') or 0, 2)
        self.total_reviews = self.reviews.count()
        self.save(update_fields=['average_rating', 'total_reviews'])


class VendorService(models.Model):
    """Services offered by a vendor"""
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='services')
    category = models.ForeignKey(VendorCategory, on_delete=models.PROTECT)
    
    service_name = models.CharField(max_length=200)
    description = models.TextField()
    
    # Pricing
    pricing_type = models.CharField(
        max_length=20,
        choices=[
            ('hourly', 'Hourly Rate'),
            ('fixed', 'Fixed Price'),
            ('per_unit', 'Per Unit'),
            ('custom', 'Custom Quote'),
        ],
        default='hourly'
    )
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Availability
    is_active = models.BooleanField(default=True)
    min_notice_hours = models.IntegerField(default=24, help_text="Minimum notice required in hours")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['service_name']
    
    def __str__(self):
        return f"{self.vendor.company_name} - {self.service_name}"


class VendorContract(models.Model):
    """Contracts with vendors"""
    CONTRACT_TYPES = [
        ('one_time', 'One Time'),
        ('annual', 'Annual'),
        ('project', 'Project Based'),
        ('ongoing', 'Ongoing'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('terminated', 'Terminated'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract_number = models.CharField(max_length=50, unique=True, editable=False)
    
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='contracts')
    contract_type = models.CharField(max_length=20, choices=CONTRACT_TYPES, default='one_time')
    
    # Details
    title = models.CharField(max_length=200)
    description = models.TextField()
    scope_of_work = models.TextField()
    
    # Financial
    contract_value = models.DecimalField(max_digits=12, decimal_places=2)
    payment_schedule = models.TextField(help_text="Description of payment terms")
    
    # Dates
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Documents
    contract_document = models.FileField(upload_to='vendors/contracts/%Y/', blank=True, null=True)
    signed_document = models.FileField(upload_to='vendors/contracts/signed/%Y/', blank=True, null=True)
    
    # Signatures
    signed_by_vendor = models.BooleanField(default=False)
    signed_by_management = models.BooleanField(default=False)
    vendor_signature_date = models.DateTimeField(null=True, blank=True)
    management_signature_date = models.DateTimeField(null=True, blank=True)
    
    # Management
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_contracts', db_constraint=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['vendor', 'status']),
            models.Index(fields=['end_date']),
        ]

    def __str__(self):
        return f"{self.contract_number} - {self.vendor.company_name}"
    
    def save(self, *args, **kwargs):
        if not self.contract_number:
            from datetime import datetime
            year = datetime.now().strftime('%Y')
            last_contract = VendorContract.objects.filter(
                contract_number__startswith=f'VCTR-{year}'
            ).order_by('-contract_number').first()
            
            if last_contract:
                last_number = int(last_contract.contract_number.split('-')[-1])
                new_number = last_number + 1
            else:
                new_number = 1
            
            self.contract_number = f'VCTR-{year}-{new_number:05d}'
        
        super().save(*args, **kwargs)


class VendorReview(models.Model):
    """Reviews and ratings for vendors"""
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='reviews')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='vendor_reviews', db_constraint=False)
    
    # Ratings (1-5 stars)
    overall_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    quality_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    timeliness_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    professionalism_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    value_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    
    # Review
    title = models.CharField(max_length=200)
    comment = models.TextField()
    
    # Work Order reference
    work_order_id = models.UUIDField(null=True, blank=True, help_text="Related work order ID")
    
    # Status
    is_verified = models.BooleanField(default=False)
    would_recommend = models.BooleanField(default=True)
    
    # Vendor response
    vendor_response = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Review for {self.vendor.company_name} - {self.overall_rating}/5"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update vendor's average rating
        self.vendor.update_ratings()


class VendorPayment(models.Model):
    """Payment tracking for vendor services"""
    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_number = models.CharField(max_length=50, unique=True, editable=False)
    
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='payments')
    contract = models.ForeignKey(VendorContract, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    
    # Payment Details
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField()
    invoice_number = models.CharField(max_length=100, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    due_date = models.DateField()
    paid_date = models.DateField(null=True, blank=True)
    
    # Documents
    invoice_document = models.FileField(upload_to='vendors/invoices/%Y/', blank=True, null=True)
    payment_receipt = models.FileField(upload_to='vendors/receipts/%Y/', blank=True, null=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Management
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_vendor_payments', db_constraint=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_vendor_payments', db_constraint=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.payment_number} - {self.vendor.company_name} - ₹{self.amount}"
    
    def save(self, *args, **kwargs):
        if not self.payment_number:
            from datetime import datetime
            year_month = datetime.now().strftime('%Y%m')
            last_payment = VendorPayment.objects.filter(
                payment_number__startswith=f'VPAY-{year_month}'
            ).order_by('-payment_number').first()
            
            if last_payment:
                last_number = int(last_payment.payment_number.split('-')[-1])
                new_number = last_number + 1
            else:
                new_number = 1
            
            self.payment_number = f'VPAY-{year_month}-{new_number:05d}'
        
        super().save(*args, **kwargs)


class VendorInsurance(models.Model):
    """Insurance certificates for vendors"""
    INSURANCE_TYPES = [
        ('general_liability', 'General Liability'),
        ('workers_comp', 'Workers Compensation'),
        ('professional_liability', 'Professional Liability'),
        ('commercial_auto', 'Commercial Auto'),
    ]
    
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='insurance_policies')
    insurance_type = models.CharField(max_length=50, choices=INSURANCE_TYPES)
    
    policy_number = models.CharField(max_length=100)
    insurance_company = models.CharField(max_length=200)
    coverage_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    effective_date = models.DateField()
    expiry_date = models.DateField()
    
    certificate_document = models.FileField(upload_to='vendors/insurance/')
    
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-expiry_date']
    
    def __str__(self):
        return f"{self.vendor.company_name} - {self.get_insurance_type_display()}"
    
    def is_expired(self):
        return timezone.now().date() > self.expiry_date
