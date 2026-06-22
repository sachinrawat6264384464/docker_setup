# calendar/models.py
from django.db import models
from django.contrib.auth import get_user_model
from properties.models import Building
import uuid

User = get_user_model()

class CalendarAlert(models.Model):
    ALERT_TYPE_CHOICES = [
        ('maintenance', 'Maintenance Work'),
        ('inspection', 'Inspection'),
        ('water_shutdown', 'Water Shutdown'),
        ('power_outage', 'Power Outage'),
        ('elevator_maintenance', 'Elevator Maintenance'),
        ('community', 'Community Event'),
        ('event', 'Community Event'),
        ('meeting', 'Meeting'),
        ('payment_due', 'Payment Due'),
        ('emergency', 'Emergency Alert'),
        ('reminder', 'General Reminder'),
        ('general', 'General Notification'),
        ('other', 'Other'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPE_CHOICES)
    category = models.ForeignKey(
        'support.TicketCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='calendar_alerts',
    )

    
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium', blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    
    affected_area = models.CharField(max_length=200, blank=True, help_text="e.g., Block B, Floors 1-5")
    
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    is_all_day = models.BooleanField(default=False)
    
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='alerts', null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_alerts')
    
    # Notifications
    notify_tenants = models.BooleanField(default=True)
    notification_sent = models.BooleanField(default=False)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_datetime']
        indexes = [
            models.Index(fields=['start_datetime', 'status']),
            models.Index(fields=['building', 'start_datetime']),
        ]

    def __str__(self):
        return self.title


class AlertRecipient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alert = models.ForeignKey(CalendarAlert, on_delete=models.CASCADE, related_name='recipients')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alert_notifications')
    
    notification_sent = models.BooleanField(default=False)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('alert', 'user')

    def __str__(self):
        return f"{self.user.username} - {self.alert.title}"
