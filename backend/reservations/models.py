# reservations/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()


class ReservableResource(models.Model):
    RESOURCE_TYPES = [
        ('facility', 'Facility'),
        ('room', 'Meeting Room'),
        ('equipment', 'Equipment'),
        ('space', 'Common Space'),
        ('vehicle', 'Vehicle'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    resource_type = models.CharField(max_length=50, choices=RESOURCE_TYPES)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=300, blank=True)
    capacity = models.IntegerField(null=True, blank=True)
    image = models.ImageField(upload_to='reservations/resources/', blank=True)

    # Availability
    is_available = models.BooleanField(default=True)
    available_from = models.TimeField(default='06:00')
    available_until = models.TimeField(default='22:00')
    available_days = models.JSONField(
        default=list,
        blank=True,
        help_text='List of weekday numbers (0=Mon, 6=Sun). Empty = every day.',
    )
    max_duration_hours = models.DecimalField(max_digits=5, decimal_places=1, default=4.0)
    min_advance_hours = models.IntegerField(default=1)
    max_advance_days = models.IntegerField(default=30)

    # Pricing
    is_free = models.BooleanField(default=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Rules
    requires_approval = models.BooleanField(default=False)
    rules = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['resource_type', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_resource_type_display()})"


class Reservation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('checked_in', 'Checked In'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation_number = models.CharField(max_length=20, unique=True, blank=True)
    resource = models.ForeignKey(
        ReservableResource, on_delete=models.CASCADE, related_name='reservations',
    )

    # Time slot
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    # People
    reserved_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='reservations',
    )
    guest_count = models.IntegerField(default=1)
    guest_names = models.JSONField(default=list, blank=True)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    purpose = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # Approval
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reservations_approved',
    )
    rejection_reason = models.TextField(blank=True)

    # Pricing
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_paid = models.BooleanField(default=False)

    # Check-in/out
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)

    # Cancellation
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=['resource', 'start_time', 'end_time']),
            models.Index(fields=['reserved_by', '-created_at']),
            models.Index(fields=['status', '-start_time']),
        ]

    def __str__(self):
        return f"{self.reservation_number} - {self.resource.name}"

    def save(self, *args, **kwargs):
        if not self.reservation_number:
            self.reservation_number = self._generate_reservation_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reservation_number():
        from django.utils.crypto import get_random_string
        return f"RSV-{timezone.now().strftime('%Y%m')}-{get_random_string(5, '0123456789')}"

    def has_conflict(self):
        """Check if this reservation conflicts with existing approved ones."""
        return Reservation.objects.filter(
            resource=self.resource,
            status__in=['approved', 'checked_in'],
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(pk=self.pk).exists()
