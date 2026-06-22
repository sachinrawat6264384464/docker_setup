# security/admin.py
from django.contrib import admin
from .models import (
    SecurityGuard, SecurityIncident, VisitorLog, AccessControl,
    AccessLog, PatrolLog, EmergencyAlert, CCTVCamera, SecurityAnnouncement
)


@admin.register(SecurityGuard)
class SecurityGuardAdmin(admin.ModelAdmin):
    list_display = ['employee_id', 'user', 'shift', 'status', 'assigned_building', 'performance_rating', 'joining_date']
    list_filter = ['shift', 'status', 'assigned_building']
    search_fields = ['employee_id', 'user__first_name', 'user__last_name', 'user__email']
    readonly_fields = ['id', 'created_at', 'updated_at', 'incidents_reported', 'incidents_resolved']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'user', 'employee_id', 'shift', 'status')
        }),
        ('Personal Information', {
            'fields': ('date_of_birth', 'blood_group', 'emergency_contact_name', 'emergency_contact_phone')
        }),
        ('Professional Information', {
            'fields': ('joining_date', 'last_working_date', 'license_number', 'license_expiry', 
                      'training_completed', 'certifications')
        }),
        ('Assignment', {
            'fields': ('assigned_building', 'assigned_gate', 'assigned_area')
        }),
        ('Performance', {
            'fields': ('incidents_reported', 'incidents_resolved', 'performance_rating')
        }),
        ('System Fields', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SecurityIncident)
class SecurityIncidentAdmin(admin.ModelAdmin):
    list_display = ['incident_number', 'title', 'incident_type', 'severity', 'status', 'occurred_at', 'reported_by']
    list_filter = ['incident_type', 'severity', 'status', 'building', 'police_notified']
    search_fields = ['incident_number', 'title', 'description', 'location']
    readonly_fields = ['id', 'incident_number', 'reported_at', 'created_at', 'updated_at']
    date_hierarchy = 'occurred_at'
    
    fieldsets = (
        ('Incident Details', {
            'fields': ('id', 'incident_number', 'incident_type', 'severity', 'title', 'description', 
                      'location', 'building', 'unit_number')
        }),
        ('Timeline', {
            'fields': ('occurred_at', 'reported_at', 'resolved_at')
        }),
        ('People Involved', {
            'fields': ('reported_by', 'assigned_to', 'witnesses', 'suspects')
        }),
        ('Investigation', {
            'fields': ('status', 'investigation_notes', 'resolution_notes', 'action_taken')
        }),
        ('Evidence', {
            'fields': ('photos', 'videos', 'documents')
        }),
        ('Notifications', {
            'fields': ('police_notified', 'police_report_number', 'management_notified', 
                      'insurance_claim_filed', 'insurance_claim_number')
        }),
        ('Damage & Loss', {
            'fields': ('property_damage', 'estimated_damage_cost', 'items_stolen', 'estimated_loss_value')
        }),
        ('Follow-up', {
            'fields': ('requires_followup', 'followup_date', 'followup_notes')
        }),
    )


@admin.register(VisitorLog)
class VisitorLogAdmin(admin.ModelAdmin):
    list_display = ['visitor_name', 'visitor_type', 'host', 'host_unit', 'expected_arrival', 'status']
    list_filter = ['visitor_type', 'status', 'host_building', 'is_pre_approved']
    search_fields = ['visitor_name', 'visitor_phone', 'visitor_email', 'vehicle_number']
    readonly_fields = ['id', 'created_at', 'updated_at']
    date_hierarchy = 'expected_arrival'
    
    fieldsets = (
        ('Visitor Information', {
            'fields': ('id', 'visitor_name', 'visitor_phone', 'visitor_email', 'visitor_type', 
                      'visitor_company', 'number_of_visitors')
        }),
        ('Identification', {
            'fields': ('id_type', 'id_number', 'id_photo', 'visitor_photo')
        }),
        ('Vehicle Information', {
            'fields': ('vehicle_number', 'vehicle_type', 'vehicle_make', 'vehicle_color')
        }),
        ('Visit Details', {
            'fields': ('host', 'host_unit', 'host_building', 'purpose')
        }),
        ('Pre-approval', {
            'fields': ('is_pre_approved', 'pre_approved_by', 'approval_code')
        }),
        ('Timeline', {
            'fields': ('expected_arrival', 'expected_departure', 'actual_checkin', 'actual_checkout')
        }),
        ('Status & Processing', {
            'fields': ('status', 'checked_in_by', 'checked_out_by', 'denial_reason')
        }),
        ('Additional Information', {
            'fields': ('items_carried', 'special_instructions', 'notes', 'temperature_recorded')
        }),
        ('Security', {
            'fields': ('access_card_issued', 'access_card_number', 'access_card_returned')
        }),
    )


@admin.register(AccessControl)
class AccessControlAdmin(admin.ModelAdmin):
    list_display = ['card_number', 'user', 'access_type', 'status', 'valid_from', 'valid_until']
    list_filter = ['access_type', 'status', 'card_type']
    search_fields = ['card_number', 'user__first_name', 'user__last_name', 'user__email']
    readonly_fields = ['id', 'created_at', 'updated_at', 'last_used', 'usage_count']
    
    fieldsets = (
        ('Person', {
            'fields': ('id', 'user')
        }),
        ('Access Details', {
            'fields': ('access_type', 'access_areas', 'access_level')
        }),
        ('Access Card/Key', {
            'fields': ('card_number', 'card_type', 'pin_code', 'biometric_registered')
        }),
        ('Validity', {
            'fields': ('valid_from', 'valid_until', 'status')
        }),
        ('Restrictions', {
            'fields': ('time_restrictions', 'day_restrictions')
        }),
        ('Tracking', {
            'fields': ('last_used', 'usage_count')
        }),
        ('System Fields', {
            'fields': ('issued_by', 'revoked_by', 'revoke_reason', 'notes', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ['card_number', 'access_point', 'access_result', 'attempted_at', 'is_suspicious']
    list_filter = ['access_result', 'access_method', 'is_suspicious', 'access_point']
    search_fields = ['card_number', 'access_point', 'access_area']
    readonly_fields = ['id', 'attempted_at']
    date_hierarchy = 'attempted_at'
    
    fieldsets = (
        ('Access Attempt Details', {
            'fields': ('id', 'access_control', 'user', 'access_point', 'access_area', 
                      'card_number', 'access_result')
        }),
        ('Additional Info', {
            'fields': ('access_method', 'denial_reason', 'attempted_at')
        }),
        ('Security', {
            'fields': ('is_suspicious', 'photo_captured')
        }),
    )


@admin.register(PatrolLog)
class PatrolLogAdmin(admin.ModelAdmin):
    list_display = ['patrol_route', 'guard', 'scheduled_start', 'status']
    list_filter = ['status', 'patrol_route']
    search_fields = ['patrol_route', 'guard__user__first_name', 'guard__user__last_name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    date_hierarchy = 'scheduled_start'
    
    fieldsets = (
        ('Patrol Details', {
            'fields': ('id', 'guard', 'patrol_route', 'checkpoints', 'scheduled_start', 
                      'scheduled_end', 'actual_start', 'actual_end')
        }),
        ('Status', {
            'fields': ('status',)
        }),
        ('Findings', {
            'fields': ('checkpoints_completed', 'checkpoints_skipped', 'observations', 
                      'incidents_found', 'photos')
        }),
        ('Notes', {
            'fields': ('notes', 'weather_conditions')
        }),
    )


@admin.register(EmergencyAlert)
class EmergencyAlertAdmin(admin.ModelAdmin):
    list_display = ['title', 'alert_type', 'priority', 'status', 'location', 'triggered_at']
    list_filter = ['alert_type', 'priority', 'status', 'building']
    search_fields = ['title', 'description', 'location']
    readonly_fields = ['id', 'triggered_at', 'created_at', 'updated_at']
    date_hierarchy = 'triggered_at'
    
    fieldsets = (
        ('Alert Details', {
            'fields': ('id', 'alert_type', 'priority', 'status', 'title', 'description')
        }),
        ('Location', {
            'fields': ('location', 'building', 'unit_number', 'coordinates')
        }),
        ('Timeline', {
            'fields': ('triggered_at', 'acknowledged_at', 'resolved_at')
        }),
        ('Triggered By', {
            'fields': ('triggered_by',)
        }),
        ('Response', {
            'fields': ('acknowledged_by', 'responders', 'response_notes', 'resolution_notes')
        }),
        ('External Services', {
            'fields': ('police_called', 'fire_dept_called', 'ambulance_called', 'external_response_time')
        }),
        ('Media', {
            'fields': ('photos', 'videos')
        }),
    )


@admin.register(CCTVCamera)
class CCTVCameraAdmin(admin.ModelAdmin):
    list_display = ['camera_id', 'camera_name', 'location', 'building', 'status', 'is_recording']
    list_filter = ['status', 'building', 'is_recording', 'has_night_vision', 'has_motion_detection']
    search_fields = ['camera_id', 'camera_name', 'location']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'camera_id', 'camera_name', 'location', 'building', 'floor')
        }),
        ('Technical Details', {
            'fields': ('ip_address', 'mac_address', 'camera_type', 'manufacturer', 'model_number')
        }),
        ('Installation', {
            'fields': ('installed_date', 'warranty_expiry', 'last_maintenance', 'next_maintenance')
        }),
        ('Status & Features', {
            'fields': ('status', 'is_recording', 'has_audio', 'has_night_vision', 
                      'has_motion_detection', 'pan_tilt_zoom')
        }),
        ('Recording Details', {
            'fields': ('recording_quality', 'storage_days', 'stream_url')
        }),
        ('Coverage', {
            'fields': ('coverage_area', 'viewing_angle')
        }),
        ('Monitoring', {
            'fields': ('last_online', 'uptime_percentage')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
    )


@admin.register(SecurityAnnouncement)
class SecurityAnnouncementAdmin(admin.ModelAdmin):
    list_display = ['title', 'priority', 'published', 'published_at', 'created_by']
    list_filter = ['priority', 'published', 'send_email', 'send_sms', 'send_push']
    search_fields = ['title', 'message']
    readonly_fields = ['id', 'created_at', 'updated_at', 'sent_count', 'read_count']
    
    fieldsets = (
        ('Announcement Details', {
            'fields': ('id', 'title', 'message', 'priority')
        }),
        ('Targeting', {
            'fields': ('target_buildings', 'target_units', 'send_to_all')
        }),
        ('Delivery', {
            'fields': ('send_email', 'send_sms', 'send_push')
        }),
        ('Publishing', {
            'fields': ('published', 'published_at', 'expires_at')
        }),
        ('Tracking', {
            'fields': ('sent_count', 'read_count')
        }),
        ('System Fields', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )