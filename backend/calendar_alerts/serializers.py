# calendar/serializers.py
from rest_framework import serializers
from .models import CalendarAlert, AlertRecipient

class CalendarAlertSerializer(serializers.ModelSerializer):
    alert_type_display = serializers.CharField(source='get_alert_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    building_name = serializers.CharField(source='building.name', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    is_active = serializers.SerializerMethodField()
    duration_hours = serializers.SerializerMethodField()
    location = serializers.CharField(source='affected_area', required=False, allow_blank=True, allow_null=True)
    
    class Meta:
        model = CalendarAlert
        fields = '__all__'
    
    def get_is_active(self, obj):
        from django.utils import timezone
        now = timezone.now()
        start_datetime = getattr(obj, 'start_datetime', None)
        end_datetime = getattr(obj, 'end_datetime', None)
        status = getattr(obj, 'status', None)

        if start_datetime is None and isinstance(obj, dict):
            start_datetime = obj.get('start_datetime')
            end_datetime = obj.get('end_datetime')
            status = obj.get('status')

        if not start_datetime or not end_datetime:
            return False

        return start_datetime <= now <= end_datetime and status == 'active'
    
    def get_duration_hours(self, obj):
        start_datetime = getattr(obj, 'start_datetime', None)
        end_datetime = getattr(obj, 'end_datetime', None)

        if start_datetime is None and isinstance(obj, dict):
            start_datetime = obj.get('start_datetime')
            end_datetime = obj.get('end_datetime')

        if not start_datetime or not end_datetime:
            return 0

        delta = end_datetime - start_datetime
        return round(delta.total_seconds() / 3600, 2)

class CalendarAlertCreateSerializer(serializers.ModelSerializer):
    location = serializers.CharField(source='affected_area', required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = CalendarAlert
        fields = '__all__'
        read_only_fields = ['created_by', 'notification_sent', 'notification_sent_at']
    
    def validate(self, data):
        from django.utils import timezone
        import re
        
        # 1. End datetime must be after start datetime
        start_datetime = data.get('start_datetime')
        end_datetime = data.get('end_datetime')
        if end_datetime and start_datetime:
            if end_datetime <= start_datetime:
                raise serializers.ValidationError("End datetime must be after start datetime")
        
        # 2. Past Date Validation: prevent setting start date earlier than timezone.now() on creation
        if not self.instance and start_datetime and start_datetime < timezone.now():
            raise serializers.ValidationError({"start_datetime": "Cannot create events in the past."})
            
        # 3. Title formatting & length validations
        title = data.get('title')
        if title is not None:
            title_stripped = title.strip()
            if not title_stripped:
                raise serializers.ValidationError({"title": "Title cannot be blank or whitespace only."})
            if len(title_stripped) < 3:
                raise serializers.ValidationError({"title": "Title must be at least 3 characters long."})
            if len(title_stripped) > 100:
                raise serializers.ValidationError({"title": "Title must be 100 characters or fewer."})
            if not re.search(r'[a-zA-Z0-9]', title_stripped):
                raise serializers.ValidationError({"title": "Title must contain at least one alphanumeric character."})
                
        # 4. SQLi & XSS Input Sanitization
        fields_to_check = {
            'title': title,
            'description': data.get('description'),
            'affected_area': data.get('affected_area')
        }
        
        for field_name, value in fields_to_check.items():
            if value:
                value_lower = value.lower()
                # XSS Check
                xss_patterns = ['<script', 'javascript:', 'onload=', 'onerror=', 'onclick=']
                for pat in xss_patterns:
                    if pat in value_lower:
                        raise serializers.ValidationError({field_name: "Potential XSS detected."})
                if re.search(r'<[^>]+>', value):
                    raise serializers.ValidationError({field_name: "HTML tags are not allowed."})
                
                # SQLi Check
                sqli_patterns = [
                    "' or 1=1", '" or 1=1', "' or '1'='1", '" or "1"="1', 
                    "' --", '" --', "union select", "drop table", "alter table", "delete from"
                ]
                for pat in sqli_patterns:
                    if pat in value_lower:
                        raise serializers.ValidationError({field_name: "Potential SQL injection detected."})

        # 5. Duplicate Prevention: Before creating/updating, query CalendarAlert for entries with matching title, start datetime, and location (affected_area)
        curr_title = data.get('title') if 'title' in data else (self.instance.title if self.instance else None)
        curr_start = data.get('start_datetime') if 'start_datetime' in data else (self.instance.start_datetime if self.instance else None)
        curr_area = data.get('affected_area') if 'affected_area' in data else (self.instance.affected_area if self.instance else '')
        if curr_title and curr_start:
            duplicate_qs = CalendarAlert.objects.filter(
                title=curr_title,
                start_datetime=curr_start,
                affected_area=curr_area or ''
            )
            if self.instance:
                duplicate_qs = duplicate_qs.exclude(id=self.instance.id)
            if duplicate_qs.exists():
                raise serializers.ValidationError("An event with the same title, start time, and location already exists.")

        return data

    def to_internal_value(self, data):
        # Ensure alert_type is lowercase
        if 'alert_type' in data and data['alert_type']:
            data = data.copy()
            data['alert_type'] = data['alert_type'].lower()
        
        # Handle empty date strings
        if 'start_datetime' in data and not data['start_datetime']:
            data = data.copy()
            data['start_datetime'] = None
        if 'end_datetime' in data and not data['end_datetime']:
            data = data.copy()
            data['end_datetime'] = None
            
        return super().to_internal_value(data)

class AlertRecipientSerializer(serializers.ModelSerializer):
    alert_title = serializers.CharField(source='alert.title', read_only=True)
    alert_type = serializers.CharField(source='alert.alert_type', read_only=True)
    alert_priority = serializers.CharField(source='alert.priority', read_only=True)
    alert_start = serializers.DateTimeField(source='alert.start_datetime', read_only=True)
    alert_end = serializers.DateTimeField(source='alert.end_datetime', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    
    class Meta:
        model = AlertRecipient
        fields = '__all__'

class AlertRecipientCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRecipient
        fields = '__all__'

class TodayAlertsSerializer(serializers.Serializer):
    active_alerts = CalendarAlertSerializer(many=True)
    upcoming_alerts = CalendarAlertSerializer(many=True)
    total_active = serializers.IntegerField()
    total_upcoming = serializers.IntegerField()
