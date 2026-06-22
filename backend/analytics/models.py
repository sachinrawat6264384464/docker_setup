import uuid
from django.db import models
from django.conf import settings


EVENT_TYPES = [
    # Auth / User
    ('user_logged_in', 'User Logged In'),
    ('user_logged_out', 'User Logged Out'),
    ('user_login_failed', 'User Login Failed'),
    ('user_registered', 'User Registered'),
    ('user_profile_updated', 'User Profile Updated'),
    ('password_changed', 'Password Changed'),
    ('2fa_enabled', '2FA Enabled'),

    # Payments / Invoices
    ('invoice_created', 'Invoice Created'),
    ('invoice_paid', 'Invoice Paid'),
    ('invoice_overdue', 'Invoice Overdue'),
    ('invoice_failed', 'Invoice Failed'),
    ('payment_plan_created', 'Payment Plan Created'),
    ('autopay_enabled', 'AutoPay Enabled'),
    ('autopay_disabled', 'AutoPay Disabled'),
    ('subscription_created', 'Subscription Created'),
    ('subscription_upgraded', 'Subscription Upgraded'),
    ('subscription_cancelled', 'Subscription Cancelled'),

    # Maintenance
    ('maintenance_request_created', 'Maintenance Request Created'),
    ('maintenance_assigned', 'Maintenance Assigned'),
    ('maintenance_status_changed', 'Maintenance Status Changed'),
    ('maintenance_resolved', 'Maintenance Resolved'),
    ('maintenance_rated', 'Maintenance Rated'),

    # Amenities
    ('amenity_booked', 'Amenity Booked'),
    ('amenity_booking_cancelled', 'Amenity Booking Cancelled'),
    ('amenity_booking_approved', 'Amenity Booking Approved'),
    ('amenity_reviewed', 'Amenity Reviewed'),

    # Communication
    ('message_sent', 'Message Sent'),
    ('announcement_published', 'Announcement Published'),
    ('announcement_viewed', 'Announcement Viewed'),
    ('email_campaign_sent', 'Email Campaign Sent'),
    ('email_opened', 'Email Opened'),
    ('email_clicked', 'Email Clicked'),
    ('sms_sent', 'SMS Sent'),
    ('sms_delivered', 'SMS Delivered'),
    ('sms_failed', 'SMS Failed'),

    # Support
    ('ticket_created', 'Ticket Created'),
    ('ticket_assigned', 'Ticket Assigned'),
    ('ticket_status_changed', 'Ticket Status Changed'),
    ('ticket_resolved', 'Ticket Resolved'),
    ('ticket_rated', 'Ticket Rated'),

    # Visitors
    ('visitor_preregistered', 'Visitor Pre-Registered'),
    ('visitor_checked_in', 'Visitor Checked In'),
    ('visitor_checked_out', 'Visitor Checked Out'),

    # Documents
    ('document_uploaded', 'Document Uploaded'),
    ('document_downloaded', 'Document Downloaded'),
    ('document_deleted', 'Document Deleted'),

    # Security
    ('incident_reported', 'Incident Reported'),
    ('access_denied', 'Access Denied'),
    ('emergency_alert_sent', 'Emergency Alert Sent'),

    # Accounting & Reconciliation
    ('accounting_sync_completed', 'Accounting Sync Completed'),
    ('accounting_sync_failed', 'Accounting Sync Failed'),
    ('reconciliation_started', 'Reconciliation Started'),
    ('reconciliation_completed', 'Reconciliation Completed'),

    # Mobile
    ('app_session_started', 'App Session Started'),
    ('app_session_ended', 'App Session Ended'),
    ('push_notification_received', 'Push Notification Received'),
    ('push_notification_tapped', 'Push Notification Tapped'),
]

DEVICE_TYPES = [
    ('web', 'Web Browser'),
    ('ios', 'iOS App'),
    ('android', 'Android App'),
    ('api', 'API Client'),
    ('other', 'Other'),
]


class AnalyticsEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=60, choices=EVENT_TYPES, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='analytics_events',
    )
    tenant_schema = models.CharField(max_length=100, db_index=True)
    object_type = models.CharField(max_length=100, blank=True, default='')
    object_id = models.CharField(max_length=255, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_type = models.CharField(max_length=20, choices=DEVICE_TYPES, default='web')
    user_agent = models.TextField(blank=True, default='')
    session_id = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Analytics Event'
        verbose_name_plural = 'Analytics Events'

    def __str__(self):
        return f'{self.event_type} | {self.tenant_schema} | {self.created_at}'


class DailyMetricSnapshot(models.Model):
    tenant_schema = models.CharField(max_length=100, db_index=True)
    date = models.DateField(db_index=True)
    metric_key = models.CharField(max_length=100)
    metric_value = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['tenant_schema', 'date', 'metric_key']
        ordering = ['-date', 'tenant_schema', 'metric_key']
        verbose_name = 'Daily Metric Snapshot'
        verbose_name_plural = 'Daily Metric Snapshots'

    def __str__(self):
        return f'{self.tenant_schema} | {self.date} | {self.metric_key}={self.metric_value}'
