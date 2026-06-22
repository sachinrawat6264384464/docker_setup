# parking/serializers.py
from rest_framework import serializers
from .models import ParkingSlot, Vehicle, ParkingPass, ParkingEntry


class ParkingSlotSerializer(serializers.ModelSerializer):
    slot_type_display = serializers.CharField(source='get_slot_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = ParkingSlot
        fields = '__all__'

    def to_internal_value(self, data):
        mutable = data.copy()
        legacy_map = {'standard': 'car', 'compact': 'car'}
        slot_type = mutable.get('slot_type')
        if slot_type in legacy_map:
            mutable['slot_type'] = legacy_map[slot_type]
        return super().to_internal_value(mutable)


class VehicleSerializer(serializers.ModelSerializer):
    vehicle_type_display = serializers.CharField(source='get_vehicle_type_display', read_only=True)
    owner_name = serializers.CharField(source='owner.get_full_name', read_only=True)
    
    class Meta:
        model = Vehicle
        fields = '__all__'
        extra_kwargs = {
            'owner': {'required': False},
            'registration_number': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        if not attrs.get('registration_number'):
            attrs['registration_number'] = attrs.get('license_plate', '')
        return attrs


class ParkingPassSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    vehicle_details = VehicleSerializer(source='vehicle', read_only=True)
    
    class Meta:
        model = ParkingPass
        fields = '__all__'


class ParkingEntrySerializer(serializers.ModelSerializer):
    vehicle_details = VehicleSerializer(source='vehicle', read_only=True)
    
    class Meta:
        model = ParkingEntry
        fields = '__all__'