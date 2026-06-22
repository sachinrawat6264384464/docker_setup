# security/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid

User = get_user_model()


class SecurityGuard(models.Model):
    """Security personnel managing the property"""
    SHIFT_CHOICES = [
        ('morning', 'Morning (6 AM - 2 PM)'),
        ('afternoon', 'Afternoon (2 PM - 10 PM)'),
        ('night', 'Night (10 PM - 6 AM)'),
        ('rotating', 'Rotating Shifts'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('on_leave', 'On Leave'),
        ('suspended', 'Suspended'),
        ('terminated', 'Terminated'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='security_profile', db_constraint=False)
    employee_id = models.CharField(max_length=50, unique=True)
    shift = models.CharField(max_length=20, choices=SHIFT_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Personal Information
    date_of_birth = models.DateField()
    blood_group = models.CharField(max_length=5, blank=True)
    emergency_contact_name = models.CharField(max_length=200)
    emergency_contact_phone = models.CharField(max_length=20)
    
    # Professional Information
    joining_date = models.DateField()
    last_working_date = models.DateField(null=True, blank=True)
    license_number = models.CharField(max_length=100)
    license_expiry = models.DateField()
    training_completed = models.JSONField(default=list, blank=True)
    certifications = models.JSONField(default=list, blank=True)
    
    # Assignment
    assigned_building = models.CharField(max_length=200, blank=True)
    assigned_gate = models.CharField(max_length=50, blank=True)
    assigned_area = models.CharField(max_length=200, blank=True)
    
    # Performance
    incidents_reported = models.IntegerField(default=0)
    incidents_resolved = models.IntegerField(default=0)
    performance_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00, 
                                            validators=[MinValueValidator(0), MaxValueValidator(5)])
    
    # System Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                   related_name='security_guards_created', blank=True, db_constraint=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Security Guard'
        verbose_name_plural = 'Security Guards'
        indexes = [
            models.Index(fields=['employee_id']),
            models.Index(fields=['status', 'shift']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.employee_id}"


class SecurityIncident(models.Model):
    """Security incidents and events"""
    SEVERITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    INCIDENT_TYPES = [
        ('theft', 'Theft'),
        ('vandalism', 'Vandalism'),
        ('trespassing', 'Trespassing'),
        ('fight', 'Fight/Altercation'),
        ('fire', 'Fire Incident'),
        ('medical', 'Medical Emergency'),
        ('suspicious', 'Suspicious Activity'),
        ('noise', 'Noise Complaint'),
        ('parking', 'Parking Violation'),
        ('unauthorized_access', 'Unauthorized Access'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('reported', 'Reported'),
        ('investigating', 'Under Investigation'),
        ('resolved', 'Resolved'),
        ('escalated', 'Escalated'),
        ('closed', 'Closed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident_number = models.CharField(max_length=50, unique=True)
    
    # Incident Details
    incident_type = models.CharField(max_length=50, choices=INCIDENT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    title = models.CharField(max_length=300)
    description = models.TextField()
    location = models.CharField(max_length=300)
    building = models.CharField(max_length=200, blank=True)
    unit_number = models.CharField(max_length=50, blank=True)
    
    # Timeline
    occurred_at = models.DateTimeField()
    reported_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # People Involved
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                   related_name='incidents_reported', db_constraint=False)
    assigned_to = models.ForeignKey(SecurityGuard, on_delete=models.SET_NULL, null=True, 
                                   related_name='assigned_incidents', blank=True)
    witnesses = models.ManyToManyField(User, related_name='witnessed_incidents', blank=True, db_constraint=False)
    suspects = models.JSONField(default=list, blank=True)
    
    # Investigation
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='reported')
    investigation_notes = models.TextField(blank=True)
    resolution_notes = models.TextField(blank=True)
    action_taken = models.TextField(blank=True)
    
    # Evidence
    photos = models.JSONField(default=list, blank=True)
    videos = models.JSONField(default=list, blank=True)
    documents = models.JSONField(default=list, blank=True)
    
    # Notifications
    police_notified = models.BooleanField(default=False)
    police_report_number = models.CharField(max_length=100, blank=True)
    management_notified = models.BooleanField(default=False)
    insurance_claim_filed = models.BooleanField(default=False)
    insurance_claim_number = models.CharField(max_length=100, blank=True)
    
    # Damage & Loss
    property_damage = models.BooleanField(default=False)
    estimated_damage_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    items_stolen = models.JSONField(default=list, blank=True)
    estimated_loss_value = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Follow-up
    requires_followup = models.BooleanField(default=False)
    followup_date = models.DateField(null=True, blank=True)
    followup_notes = models.TextField(blank=True)
    
    # System Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-occurred_at']
        verbose_name = 'Security Incident'
        verbose_name_plural = 'Security Incidents'
        indexes = [
            models.Index(fields=['incident_number']),
            models.Index(fields=['incident_type', 'status']),
            models.Index(fields=['severity']),
            models.Index(fields=['-occurred_at']),
        ]

    def __str__(self):
        return f"{self.incident_number} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.incident_number:
            self.incident_number = self._generate_incident_number()
        super().save(*args, **kwargs)

    def _generate_incident_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        count = SecurityIncident.objects.filter(
            incident_number__startswith=f'INC-{date_str}'
        ).count() + 1
        return f'INC-{date_str}-{count:04d}'


class VisitorLog(models.Model):
    """Track all visitors entering the property"""
    VISITOR_TYPES = [
        ('guest', 'Guest'),
        ('delivery', 'Delivery'),
        ('service', 'Service Provider'),
        ('contractor', 'Contractor'),
        ('vendor', 'Vendor'),
        ('real_estate', 'Real Estate Agent'),
        ('government', 'Government Official'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('denied', 'Denied'),
        ('expired', 'Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Visitor Information
    visitor_name = models.CharField(max_length=200)
    visitor_phone = models.CharField(max_length=20)
    visitor_email = models.EmailField(blank=True)
    visitor_type = models.CharField(max_length=50, choices=VISITOR_TYPES)
    visitor_company = models.CharField(max_length=200, blank=True)
    number_of_visitors = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    
    # Identification
    id_type = models.CharField(max_length=50, blank=True)
    id_number = models.CharField(max_length=100, blank=True)
    id_photo = models.CharField(max_length=500, blank=True)
    visitor_photo = models.CharField(max_length=500, blank=True)
    
    # Vehicle Information
    vehicle_number = models.CharField(max_length=50, blank=True)
    vehicle_type = models.CharField(max_length=100, blank=True)
    vehicle_make = models.CharField(max_length=100, blank=True)
    vehicle_color = models.CharField(max_length=50, blank=True)
    
    # Visit Details
    host = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='security_visitors_logs', db_constraint=False)
    host_unit = models.CharField(max_length=50)
    host_building = models.CharField(max_length=200)
    purpose = models.TextField()
    
    # Pre-approval
    is_pre_approved = models.BooleanField(default=False)
    pre_approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                        related_name='pre_approved_visitors', blank=True, db_constraint=False)
    approval_code = models.CharField(max_length=20, blank=True)
    
    # Timeline
    expected_arrival = models.DateTimeField()
    expected_departure = models.DateTimeField(null=True, blank=True)
    actual_checkin = models.DateTimeField(null=True, blank=True)
    actual_checkout = models.DateTimeField(null=True, blank=True)
    
    # Status & Processing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    checked_in_by = models.ForeignKey(SecurityGuard, on_delete=models.SET_NULL, null=True, 
                                     related_name='checked_in_visitors', blank=True)
    checked_out_by = models.ForeignKey(SecurityGuard, on_delete=models.SET_NULL, null=True, 
                                      related_name='checked_out_visitors', blank=True)
    denial_reason = models.TextField(blank=True)
    
    # Additional Information
    items_carried = models.TextField(blank=True)
    special_instructions = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    temperature_recorded = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    
    # Security
    access_card_issued = models.BooleanField(default=False)
    access_card_number = models.CharField(max_length=50, blank=True)
    access_card_returned = models.BooleanField(default=False)
    
    # Notifications
    host_notified = models.BooleanField(default=False)
    host_notification_sent_at = models.DateTimeField(null=True, blank=True)
    
    # System Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-expected_arrival']
        verbose_name = 'Visitor Log'
        verbose_name_plural = 'Visitor Logs'
        indexes = [
            models.Index(fields=['visitor_phone']),
            models.Index(fields=['host', 'status']),
            models.Index(fields=['-expected_arrival']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.visitor_name} - {self.host_unit}"


class AccessControl(models.Model):
    """Manage access permissions for different areas"""
    ACCESS_TYPES = [
        ('permanent', 'Permanent'),
        ('temporary', 'Temporary'),
        ('recurring', 'Recurring'),
        ('emergency', 'Emergency'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('expired', 'Expired'),
        ('revoked', 'Revoked'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Person
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_permissions', db_constraint=False)
    
    # Access Details
    access_type = models.CharField(max_length=20, choices=ACCESS_TYPES)
    access_areas = models.JSONField(default=list)  # List of accessible areas
    access_level = models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(10)])
    
    # Access Card/Key
    card_number = models.CharField(max_length=100, unique=True)
    card_type = models.CharField(max_length=50)
    pin_code = models.CharField(max_length=20, blank=True)
    biometric_registered = models.BooleanField(default=False)
    
    # Validity
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Restrictions
    time_restrictions = models.JSONField(default=dict, blank=True)
    day_restrictions = models.JSONField(default=list, blank=True)
    
    # Tracking
    last_used = models.DateTimeField(null=True, blank=True)
    usage_count = models.IntegerField(default=0)
    
    # System Fields
    issued_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                 related_name='access_cards_issued', blank=True, db_constraint=False)
    revoked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                  related_name='access_cards_revoked', blank=True, db_constraint=False)
    revoke_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Access Control'
        verbose_name_plural = 'Access Controls'
        indexes = [
            models.Index(fields=['card_number']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.card_number}"


class AccessLog(models.Model):
    """Log all access attempts"""
    ACCESS_RESULTS = [
        ('granted', 'Access Granted'),
        ('denied', 'Access Denied'),
        ('expired', 'Card Expired'),
        ('invalid', 'Invalid Card'),
        ('restricted_time', 'Restricted Time'),
        ('restricted_area', 'Restricted Area'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    access_control = models.ForeignKey(AccessControl, on_delete=models.CASCADE, 
                                      related_name='access_logs', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='access_attempts', db_constraint=False)
    
    # Access Attempt Details
    access_point = models.CharField(max_length=200)
    access_area = models.CharField(max_length=200)
    card_number = models.CharField(max_length=100)
    access_result = models.CharField(max_length=50, choices=ACCESS_RESULTS)
    
    # Additional Info
    access_method = models.CharField(max_length=50)  # card, biometric, pin, manual
    denial_reason = models.TextField(blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)
    
    # Security
    is_suspicious = models.BooleanField(default=False)
    photo_captured = models.CharField(max_length=500, blank=True)
    
    class Meta:
        ordering = ['-attempted_at']
        verbose_name = 'Access Log'
        verbose_name_plural = 'Access Logs'
        indexes = [
            models.Index(fields=['-attempted_at']),
            models.Index(fields=['access_result']),
            models.Index(fields=['is_suspicious']),
        ]

    def __str__(self):
        return f"{self.card_number} - {self.access_point} - {self.access_result}"


class PatrolLog(models.Model):
    """Security patrol and checkpoint logs"""
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('missed', 'Missed'),
        ('incident_found', 'Incident Found'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    guard = models.ForeignKey(SecurityGuard, on_delete=models.CASCADE, related_name='patrols')
    
    # Patrol Details
    patrol_route = models.CharField(max_length=200)
    checkpoints = models.JSONField(default=list)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    
    # Findings
    checkpoints_completed = models.JSONField(default=list)
    checkpoints_skipped = models.JSONField(default=list)
    observations = models.TextField(blank=True)
    incidents_found = models.ManyToManyField(SecurityIncident, related_name='found_during_patrols', blank=True)
    photos = models.JSONField(default=list, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    weather_conditions = models.CharField(max_length=200, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_start']
        verbose_name = 'Patrol Log'
        verbose_name_plural = 'Patrol Logs'
        indexes = [
            models.Index(fields=['guard', 'status']),
            models.Index(fields=['-scheduled_start']),
        ]

    def __str__(self):
        return f"{self.patrol_route} - {self.scheduled_start.strftime('%Y-%m-%d %H:%M')}"


class EmergencyAlert(models.Model):
    """Emergency alerts and SOS"""
    ALERT_TYPES = [
        ('sos', 'SOS'),
        ('fire', 'Fire'),
        ('medical', 'Medical Emergency'),
        ('security_threat', 'Security Threat'),
        ('natural_disaster', 'Natural Disaster'),
        ('evacuation', 'Evacuation'),
        ('lockdown', 'Lockdown'),
        ('other', 'Other'),
    ]
    
    PRIORITY_LEVELS = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('acknowledged', 'Acknowledged'),
        ('responding', 'Responding'),
        ('resolved', 'Resolved'),
        ('false_alarm', 'False Alarm'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    priority = models.CharField(max_length=20, choices=PRIORITY_LEVELS, default='high')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Location
    location = models.CharField(max_length=300)
    building = models.CharField(max_length=200, blank=True)
    unit_number = models.CharField(max_length=50, blank=True)
    coordinates = models.JSONField(default=dict, blank=True)
    
    # Alert Details
    title = models.CharField(max_length=300)
    description = models.TextField()
    triggered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                    related_name='emergency_alerts_triggered', db_constraint=False)
    
    # Timeline
    triggered_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Response
    acknowledged_by = models.ForeignKey(SecurityGuard, on_delete=models.SET_NULL, null=True, 
                                       related_name='alerts_acknowledged', blank=True)
    responders = models.ManyToManyField(SecurityGuard, related_name='alerts_responded', blank=True)
    response_notes = models.TextField(blank=True)
    resolution_notes = models.TextField(blank=True)
    
    # External Services
    police_called = models.BooleanField(default=False)
    fire_dept_called = models.BooleanField(default=False)
    ambulance_called = models.BooleanField(default=False)
    external_response_time = models.DurationField(null=True, blank=True)
    
    # Media
    photos = models.JSONField(default=list, blank=True)
    videos = models.JSONField(default=list, blank=True)
    
    # System Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-triggered_at']
        verbose_name = 'Emergency Alert'
        verbose_name_plural = 'Emergency Alerts'
        indexes = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['-triggered_at']),
        ]

    def __str__(self):
        return f"{self.alert_type} - {self.location} - {self.triggered_at.strftime('%Y-%m-%d %H:%M')}"


class CCTVCamera(models.Model):
    """CCTV Camera management"""
    STATUS_CHOICES = [
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('maintenance', 'Under Maintenance'),
        ('faulty', 'Faulty'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    camera_id = models.CharField(max_length=100, unique=True)
    camera_name = models.CharField(max_length=200)
    location = models.CharField(max_length=300)
    building = models.CharField(max_length=200, blank=True)
    floor = models.CharField(max_length=50, blank=True)
    
    # Technical Details
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    mac_address = models.CharField(max_length=100, blank=True)
    camera_type = models.CharField(max_length=100)
    manufacturer = models.CharField(max_length=100)
    model_number = models.CharField(max_length=100)
    
    # Installation
    installed_date = models.DateField()
    warranty_expiry = models.DateField(null=True, blank=True)
    last_maintenance = models.DateField(null=True, blank=True)
    next_maintenance = models.DateField(null=True, blank=True)
    
    # Status & Features
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='online')
    is_recording = models.BooleanField(default=True)
    has_audio = models.BooleanField(default=False)
    has_night_vision = models.BooleanField(default=True)
    has_motion_detection = models.BooleanField(default=True)
    pan_tilt_zoom = models.BooleanField(default=False)
    
    # Recording Details
    recording_quality = models.CharField(max_length=50, blank=True)
    storage_days = models.IntegerField(default=30)
    stream_url = models.CharField(max_length=500, blank=True)
    
    # Coverage
    coverage_area = models.TextField(blank=True)
    viewing_angle = models.IntegerField(null=True, blank=True)
    
    # Monitoring
    last_online = models.DateTimeField(null=True, blank=True)
    uptime_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['building', 'location']
        verbose_name = 'CCTV Camera'
        verbose_name_plural = 'CCTV Cameras'
        indexes = [
            models.Index(fields=['camera_id']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.camera_name} - {self.location}"


class SecurityAnnouncement(models.Model):
    """Security announcements and alerts to residents"""
    PRIORITY_LEVELS = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    title = models.CharField(max_length=300)
    message = models.TextField()
    priority = models.CharField(max_length=20, choices=PRIORITY_LEVELS, default='medium')
    
    # Targeting
    target_buildings = models.JSONField(default=list, blank=True)
    target_units = models.JSONField(default=list, blank=True)
    send_to_all = models.BooleanField(default=False)
    
    # Delivery
    send_email = models.BooleanField(default=True)
    send_sms = models.BooleanField(default=False)
    send_push = models.BooleanField(default=True)
    
    # Publishing
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Tracking
    sent_count = models.IntegerField(default=0)
    read_count = models.IntegerField(default=0)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                  related_name='security_announcements_created', db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Security Announcement'
        verbose_name_plural = 'Security Announcements'

    def __str__(self):
        return self.title