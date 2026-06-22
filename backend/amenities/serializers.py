# amenities/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Amenity, AmenityBooking, AmenityReview, AmenityMaintenance,
    AmenityUsageLog, AmenityRule, AmenityBlockAssignment
)
from properties.models import Block, Unit

User = get_user_model()


class AmenitySerializer(serializers.ModelSerializer):
    amenity_type_display = serializers.CharField(source='get_amenity_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    is_currently_available = serializers.SerializerMethodField()
    utilization_rate = serializers.SerializerMethodField()
    block_assignments = serializers.SerializerMethodField()
    assigned_block_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        allow_empty=True,
    )
    
    class Meta:
        model = Amenity
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'total_bookings', 'active_bookings', 
                           'rating_average', 'review_count']
    
    def get_is_currently_available(self, obj):
        from django.utils import timezone
        return obj.is_available_at(timezone.now())
    
    def get_utilization_rate(self, obj):
        from django.utils import timezone
        from datetime import timedelta
        
        # Calculate utilization for last 30 days
        thirty_days_ago = timezone.now() - timedelta(days=30)
        total_hours = 30 * 24
        
        bookings = obj.bookings.filter(
            booking_date__gte=thirty_days_ago.date(),
            status__in=['confirmed', 'completed']
        )
        
        booked_hours = sum([float(b.duration_hours) for b in bookings])
        return round((booked_hours / total_hours) * 100, 2) if total_hours > 0 else 0

    def get_block_assignments(self, obj):
        assignments = obj.block_assignments.select_related('block', 'block__building').all()
        return [
            {
                'block_id': str(assignment.block_id),
                'block_name': assignment.block.name,
                'building_id': str(assignment.block.building_id),
                'building_name': assignment.block.building.name,
            }
            for assignment in assignments
        ]

    def _set_block_assignments(self, amenity, block_ids):
        block_ids = block_ids or []
        if not block_ids:
            amenity.block_assignments.all().delete()
            return

        valid_blocks = list(Block.objects.filter(id__in=block_ids).values_list('id', flat=True))
        if len(valid_blocks) != len(set(block_ids)):
            raise serializers.ValidationError({'assigned_block_ids': 'One or more selected blocks are invalid.'})

        amenity.block_assignments.exclude(block_id__in=valid_blocks).delete()
        existing_ids = set(
            amenity.block_assignments.filter(block_id__in=valid_blocks).values_list('block_id', flat=True)
        )
        creator = self.context.get('request').user if self.context.get('request') else None
        new_assignments = [
            AmenityBlockAssignment(amenity=amenity, block_id=block_id, created_by=creator)
            for block_id in valid_blocks
            if block_id not in existing_ids
        ]
        if new_assignments:
            AmenityBlockAssignment.objects.bulk_create(new_assignments)

    def create(self, validated_data):
        block_ids = validated_data.pop('assigned_block_ids', [])
        amenity = super().create(validated_data)
        self._set_block_assignments(amenity, block_ids)
        return amenity

    def update(self, instance, validated_data):
        block_ids = validated_data.pop('assigned_block_ids', None)
        amenity = super().update(instance, validated_data)
        if block_ids is not None:
            self._set_block_assignments(amenity, block_ids)
        return amenity


class AmenityListSerializer(serializers.ModelSerializer):
    amenity_type_display = serializers.CharField(source='get_amenity_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    block_assignments = serializers.SerializerMethodField()
    
    class Meta:
        model = Amenity
        fields = ['id', 'name', 'amenity_type', 'amenity_type_display', 'status', 'status_display',
                 'is_bookable', 'capacity', 'is_paid', 'price_per_hour', 'rating_average', 'building',
                 'block_assignments', 'description', 'rules', 'operating_hours']

    def get_block_assignments(self, obj):
        assignments = obj.block_assignments.select_related('block', 'block__building').all()
        return [
            {
                'block_id': str(assignment.block_id),
                'block_name': assignment.block.name,
                'building_id': str(assignment.block.building_id),
                'building_name': assignment.block.building.name,
            }
            for assignment in assignments
        ]


class AmenityBookingSerializer(serializers.ModelSerializer):
    amenity_name = serializers.CharField(source='amenity.name', read_only=True)
    amenity_type = serializers.CharField(source='amenity.amenity_type', read_only=True)
    amenity_price_per_hour = serializers.DecimalField(source='amenity.price_per_hour', max_digits=10, decimal_places=2, read_only=True)
    amenity_security_deposit = serializers.DecimalField(source='amenity.security_deposit', max_digits=10, decimal_places=2, read_only=True)
    amenity_is_paid = serializers.BooleanField(source='amenity.is_paid', read_only=True)
    booked_by_name = serializers.CharField(source='booked_by.get_full_name', read_only=True)
    booked_by_building = serializers.CharField(source='booked_by.building_name', read_only=True, default='N/A')
    booked_by_unit = serializers.CharField(source='booked_by.unit_number', read_only=True, default='N/A')
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)
    is_upcoming = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    
    class Meta:
        model = AmenityBooking
        fields = '__all__'
        read_only_fields = ['id', 'booking_number', 'created_at', 'updated_at']
    
    def get_is_upcoming(self, obj):
        from django.utils import timezone
        return obj.booking_date >= timezone.now().date()
    
    def get_can_cancel(self, obj):
        from django.utils import timezone
        from datetime import timedelta
        
        if obj.status in ['cancelled', 'completed', 'no_show']:
            return False
        
        # Can cancel up to 24 hours before booking
        booking_datetime = timezone.datetime.combine(obj.booking_date, obj.start_time)
        booking_datetime = timezone.make_aware(booking_datetime)
        return booking_datetime - timezone.now() > timedelta(hours=24)


class AmenityBookingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AmenityBooking
        fields = ['amenity', 'booking_date', 'start_time', 'end_time', 'duration_hours',
                 'number_of_people', 'guest_names', 'purpose', 'special_requirements']
    
    def validate(self, data):
        # Validate booking time
        if data['start_time'] >= data['end_time']:
            raise serializers.ValidationError("End time must be after start time")
        
        # Check amenity availability
        amenity = data['amenity']
        if not amenity.is_bookable:
            raise serializers.ValidationError("This amenity is not bookable")

        request = self.context.get('request')
        user = request.user if request else None
        resident_roles = {'tenant', 'owner', 'tenant_vendor'}
        user_role = getattr(user, 'role', None)

        assigned_block_ids = list(amenity.block_assignments.values_list('block_id', flat=True))
        if user_role in resident_roles:
            if not user or not user.is_authenticated:
                raise serializers.ValidationError('Authentication required for booking.')

            if not assigned_block_ids:
                # Global amenities are bookable by everyone in the tenant
                pass
            else:
                units_qs = Unit.objects.filter(
                    building__name__iexact=(user.building_name or '').strip(),
                    unit_number__iexact=(user.unit_number or '').strip(),
                )
                user_block_ids = {
                    str(block_id)
                    for block_id in units_qs.exclude(floor_ref__block__isnull=True).values_list('floor_ref__block_id', flat=True)
                    if block_id
                }

                # Legacy fallback: map Unit.block text to Block model when floor_ref is missing.
                if not user_block_ids:
                    raw_block_names = [
                        str(name).strip()
                        for name in units_qs.exclude(block__isnull=True).exclude(block='').values_list('block', flat=True)
                        if str(name).strip()
                    ]
                    for block_name in raw_block_names:
                        mapped = Block.objects.filter(
                            building__name__iexact=(user.building_name or '').strip(),
                            name__iexact=block_name,
                        ).values_list('id', flat=True)
                        user_block_ids.update({str(block_id) for block_id in mapped})

                if not user_block_ids:
                    b_name = (user.building_name or '').strip()
                    u_num = (user.unit_number or '').strip()
                    if not b_name or not u_num:
                        raise serializers.ValidationError(
                            f'Your profile is missing building/unit info (Found: {b_name}/{u_num}). Update your profile to book.'
                        )
                    raise serializers.ValidationError(
                        f'No unit found for building "{b_name}" and unit "{u_num}", or it is not mapped to any block. Contact management.'
                    )

                allowed_block_ids = {str(block_id) for block_id in assigned_block_ids}
                if user_block_ids.isdisjoint(allowed_block_ids):
                    raise serializers.ValidationError(
                        'This amenity is restricted to selected blocks. Your block is not currently assigned.'
                    )
        
        # Check for conflicts
        from django.utils import timezone
        conflicts = AmenityBooking.objects.filter(
            amenity=amenity,
            booking_date=data['booking_date'],
            status__in=['pending', 'approved', 'confirmed', 'checked_in']
        ).filter(
            start_time__lt=data['end_time'],
            end_time__gt=data['start_time']
        )
        
        if conflicts.exists():
            raise serializers.ValidationError("This time slot is already booked")
        
        return data


class AmenityReviewSerializer(serializers.ModelSerializer):
    amenity_name = serializers.CharField(source='amenity.name', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = AmenityReview
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'helpful_count']


class AmenityMaintenanceSerializer(serializers.ModelSerializer):
    amenity_name = serializers.CharField(source='amenity.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    maintenance_type_display = serializers.CharField(source='get_maintenance_type_display', read_only=True)
    
    class Meta:
        model = AmenityMaintenance
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class AmenityUsageLogSerializer(serializers.ModelSerializer):
    amenity_name = serializers.CharField(source='amenity.name', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = AmenityUsageLog
        fields = '__all__'
        read_only_fields = ['id', 'created_at']


class AmenityRuleSerializer(serializers.ModelSerializer):
    amenity_name = serializers.CharField(source='amenity.name', read_only=True)
    
    class Meta:
        model = AmenityRule
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class AmenityDashboardSerializer(serializers.Serializer):
    total_amenities = serializers.IntegerField()
    available_amenities = serializers.IntegerField()
    total_bookings_today = serializers.IntegerField()
    active_bookings = serializers.IntegerField()
    pending_approvals = serializers.IntegerField()
    revenue_this_month = serializers.DecimalField(max_digits=12, decimal_places=2)