# maintenance/serializers.py - COMPLETE REPLACEMENT
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import MaintenanceRequest, MaintenanceSchedule, Vendor
from properties.models import Unit, Lease

User = get_user_model()


def _resolve_unit(building_name, unit_number, unit_id=None):
    if unit_id:
        unit = Unit.objects.select_related('building').filter(id=unit_id).first()
        if unit:
            return unit

    if building_name and unit_number:
        return Unit.objects.select_related('building').filter(
            building__name__iexact=building_name.strip(),
            unit_number__iexact=unit_number.strip(),
        ).first()

    return None


class MaintenanceRequestSerializer(serializers.ModelSerializer):
    # Display fields (read-only)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    requested_by_name = serializers.CharField(source='requested_by.get_full_name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True, allow_null=True)
    
    # Alias fields (write-only, map to model fields)
    location_detail = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    # Friendly field names for frontend (read-only)
    building_name = serializers.CharField(source='building', read_only=True)
    unit_id = serializers.UUIDField(write_only=True, required=False)
    lease_id = serializers.UUIDField(write_only=True, required=False)
    unit_display = serializers.CharField(source='unit.unit_number', read_only=True, allow_null=True)
    lease_display = serializers.CharField(source='lease.id', read_only=True, allow_null=True)
    owner_name = serializers.CharField(source='owner_user.get_full_name', read_only=True, allow_null=True)
    tenant_name = serializers.CharField(source='tenant_user.get_full_name', read_only=True, allow_null=True)
    
    class Meta:
        model = MaintenanceRequest
        fields = [
    'id', 'request_number', 'request_type', 'category', 'priority', 'title', 'description',
            'building', 'building_name', 'unit_number', 'specific_location', 'location_detail',
            'unit_id', 'lease_id', 'unit_display', 'lease_display',
            'requested_by', 'requested_by_name', 'contact_phone',
            'tenant_user', 'tenant_name', 'owner_user', 'owner_name', 'owner_email',
            'status', 'status_display', 'assigned_to', 'assigned_to_name',
            'requested_date', 'acknowledged_date', 'assigned_date', 'started_date', 'completed_date',
            'preferred_date', 'preferred_time', 'access_instructions', 'is_occupied',
            'work_performed', 'parts_used', 'parts_cost', 'labor_cost', 'total_cost',
            'photos_before', 'photos_after',
            'rating', 'feedback', 'feedback_date',
            'admin_notes', 'technician_notes',
            'created_at', 'updated_at',
            'category_display', 'priority_display'
        ]
        read_only_fields = [
            'id', 'request_number', 'requested_by', 'requested_date',
            'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'title': {'required': False},
            'building': {'required': False},
            'unit_number': {'required': False},
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Drop large image data fields on list views to improve performance
        request = self.context.get('request')
        view = self.context.get('view')
        if request and request.method == 'GET' and getattr(view, 'action', '') == 'list':
            self.fields.pop('photos_before', None)
            self.fields.pop('photos_after', None)

    def validate(self, attrs):
        """Handle missing title, building, unit and map location_detail"""
        request = self.context.get('request')
        user = request.user if request else None

        # 1. Fallback for Title
        if not attrs.get('title') and 'description' in attrs:
            desc = attrs.get('description', '')
            attrs['title'] = desc[:100] + ('...' if len(desc) > 100 else '')
        
        # 2. Fallback for Building & Unit (especially for residents)
        if user:
            if not attrs.get('building'):
                attrs['building'] = getattr(user, 'building_name', 'Main') or 'Main'
            if not attrs.get('unit_number'):
                attrs['unit_number'] = getattr(user, 'unit_number', 'N/A') or 'N/A'
            if not attrs.get('contact_phone'):
                attrs['contact_phone'] = getattr(user, 'phone', '') or ''

        unit = _resolve_unit(
            attrs.get('building') or getattr(user, 'building_name', ''),
            attrs.get('unit_number') or getattr(user, 'unit_number', ''),
            attrs.pop('unit_id', None),
        )
        lease_id = attrs.pop('lease_id', None)

        if unit:
            attrs['unit'] = unit
            attrs['building'] = unit.building.name if unit.building_id else attrs.get('building', '')
            attrs['unit_number'] = unit.unit_number
            owner_user = getattr(unit, 'owner_user', None)
            attrs['owner_user'] = owner_user or attrs.get('owner_user')
            attrs['owner_email'] = unit.owner_email or getattr(owner_user, 'email', '') or attrs.get('owner_email', '')

            if not attrs.get('owner_user') and unit.owner_email:
                attrs['owner_user'] = User.objects.filter(email__iexact=unit.owner_email).first()

            lease = None
            if lease_id:
                lease = Lease.objects.select_related('tenant').filter(id=lease_id, unit=unit).first()
            if not lease:
                lease = unit.leases.filter(status='active').select_related('tenant').first()

            if lease:
                attrs['lease'] = lease
                attrs['tenant_user'] = lease.tenant
                attrs['is_occupied'] = True
        elif lease_id:
            attrs['lease'] = Lease.objects.select_related('unit', 'tenant').filter(id=lease_id).first()

        # 3. Map location_detail to specific_location
        if 'location_detail' in attrs:
            attrs['specific_location'] = attrs.pop('location_detail')
            
        return attrs
    
    def create(self, validated_data):
        """No need for redundant logic anymore, handled in validate"""
        return super().create(validated_data)


class MaintenanceScheduleSerializer(serializers.ModelSerializer):
    frequency_display = serializers.CharField(source='get_frequency_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True, allow_null=True)
    
    class Meta:
        model = MaintenanceSchedule
        fields = '__all__'


class VendorSerializer(serializers.ModelSerializer):
    service_type_display = serializers.CharField(source='get_service_type_display', read_only=True)
    
    class Meta:
        model = Vendor
        fields = '__all__'