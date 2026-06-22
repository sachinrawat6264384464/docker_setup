# inspections/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()


class InspectionTemplate(models.Model):
    INSPECTION_TYPES = [
        ('move_in', 'Move-In'),
        ('move_out', 'Move-Out'),
        ('routine', 'Routine'),
        ('safety', 'Safety'),
        ('pest_control', 'Pest Control'),
        ('maintenance', 'Maintenance'),
        ('custom', 'Custom'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    inspection_type = models.CharField(max_length=50, choices=INSPECTION_TYPES)
    description = models.TextField(blank=True)
    checklist_items = models.JSONField(
        default=list,
        help_text='List of {"label": "...", "required": true/false, "category": "..."} items',
    )
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='inspection_templates_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['inspection_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_inspection_type_display()})"


class Inspection(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    RESULT_CHOICES = [
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('partial', 'Partial Pass'),
        ('pending', 'Pending Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inspection_number = models.CharField(max_length=20, unique=True, blank=True)
    template = models.ForeignKey(
        InspectionTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inspections',
    )

    # What is being inspected
    inspection_type = models.CharField(max_length=50, choices=InspectionTemplate.INSPECTION_TYPES)
    unit_id = models.UUIDField(null=True, blank=True)
    building_id = models.UUIDField(null=True, blank=True)
    location_description = models.CharField(max_length=500, blank=True)

    # Schedule
    scheduled_date = models.DateTimeField()
    completed_date = models.DateTimeField(null=True, blank=True)

    # People
    inspector = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='inspections_assigned',
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inspections_requested',
    )

    # Results
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    result = models.CharField(max_length=20, choices=RESULT_CHOICES, default='pending')
    checklist_results = models.JSONField(
        default=list,
        help_text='List of {"item": "...", "status": "pass/fail/na", "notes": "...", "photo": "..."} entries',
    )
    overall_notes = models.TextField(blank=True)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Follow-up
    follow_up_required = models.BooleanField(default=False)
    follow_up_notes = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_date']
        indexes = [
            models.Index(fields=['status', '-scheduled_date']),
            models.Index(fields=['inspector', 'status']),
            models.Index(fields=['unit_id']),
        ]

    def __str__(self):
        return f"{self.inspection_number} - {self.get_inspection_type_display()}"

    def save(self, *args, **kwargs):
        if not self.inspection_number:
            self.inspection_number = self._generate_inspection_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_inspection_number():
        from django.utils.crypto import get_random_string
        return f"INS-{timezone.now().strftime('%Y%m')}-{get_random_string(5, '0123456789')}"


class InspectionPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='inspections/photos/%Y/%m/')
    caption = models.CharField(max_length=300, blank=True)
    checklist_item_index = models.IntegerField(null=True, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Photo for {self.inspection.inspection_number}"
