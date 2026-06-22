# maintenance/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid

User = get_user_model()


class MaintenanceRequest(models.Model):
    PRIORITY_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    CATEGORY_CHOICES = [
        ('plumbing', 'Plumbing'),
        ('electrical', 'Electrical'),
        ('hvac', 'HVAC'),
        ('appliance', 'Appliance'),
        ('carpentry', 'Carpentry'),
        ('painting', 'Painting'),
        ('flooring', 'Flooring'),
        ('pest_control', 'Pest Control'),
        ('cleaning', 'Cleaning'),
        ('security', 'Security System'),
        ('elevator', 'Elevator'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('acknowledged', 'Acknowledged'),
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    REQUEST_TYPE_CHOICES = [
        ('common', 'Common Area'),
        ('personal', 'Personal Unit'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_number = models.CharField(max_length=50, unique=True)
    
    # Request Details
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES, default='personal')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    priority = models.CharField(max_length=20, choices=PRIORITY_LEVELS, default='medium')
    title = models.CharField(max_length=300)
    description = models.TextField()
    
    # Location
    building = models.CharField(max_length=200)
    unit_number = models.CharField(max_length=50)
    specific_location = models.CharField(max_length=300, blank=True)
    unit = models.ForeignKey(
        'properties.Unit',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='maintenance_requests',
    )
    lease = models.ForeignKey(
        'properties.Lease',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='maintenance_requests',
    )
    
    # Requester
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='maintenance_requests', db_constraint=False)
    contact_phone = models.CharField(max_length=20, blank=True)
    tenant_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tenant_maintenance_requests',
        db_constraint=False
    )
    owner_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='owned_maintenance_requests',
        db_constraint=False
    )
    owner_email = models.EmailField(blank=True, default='')
    
    # Status & Assignment
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_maintenance', db_constraint=False)
    
    # Timeline
    requested_date = models.DateTimeField(auto_now_add=True)
    acknowledged_date = models.DateTimeField(null=True, blank=True)
    assigned_date = models.DateTimeField(null=True, blank=True)
    started_date = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    
    # Access
    preferred_date = models.DateField(null=True, blank=True)
    preferred_time = models.TimeField(null=True, blank=True)
    access_instructions = models.TextField(blank=True)
    is_occupied = models.BooleanField(default=True)
    
    # Work Details
    work_performed = models.TextField(blank=True)
    parts_used = models.JSONField(default=list, blank=True)
    parts_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    labor_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_chargeable = models.BooleanField(default=False)
    invoiced = models.BooleanField(default=False)
    
    # Media
    photos_before = models.JSONField(default=list, blank=True)
    photos_after = models.JSONField(default=list, blank=True)
    
    # Feedback
    rating = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    feedback = models.TextField(blank=True)
    feedback_date = models.DateTimeField(null=True, blank=True)
    
    # Notes
    admin_notes = models.TextField(blank=True)
    technician_notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['request_number']),
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['category']),
            models.Index(fields=['requested_by', 'created_at']),
            models.Index(fields=['assigned_to', 'status']),
        ]

    def __str__(self):
        return f"{self.request_number} - {self.title}"
    
    def save(self, *args, **kwargs):
        if not self.request_number:
            self.request_number = self._generate_request_number()
        super().save(*args, **kwargs)
    
    def _generate_request_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        count = MaintenanceRequest.objects.filter(
            request_number__startswith=f'MNT-{date_str}'
        ).count() + 1
        return f'MNT-{date_str}-{count:04d}'

    def get_unit_history(self):
        """
        Get previous maintenance incidents for the same unit and category.
        This helps identify recurring issues (e.g., plumbing issue last year).
        """
        if not self.unit:
            return MaintenanceRequest.objects.none()
            
        return MaintenanceRequest.objects.filter(
            unit=self.unit,
            category=self.category
        ).exclude(id=self.id).order_by('-created_at')

    def update_vendor_performance(self):
        """
        Update vendor statistics when a task is completed and rated.
        """
        if self.status == 'completed' and self.assigned_to and hasattr(self.assigned_to, 'vendor_profile'):
            vendor = self.assigned_to.vendor_profile
            # Calculate new average rating
            completed_tasks = MaintenanceRequest.objects.filter(
                assigned_to=self.assigned_to,
                status='completed',
                rating__isnull=False
            )
            
            total_rating = sum([t.rating for t in completed_tasks])
            count = completed_tasks.count()
            
            if count > 0:
                vendor.rating = total_rating / count
                vendor.total_jobs = count
                vendor.save()

    def populate_from_user(self, user):
        """Auto-populate building and unit from user profile"""
        if hasattr(user, 'building_name') and user.building_name:
            self.building = user.building_name
        if hasattr(user, 'unit_number') and user.unit_number:
            self.unit_number = user.unit_number
        if hasattr(user, 'phone') and user.phone:
            self.contact_phone = user.phone


class MaintenanceSchedule(models.Model):
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', 'Semi-annual'),
        ('annual', 'Annual'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    title = models.CharField(max_length=300)
    description = models.TextField()
    category = models.CharField(max_length=50, choices=MaintenanceRequest.CATEGORY_CHOICES)
    
    frequency = models.CharField(max_length=50, choices=FREQUENCY_CHOICES)
    
    # Location
    building = models.CharField(max_length=200, blank=True)
    area = models.CharField(max_length=300)
    
    # Assignment
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False)
    
    # Schedule
    next_due_date = models.DateField()
    last_completed = models.DateField(null=True, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Checklist
    checklist_items = models.JSONField(default=list, blank=True)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['next_due_date']

    def __str__(self):
        return f"{self.title} - {self.frequency}"


class Vendor(models.Model):
    SERVICE_TYPES = [
        ('plumbing', 'Plumbing'),
        ('electrical', 'Electrical'),
        ('hvac', 'HVAC'),
        ('pest_control', 'Pest Control'),
        ('cleaning', 'Cleaning'),
        ('landscaping', 'Landscaping'),
        ('security', 'Security'),
        ('elevator', 'Elevator Maintenance'),
        ('general', 'General Maintenance'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    name = models.CharField(max_length=200)
    service_type = models.CharField(max_length=50, choices=SERVICE_TYPES)
    
    # Contact
    contact_person = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    address = models.TextField()
    
    # Business Details
    license_number = models.CharField(max_length=100, blank=True)
    insurance_number = models.CharField(max_length=100, blank=True)
    
    # Performance
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00, validators=[MinValueValidator(0), MaxValueValidator(5)])
    total_jobs = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.get_service_type_display()}"