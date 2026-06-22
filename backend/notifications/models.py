# notifications/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('system', 'System'),
        ('payment', 'Payment'),
        ('maintenance', 'Maintenance'),
        ('security', 'Security'),
        ('amenity', 'Amenity'),
        ('parking', 'Parking'),
        ('rental', 'Rental/Lease'),
        ('announcement', 'Announcement'),
        ('reminder', 'Reminder'),
        ('alert', 'Alert'),
        ('message', 'Message'),
    ]
    
    PRIORITY_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    priority = models.CharField(max_length=20, choices=PRIORITY_LEVELS, default='medium')
    
    title = models.CharField(max_length=300)
    message = models.TextField()
    
    # Delivery Channels
    send_email = models.BooleanField(default=True)
    send_sms = models.BooleanField(default=False)
    send_push = models.BooleanField(default=True)
    send_in_app = models.BooleanField(default=True)
    
    # Status
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    # Related Objects
    related_object_type = models.CharField(max_length=100, blank=True)
    related_object_id = models.UUIDField(null=True, blank=True)
    action_url = models.CharField(max_length=500, blank=True)
    
    # Scheduling
    scheduled_for = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Delivery Status
    email_sent = models.BooleanField(default=False)
    sms_sent = models.BooleanField(default=False)
    push_sent = models.BooleanField(default=False)
    
    # Additional Data
    data = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['notification_type', 'created_at']),
        ]

    def __str__(self):
        return f"{self.title} - {self.recipient.get_full_name()}"
    
    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()


class NotificationPreference(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preference'
    )

    # Email Preferences
    email_enabled = models.BooleanField(default=True)
    email_payment = models.BooleanField(default=True)
    email_maintenance = models.BooleanField(default=True)
    email_security = models.BooleanField(default=True)
    email_amenity = models.BooleanField(default=True)
    email_announcements = models.BooleanField(default=True)

    # SMS Preferences
    sms_enabled = models.BooleanField(default=False)
    sms_payment = models.BooleanField(default=False)
    sms_maintenance = models.BooleanField(default=False)
    sms_security = models.BooleanField(default=True)
    sms_amenity = models.BooleanField(default=False)

    # Push Preferences
    push_enabled = models.BooleanField(default=True)
    push_payment = models.BooleanField(default=True)
    push_maintenance = models.BooleanField(default=True)
    push_security = models.BooleanField(default=True)
    push_amenity = models.BooleanField(default=True)
    push_announcements = models.BooleanField(default=True)

    # Quiet Hours
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)



class Announcement(models.Model):
    AUDIENCE_CHOICES = [
        ('all', 'All Residents'),
        ('building', 'Specific Building'),
        ('unit_type', 'Specific Unit Type'),
        ('custom', 'Custom Selection'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    title = models.CharField(max_length=300)
    content = models.TextField()
    
    # Targeting
    audience_type = models.CharField(max_length=50, choices=AUDIENCE_CHOICES, default='all')
    target_buildings = models.JSONField(default=list, blank=True)
    target_units = models.JSONField(default=list, blank=True)
    
    # Delivery
    send_email = models.BooleanField(default=True)
    send_sms = models.BooleanField(default=False)
    send_push = models.BooleanField(default=True)
    
    # Publishing
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Attachments
    attachments = models.JSONField(default=list, blank=True)
    
    # Statistics
    sent_count = models.IntegerField(default=0)
    read_count = models.IntegerField(default=0)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='announcements_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class EmailTemplate(models.Model):
    CATEGORY_CHOICES = [
        ('transactional', 'Transactional'),
        ('marketing', 'Marketing'),
        ('system', 'System'),
    ]
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    subject = models.CharField(max_length=300)
    html_body = models.TextField()
    plain_body = models.TextField(blank=True)
    variables_list = models.JSONField(default=list)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='transactional')
    is_active = models.BooleanField(default=True)
    last_modified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='modified_email_templates'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class EmailLog(models.Model):
    STATUS_CHOICES = [
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('opened', 'Opened'),
        ('clicked', 'Clicked'),
        ('bounced', 'Bounced'),
        ('failed', 'Failed'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        EmailTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='logs'
    )
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=300)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='sent')
    sendgrid_message_id = models.CharField(max_length=200, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    bounced_at = models.DateTimeField(null=True, blank=True)
    tenant_schema = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient_email} - {self.subject} ({self.status})"


class UnsubscribeRecord(models.Model):
    email = models.EmailField()
    category = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['email', 'category']

    def __str__(self):
        return f"{self.email} - {self.category}"


class EmailCampaign(models.Model):
    SEGMENT_CHOICES = [
        ('all', 'All Residents'),
        ('active', 'Active Rentals'),
        ('overdue', 'Overdue Payments'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.CharField(max_length=300)
    from_name = models.CharField(max_length=100, blank=True)
    body = models.TextField()
    recipient_segment = models.CharField(max_length=50, choices=SEGMENT_CHOICES, default='all')
    
    # Status
    status = models.CharField(max_length=20, default='sent')
    sent_count = models.IntegerField(default=0)
    open_count = models.IntegerField(default=0)
    click_count = models.IntegerField(default=0)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='email_campaigns_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.subject


class SMSAlert(models.Model):
    GROUP_CHOICES = [
        ('all', 'All Residents'),
        ('emergency', 'Emergency Only'),
        ('overdue', 'Overdue Payments'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.TextField()
    recipient_group = models.CharField(max_length=50, choices=GROUP_CHOICES, default='all')
    
    # Status
    status = models.CharField(max_length=20, default='sent')
    sent_count = models.IntegerField(default=0)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sms_alerts_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"SMS to {self.recipient_group} at {self.created_at}"