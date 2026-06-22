# reservations/serializers.py
from rest_framework import serializers
from .models import ReservableResource, Reservation


class ReservableResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReservableResource
        fields = '__all__'


class ReservationSerializer(serializers.ModelSerializer):
    resource_name = serializers.CharField(source='resource.name', read_only=True)
    reserved_by_name = serializers.CharField(source='reserved_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True, default='')
    has_conflict = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = '__all__'
        read_only_fields = [
            'reservation_number', 'reserved_by', 'approved_by', 'total_cost',
            'checked_in_at', 'checked_out_at', 'cancelled_at',
        ]

    def get_has_conflict(self, obj):
        return obj.has_conflict()


class ReservationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = ['resource', 'start_time', 'end_time', 'guest_count', 'guest_names', 'purpose', 'notes']

    def validate(self, attrs):
        if attrs['start_time'] >= attrs['end_time']:
            raise serializers.ValidationError({'end_time': 'End time must be after start time.'})

        # Check for conflicts
        resource = attrs['resource']
        conflict = Reservation.objects.filter(
            resource=resource,
            status__in=['approved', 'checked_in', 'pending'],
            start_time__lt=attrs['end_time'],
            end_time__gt=attrs['start_time'],
        ).exists()
        if conflict:
            raise serializers.ValidationError('This time slot conflicts with an existing reservation.')

        # Check resource availability
        if not resource.is_available:
            raise serializers.ValidationError('This resource is currently unavailable.')

        return attrs
