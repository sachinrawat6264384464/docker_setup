# visitors/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    VisitorType, Visitor, VisitorPass, VisitorLog,
    BlacklistedVisitor, VisitorFeedback
)

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user data for visitors"""
    full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'full_name']
    
    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class VisitorTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitorType
        fields = [
            'id', 'name', 'description', 'requires_approval',
            'max_duration_hours', 'color_code', 'is_active',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class VisitorSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    is_blacklisted_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Visitor
        fields = [
            'id', 'visitor_number', 'first_name', 'last_name', 'full_name',
            'email', 'phone', 'gender', 'id_type', 'id_number', 'photo',
            'vehicle_make', 'vehicle_model', 'vehicle_color', 'vehicle_plate',
            'company_name', 'is_blacklisted', 'is_blacklisted_status',
            'blacklist_reason', 'first_visit', 'last_visit', 'visit_count'
        ]
        read_only_fields = [
            'id', 'visitor_number', 'first_visit', 'last_visit', 
            'visit_count', 'is_blacklisted'
        ]
    
    def get_full_name(self, obj):
        return obj.get_full_name()
    
    def get_is_blacklisted_status(self, obj):
        if obj.is_blacklisted:
            return {
                'status': True,
                'reason': obj.blacklist_reason,
                'date': obj.blacklisted_at
            }
        return {'status': False}


class VisitorPassSerializer(serializers.ModelSerializer):
    visitor = VisitorSerializer(read_only=True)
    visitor_id = serializers.UUIDField(write_only=True)
    visitor_type = VisitorTypeSerializer(read_only=True)
    visitor_type_id = serializers.IntegerField(write_only=True)
    host = UserMiniSerializer(read_only=True)
    approved_by_user = UserMiniSerializer(source='approved_by', read_only=True)
    rejected_by_user = UserMiniSerializer(source='rejected_by', read_only=True)
    is_expired = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    
    class Meta:
        model = VisitorPass
        fields = [
            'id', 'pass_number', 'visitor', 'visitor_id', 'visitor_type',
            'visitor_type_id', 'host', 'purpose', 'building', 'unit_number',
            'expected_arrival', 'expected_departure', 'actual_arrival',
            'actual_departure', 'status', 'approved_by_user', 'approved_at',
            'rejected_by_user', 'rejected_at', 'rejection_reason',
            'qr_code', 'access_code', 'security_notes', 'can_drive_in',
            'requires_escort', 'is_expired', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'pass_number', 'approved_at', 'rejected_at',
            'qr_code', 'access_code', 'actual_arrival', 'actual_departure',
            'created_at', 'updated_at'
        ]
    
    def get_is_expired(self, obj):
        return obj.is_expired()
    
    def get_is_active(self, obj):
        return obj.status == 'active'
    
    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['host'] = request.user
        return super().create(validated_data)


import uuid as _uuid

class VisitorPassCreateSerializer(serializers.ModelSerializer):
    """Simplified serializer for creating visitor passes"""
    visitor_id = serializers.UUIDField(required=True)
    visitor_type_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = VisitorPass
        fields = [
            'visitor_id', 'visitor_type_id', 'purpose', 'building',
            'unit_number', 'expected_arrival', 'expected_departure',
            'can_drive_in', 'requires_escort', 'security_notes'
        ]

    def create(self, validated_data):
        request = self.context.get('request')
        host = request.user
        validated_data['host'] = host

        # --- Handle building and unit_number fallbacks ---
        # If frontend sends "Main"/"N/A" or empty, try to use host's profile
        building = validated_data.get('building')
        unit_number = validated_data.get('unit_number')

        if not building or building == 'Main':
            validated_data['building'] = getattr(host, 'building_name', building) or 'Main'
        
        if not unit_number or unit_number == 'N/A':
            validated_data['unit_number'] = getattr(host, 'unit_number', unit_number) or 'N/A'

        # --- Resolve visitor ---
        visitor_id = validated_data.pop('visitor_id', None)
        try:
            visitor = Visitor.objects.get(pk=visitor_id)
        except Visitor.DoesNotExist:
            raise serializers.ValidationError({'visitor_id': 'Visitor not found.'})
        validated_data['visitor'] = visitor

        # --- Resolve visitor_type ---
        visitor_type_id = validated_data.pop('visitor_type_id', None)
        visitor_type = None
        if visitor_type_id:
            try:
                visitor_type = VisitorType.objects.get(id=visitor_type_id)
            except VisitorType.DoesNotExist:
                visitor_type = None

        if visitor_type is None:
            visitor_type, _ = VisitorType.objects.get_or_create(
                name='Guest',
                defaults={
                    'description': 'Default guest type',
                    'requires_approval': False,
                    'color_code': '#10b981',
                    'is_active': True,
                }
            )
        validated_data['visitor_type'] = visitor_type

        # Auto-approve if visitor type doesn't require approval
        if not visitor_type.requires_approval:
            validated_data['status'] = 'approved'
            validated_data['approved_by'] = request.user
            from django.utils import timezone
            validated_data['approved_at'] = timezone.now()

        return super().create(validated_data)


class VisitorLogSerializer(serializers.ModelSerializer):
    visitor_pass = VisitorPassSerializer(read_only=True)
    security_staff = UserMiniSerializer(read_only=True)
    
    class Meta:
        model = VisitorLog
        fields = [
            'id', 'visitor_pass', 'log_type', 'security_staff',
            'gate_number', 'entry_point', 'notes', 'temperature',
            'health_screening_passed', 'entry_photo', 'timestamp'
        ]
        read_only_fields = ['id', 'timestamp']


class BlacklistedVisitorSerializer(serializers.ModelSerializer):
    visitor = VisitorSerializer(read_only=True)
    blacklisted_by_user = UserMiniSerializer(source='blacklisted_by', read_only=True)
    is_currently_active = serializers.SerializerMethodField()
    
    class Meta:
        model = BlacklistedVisitor
        fields = [
            'id', 'visitor', 'reason', 'blacklisted_by_user',
            'blacklisted_at', 'is_permanent', 'expires_at',
            'notes', 'is_currently_active'
        ]
        read_only_fields = ['id', 'blacklisted_at']
    
    def get_is_currently_active(self, obj):
        return obj.is_active()


class VisitorFeedbackSerializer(serializers.ModelSerializer):
    visitor_pass = VisitorPassSerializer(read_only=True)
    
    class Meta:
        model = VisitorFeedback
        fields = [
            'id', 'visitor_pass', 'rating', 'comments',
            'security_staff_rating', 'process_ease_rating',
            'would_recommend', 'submitted_at'
        ]
        read_only_fields = ['id', 'submitted_at']