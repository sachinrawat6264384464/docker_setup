# ========================================
# FILE 3: entertainment/serializers.py
# ========================================
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Event, EventRegistration, Club

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user data"""
    full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'full_name']
    
    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class EventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_user = UserMiniSerializer(source='created_by', read_only=True)
    is_full = serializers.SerializerMethodField()
    spots_remaining = serializers.SerializerMethodField()
    is_attending = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            'id', 'title', 'description', 'event_type', 'event_type_display',
            'start_date', 'end_date', 'start_time', 'end_time',
            'venue', 'building', 'location_details',
            'max_attendees', 'current_attendees', 'is_full', 'spots_remaining',
            'requires_registration', 'registration_deadline',
            'is_paid', 'ticket_price', 'banner_image', 'images',
            'organized_by', 'contact_person', 'contact_phone', 'contact_email',
            'status', 'status_display', 'features', 'requirements', 'rules',
            'created_by_user', 'created_at', 'updated_at', 'is_attending'
        ]
        read_only_fields = ['id', 'current_attendees', 'created_at', 'updated_at']
    
    def get_is_full(self, obj):
        return obj.current_attendees >= obj.max_attendees
    
    def get_spots_remaining(self, obj):
        return max(0, obj.max_attendees - obj.current_attendees)
        
    def get_is_attending(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return EventRegistration.objects.filter(event=obj, user=request.user, status__in=['confirmed', 'attended', 'pending']).exists()
        return False
    
    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['created_by'] = request.user
        return super().create(validated_data)


class EventRegistrationSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_detail = EventSerializer(source='event', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_detail = UserMiniSerializer(source='user', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = EventRegistration
        fields = [
            'id', 'event', 'event_title', 'event_detail',
            'user', 'user_name', 'user_detail',
            'number_of_guests', 'guest_names', 'status', 'status_display',
            'payment_status', 'payment_reference', 'amount_paid',
            'checked_in_at', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'checked_in_at', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['user'] = request.user
        return super().create(validated_data)


class ClubSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    admin_name = serializers.CharField(source='admin.get_full_name', read_only=True)
    admin_detail = UserMiniSerializer(source='admin', read_only=True)
    member_count = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField()
    is_member = serializers.SerializerMethodField()
    
    class Meta:
        model = Club
        fields = [
            'id', 'name', 'description', 'category', 'category_display',
            'admin', 'admin_name', 'admin_detail',
            'members', 'member_count', 'max_members', 'is_full', 'is_member',
            'meeting_schedule', 'meeting_location',
            'is_active', 'logo',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_member_count(self, obj):
        return obj.member_count()
    
    def get_is_full(self, obj):
        return obj.is_full()
    
    def get_is_member(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.members.filter(id=request.user.id).exists()
        return False