# security/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    SecurityGuard, SecurityIncident, VisitorLog, AccessControl,
    AccessLog, PatrolLog, EmergencyAlert, CCTVCamera, SecurityAnnouncement
)

User = get_user_model()
from communication.serializers import safe_get_user


class SecurityGuardSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_phone = serializers.CharField(source='user.phone', read_only=True)
    shift_display = serializers.CharField(source='get_shift_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    license_valid = serializers.SerializerMethodField()
    
    class Meta:
        model = SecurityGuard
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'incidents_reported', 'incidents_resolved']
    
    def get_license_valid(self, obj):
        from django.utils import timezone
        return obj.license_expiry > timezone.now().date() if obj.license_expiry else False


class SecurityGuardCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityGuard
        fields = [
            'user', 'employee_id', 'shift', 'date_of_birth', 'blood_group',
            'emergency_contact_name', 'emergency_contact_phone', 'joining_date',
            'license_number', 'license_expiry', 'training_completed', 'certifications',
            'assigned_building', 'assigned_gate', 'assigned_area'
        ]


class SecurityIncidentSerializer(serializers.ModelSerializer):
    incident_type_display = serializers.CharField(source='get_incident_type_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    reported_by = serializers.SerializerMethodField()
    reported_by_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.CharField(source='assigned_to.user.get_full_name', read_only=True)
    response_time = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    
    class Meta:
        model = SecurityIncident
        fields = '__all__'
        read_only_fields = ['id', 'incident_number', 'reported_at', 'created_at', 'updated_at']
    
    def get_reported_by(self, obj):
        user = safe_get_user(obj, 'reported_by')
        return user.id if user else None
        
    def get_reported_by_name(self, obj):
        user = safe_get_user(obj, 'reported_by')
        return user.get_full_name() if user else None
        
    def get_response_time(self, obj):
        if obj.resolved_at and obj.reported_at:
            delta = obj.resolved_at - obj.reported_at
            hours = delta.total_seconds() / 3600
            return round(hours, 2)
        return None
    
    def get_is_overdue(self, obj):
        from django.utils import timezone
        if obj.status in ['resolved', 'closed']:
            return False
        
        overdue_hours = {
            'critical': 2,
            'high': 6,
            'medium': 24,
            'low': 72
        }
        
        hours_since_report = (timezone.now() - obj.reported_at).total_seconds() / 3600
        return hours_since_report > overdue_hours.get(obj.severity, 24)


class SecurityIncidentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityIncident
        fields = [
            'incident_type', 'severity', 'title', 'description', 'location',
            'building', 'unit_number', 'occurred_at', 'reported_by', 'assigned_to',
            'photos', 'videos', 'documents'
        ]
        read_only_fields = ['reported_by']


class VisitorLogSerializer(serializers.ModelSerializer):
    visitor_type_display = serializers.CharField(source='get_visitor_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    host = serializers.SerializerMethodField()
    host_name = serializers.SerializerMethodField()
    checked_in_by_name = serializers.CharField(source='checked_in_by.user.get_full_name', read_only=True)
    checked_out_by_name = serializers.CharField(source='checked_out_by.user.get_full_name', read_only=True)
    duration = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    
    class Meta:
        model = VisitorLog
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
        
    def get_host(self, obj):
        user = safe_get_user(obj, 'host')
        return user.id if user else None
        
    def get_host_name(self, obj):
        user = safe_get_user(obj, 'host')
        return user.get_full_name() if user else 'Resident'
    
    def get_duration(self, obj):
        if obj.actual_checkin and obj.actual_checkout:
            delta = obj.actual_checkout - obj.actual_checkin
            minutes = delta.total_seconds() / 60
            return round(minutes, 2)
        return None
    
    def get_is_overdue(self, obj):
        from django.utils import timezone
        if obj.status == 'checked_out':
            return False
        if obj.expected_departure and timezone.now() > obj.expected_departure:
            return True
        return False


class VisitorPreApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitorLog
        fields = [
            'visitor_name', 'visitor_phone', 'visitor_email', 'visitor_type',
            'host', 'host_unit', 'host_building', 'purpose', 'expected_arrival',
            'expected_departure', 'vehicle_number'
        ]


class AccessControlSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    access_type_display = serializers.CharField(source='get_access_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_valid = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    
    class Meta:
        model = AccessControl
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_used', 'usage_count']
    
    def get_is_valid(self, obj):
        from django.utils import timezone
        if obj.status != 'active':
            return False
        if obj.valid_until and timezone.now() > obj.valid_until:
            return False
        return True
    
    def get_is_expired(self, obj):
        from django.utils import timezone
        return obj.valid_until and timezone.now() > obj.valid_until if obj.valid_until else False


class AccessLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    access_result_display = serializers.CharField(source='get_access_result_display', read_only=True)
    
    class Meta:
        model = AccessLog
        fields = '__all__'
        read_only_fields = ['id', 'attempted_at']


class PatrolLogSerializer(serializers.ModelSerializer):
    guard_name = serializers.CharField(source='guard.user.get_full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    completion_percentage = serializers.SerializerMethodField()
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = PatrolLog
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_completion_percentage(self, obj):
        total = len(obj.checkpoints)
        completed = len(obj.checkpoints_completed)
        if total == 0:
            return 0
        return round((completed / total) * 100, 2)
    
    def get_duration(self, obj):
        if obj.actual_start and obj.actual_end:
            delta = obj.actual_end - obj.actual_start
            minutes = delta.total_seconds() / 60
            return round(minutes, 2)
        return None


class EmergencyAlertSerializer(serializers.ModelSerializer):
    alert_type_display = serializers.CharField(source='get_alert_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    triggered_by = serializers.SerializerMethodField()
    triggered_by_name = serializers.SerializerMethodField()
    acknowledged_by_name = serializers.CharField(source='acknowledged_by.user.get_full_name', read_only=True)
    response_time = serializers.SerializerMethodField()
    
    class Meta:
        model = EmergencyAlert
        fields = '__all__'
        read_only_fields = ['id', 'triggered_at', 'created_at', 'updated_at']
        
    def get_triggered_by(self, obj):
        user = safe_get_user(obj, 'triggered_by')
        return user.id if user else None
        
    def get_triggered_by_name(self, obj):
        user = safe_get_user(obj, 'triggered_by')
        return user.get_full_name() if user else None
    
    def get_response_time(self, obj):
        if obj.acknowledged_at and obj.triggered_at:
            delta = obj.acknowledged_at - obj.triggered_at
            minutes = delta.total_seconds() / 60
            return round(minutes, 2)
        return None


class CCTVCameraSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_due_maintenance = serializers.SerializerMethodField()
    warranty_valid = serializers.SerializerMethodField()
    
    class Meta:
        model = CCTVCamera
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_is_due_maintenance(self, obj):
        from django.utils import timezone
        return obj.next_maintenance and obj.next_maintenance <= timezone.now().date() if obj.next_maintenance else False
    
    def get_warranty_valid(self, obj):
        from django.utils import timezone
        return obj.warranty_expiry and obj.warranty_expiry > timezone.now().date() if obj.warranty_expiry else False


class SecurityAnnouncementSerializer(serializers.ModelSerializer):
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    created_by = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    read_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = SecurityAnnouncement
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'sent_count', 'read_count']
        
    def get_created_by(self, obj):
        user = safe_get_user(obj, 'created_by')
        return user.id if user else None
        
    def get_created_by_name(self, obj):
        user = safe_get_user(obj, 'created_by')
        return user.get_full_name() if user else None
    
    def get_is_expired(self, obj):
        from django.utils import timezone
        return obj.expires_at and timezone.now() > obj.expires_at if obj.expires_at else False
    
    def get_read_percentage(self, obj):
        if obj.sent_count == 0:
            return 0
        return round((obj.read_count / obj.sent_count) * 100, 2)


# Dashboard Serializers
class SecurityDashboardSerializer(serializers.Serializer):
    total_guards = serializers.IntegerField()
    active_guards = serializers.IntegerField()
    total_incidents = serializers.IntegerField()
    open_incidents = serializers.IntegerField()
    critical_incidents = serializers.IntegerField()
    visitors_today = serializers.IntegerField()
    active_visitors = serializers.IntegerField()
    active_alerts = serializers.IntegerField()
    cameras_online = serializers.IntegerField()
    cameras_total = serializers.IntegerField()


class IncidentStatisticsSerializer(serializers.Serializer):
    incident_type = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class VisitorStatisticsSerializer(serializers.Serializer):
    visitor_type = serializers.CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()