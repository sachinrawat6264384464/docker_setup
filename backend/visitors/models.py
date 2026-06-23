# visitors/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import RegexValidator
import uuid
import qrcode
from io import BytesIO
from django.core.files import File

User = get_user_model()


class VisitorType(models.Model):
    """Types of visitors (guest, delivery, contractor, etc.)"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    requires_approval = models.BooleanField(default=True)
    max_duration_hours = models.IntegerField(default=24, help_text="Maximum visit duration in hours")
    color_code = models.CharField(max_length=7, default='#007bff', help_text="Hex color for UI")
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class Visitor(models.Model):
    """Visitor information"""
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
        ('prefer_not_to_say', 'Prefer not to say'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visitor_number = models.CharField(max_length=50, unique=True, editable=False)
    
    # Personal Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$', message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
    phone = models.CharField(validators=[phone_regex], max_length=17)
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True)
    
    # Identification
    id_type = models.CharField(max_length=50, blank=True)  # Driver's License, Passport, etc.
    id_number = models.CharField(max_length=100, blank=True)
    photo = models.ImageField(upload_to='visitors/photos/%Y/%m/', blank=True, null=True)
    
    # Vehicle Information (if applicable)
    vehicle_make = models.CharField(max_length=100, blank=True)
    vehicle_model = models.CharField(max_length=100, blank=True)
    vehicle_color = models.CharField(max_length=50, blank=True)
    vehicle_plate = models.CharField(max_length=20, blank=True)
    
    # Company (for contractors, delivery, etc.)
    company_name = models.CharField(max_length=200, blank=True)
    
    # Blacklist tracking
    is_blacklisted = models.BooleanField(default=False)
    blacklist_reason = models.TextField(blank=True)
    blacklisted_at = models.DateTimeField(null=True, blank=True)
    blacklisted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='blacklisted_visitors', db_constraint=False)
    
    # Timestamps
    first_visit = models.DateTimeField(auto_now_add=True)
    last_visit = models.DateTimeField(auto_now=True)
    visit_count = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-last_visit']
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['email']),
            models.Index(fields=['-last_visit']),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.visitor_number})"
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def save(self, *args, **kwargs):
        if not self.visitor_number:
            from datetime import datetime
            year_month = datetime.now().strftime('%Y%m')
            last_visitor = Visitor.objects.filter(
                visitor_number__startswith=f'VIS-{year_month}'
            ).order_by('-visitor_number').first()
            
            if last_visitor:
                last_number = int(last_visitor.visitor_number.split('-')[-1])
                new_number = last_number + 1
            else:
                new_number = 1
            
            self.visitor_number = f'VIS-{year_month}-{new_number:05d}'
        
        super().save(*args, **kwargs)


class VisitorPass(models.Model):
    """Visitor pass for entry/exit"""
    PASS_STATUS = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pass_number = models.CharField(max_length=50, unique=True, editable=False)
    
    # Visitor and Host
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='passes')
    visitor_type = models.ForeignKey(VisitorType, on_delete=models.PROTECT)
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name='visitor_passes', db_constraint=False)
    
    # Visit Details
    purpose = models.TextField()
    building = models.CharField(max_length=100)
    unit_number = models.CharField(max_length=20)
    
    # Timing
    expected_arrival = models.DateTimeField()
    expected_departure = models.DateTimeField()
    actual_arrival = models.DateTimeField(null=True, blank=True)
    actual_departure = models.DateTimeField(null=True, blank=True)
    
    # Approval
    status = models.CharField(max_length=20, choices=PASS_STATUS, default='pending')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_passes', db_constraint=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rejected_passes', db_constraint=False)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    # QR Code for entry
    qr_code = models.ImageField(upload_to='visitors/qr_codes/', blank=True, null=True)
    access_code = models.CharField(max_length=10, unique=True, editable=False)
    
    # Security Notes
    security_notes = models.TextField(blank=True)
    
    # Special permissions
    can_drive_in = models.BooleanField(default=False)
    requires_escort = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['expected_arrival']),
            models.Index(fields=['host']),
            models.Index(fields=['host', 'status']),
            models.Index(fields=['visitor', 'created_at']),
            models.Index(fields=['status', 'expected_arrival']),
        ]
    
    def __str__(self):
        return f"{self.pass_number} - {self.visitor.get_full_name()}"
    
    def save(self, *args, **kwargs):
        if not self.pass_number:
            from datetime import datetime
            year_month = datetime.now().strftime('%Y%m')
            last_pass = VisitorPass.objects.filter(
                pass_number__startswith=f'PASS-{year_month}'
            ).order_by('-pass_number').first()
            
            if last_pass:
                last_number = int(last_pass.pass_number.split('-')[-1])
                new_number = last_number + 1
            else:
                new_number = 1
            
            self.pass_number = f'PASS-{year_month}-{new_number:05d}'
        
        if not self.access_code:
            import random
            import string
            self.access_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        super().save(*args, **kwargs)
        
        # Generate QR code if approved
        if self.status == 'approved' and not self.qr_code:
            self.generate_qr_code()
    
    def generate_qr_code(self):
        """Generate QR code for visitor pass"""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr_data = f"VISITOR_PASS:{self.pass_number}:{self.access_code}"
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        
        filename = f'qr_{self.pass_number}.png'
        self.qr_code.save(filename, File(buffer), save=False)
        self.save(update_fields=['qr_code'])
    
    def check_in(self):
        """Check in the visitor"""
        self.actual_arrival = timezone.now()
        self.status = 'active'
        self.save()
        
        # Update visitor count
        self.visitor.visit_count += 1
        self.visitor.save()
    
    def check_out(self):
        """Check out the visitor"""
        self.actual_departure = timezone.now()
        self.status = 'completed'
        self.save()
    
    def is_expired(self):
        """Check if pass is expired"""
        return timezone.now() > self.expected_departure


class VisitorLog(models.Model):
    """Log of visitor check-in/check-out"""
    LOG_TYPES = [
        ('check_in', 'Check In'),
        ('check_out', 'Check Out'),
        ('denied_entry', 'Denied Entry'),
        ('alert', 'Security Alert'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visitor_pass = models.ForeignKey(VisitorPass, on_delete=models.CASCADE, related_name='logs')
    log_type = models.CharField(max_length=20, choices=LOG_TYPES)
    
    # Who performed the action
    security_staff = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='visitor_logs', db_constraint=False)
    
    # Location
    gate_number = models.CharField(max_length=50, blank=True)
    entry_point = models.CharField(max_length=100, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Temperature check (COVID-19 or health screening)
    temperature = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    health_screening_passed = models.BooleanField(default=True)
    
    # Photos
    entry_photo = models.ImageField(upload_to='visitors/entry_photos/%Y/%m/', blank=True, null=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['log_type']),
        ]
    
    def __str__(self):
        return f"{self.log_type} - {self.visitor_pass.visitor.get_full_name()} at {self.timestamp}"


class BlacklistedVisitor(models.Model):
    """Blacklisted visitors who should not be allowed entry"""
    visitor = models.OneToOneField(Visitor, on_delete=models.CASCADE, related_name='blacklist_record')
    reason = models.TextField()
    
    blacklisted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='blacklist_actions', db_constraint=False)
    blacklisted_at = models.DateTimeField(auto_now_add=True)
    
    is_permanent = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-blacklisted_at']
    
    def __str__(self):
        return f"Blacklisted: {self.visitor.get_full_name()}"
    
    def is_active(self):
        """Check if blacklist is still active"""
        if self.is_permanent:
            return True
        if self.expires_at:
            return timezone.now() < self.expires_at
        return True


class VisitorFeedback(models.Model):
    """Feedback from visitors about their experience"""
    RATING_CHOICES = [
        (1, '1 - Very Poor'),
        (2, '2 - Poor'),
        (3, '3 - Average'),
        (4, '4 - Good'),
        (5, '5 - Excellent'),
    ]
    
    visitor_pass = models.OneToOneField(VisitorPass, on_delete=models.CASCADE, related_name='feedback')
    rating = models.IntegerField(choices=RATING_CHOICES)
    comments = models.TextField(blank=True)
    
    # Specific ratings
    security_staff_rating = models.IntegerField(choices=RATING_CHOICES, null=True, blank=True)
    process_ease_rating = models.IntegerField(choices=RATING_CHOICES, null=True, blank=True)
    
    would_recommend = models.BooleanField(default=True)
    
    submitted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-submitted_at']
    
    def __str__(self):
        return f"Feedback from {self.visitor_pass.visitor.get_full_name()} - {self.rating}/5"
