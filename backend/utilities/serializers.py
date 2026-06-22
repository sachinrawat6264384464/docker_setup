# utilities/serializers.py
from rest_framework import serializers
from .models import (
    UtilityType, UtilityBill, UtilityMeterReading,
    UtilityProvider, BuildingUtilityConnection,
    InsuranceProvider, BuildingInsurance
)

class UtilityTypeSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    active_bills_count = serializers.SerializerMethodField()
    
    class Meta:
        model = UtilityType
        fields = '__all__'
    
    def get_active_bills_count(self, obj):
        return obj.bills.filter(status='pending').count()

class UtilityTypeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UtilityType
        fields = '__all__'

class UtilityBillSerializer(serializers.ModelSerializer):
    utility_type_name = serializers.CharField(source='utility_type.name', read_only=True)
    utility_category = serializers.CharField(source='utility_type.category', read_only=True)
    unit_number = serializers.CharField(source='unit.unit_number', read_only=True)
    building_name = serializers.CharField(source='unit.building.name', read_only=True)
    tenant_name = serializers.CharField(source='tenant.get_full_name', read_only=True)
    tenant_email = serializers.CharField(source='tenant.email', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    days_until_due = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    
    class Meta:
        model = UtilityBill
        fields = '__all__'
    
    def get_days_until_due(self, obj):
        from django.utils import timezone
        if obj.status == 'pending':
            today = timezone.now().date()
            delta = obj.due_date - today
            return delta.days
        return None
    
    def get_is_overdue(self, obj):
        from django.utils import timezone
        if obj.status == 'pending':
            return obj.due_date < timezone.now().date()
        return False

class UtilityBillCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UtilityBill
        fields = '__all__'
        read_only_fields = ['bill_number', 'consumption', 'base_amount', 'total_amount']
    
    def validate(self, data):
        if data.get('current_reading', 0) < data.get('previous_reading', 0):
            raise serializers.ValidationError("Current reading cannot be less than previous reading")
        
        if data.get('billing_period_end') <= data.get('billing_period_start'):
            raise serializers.ValidationError("Billing period end must be after start")
        
        return data

class UtilityMeterReadingSerializer(serializers.ModelSerializer):
    utility_type_name = serializers.CharField(source='utility_type.name', read_only=True)
    unit_number = serializers.CharField(source='unit.unit_number', read_only=True)
    building_name = serializers.CharField(source='unit.building.name', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.get_full_name', read_only=True)
    reading_type_display = serializers.CharField(source='get_reading_type_display', read_only=True)
    
    class Meta:
        model = UtilityMeterReading
        fields = '__all__'

class UtilityMeterReadingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UtilityMeterReading
        fields = '__all__'
        read_only_fields = ['recorded_by']

class UtilityProviderSerializer(serializers.ModelSerializer):
    utility_category_display = serializers.CharField(source='get_utility_category_display', read_only=True)
    active_connections_count = serializers.SerializerMethodField()
    
    class Meta:
        model = UtilityProvider
        fields = '__all__'
    
    def get_active_connections_count(self, obj):
        return obj.building_connections.filter(is_active=True).count()

class UtilityProviderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UtilityProvider
        fields = '__all__'

class BuildingUtilityConnectionSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source='building.name', read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    utility_type_name = serializers.CharField(source='utility_type.name', read_only=True)
    utility_category = serializers.CharField(source='provider.utility_category', read_only=True)
    
    class Meta:
        model = BuildingUtilityConnection
        fields = '__all__'

class BuildingUtilityConnectionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuildingUtilityConnection
        fields = '__all__'
    
    def validate(self, data):
        existing = BuildingUtilityConnection.objects.filter(
            building=data.get('building'),
            provider=data.get('provider'),
            connection_number=data.get('connection_number')
        ).exclude(id=self.instance.id if self.instance else None)
        
        if existing.exists():
            raise serializers.ValidationError("Connection with this number already exists for this building and provider")
        
        return data

class UtilityConsumptionReportSerializer(serializers.Serializer):
    utility_type = serializers.CharField()
    unit_number = serializers.CharField()
    building_name = serializers.CharField()
    total_consumption = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    period_start = serializers.DateField()
    period_end = serializers.DateField()

class UtilityStatsSerializer(serializers.Serializer):
    total_utility_types = serializers.IntegerField()
    total_bills = serializers.IntegerField()
    pending_bills = serializers.IntegerField()
    paid_bills = serializers.IntegerField()
    overdue_bills = serializers.IntegerField()
    total_pending_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_collected_amount = serializers.DecimalField(max_digits=12, decimal_places=2)

class InsuranceProviderSerializer(serializers.ModelSerializer):
    insurance_type_display = serializers.CharField(source='get_insurance_type_display', read_only=True)
    building_count = serializers.SerializerMethodField()

    class Meta:
        model = InsuranceProvider
        fields = '__all__'

    def get_building_count(self, obj):
        return obj.building_insurances.filter(is_active=True).count()

class InsuranceProviderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceProvider
        fields = '__all__'

class BuildingInsuranceSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source='building.name', read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    provider_type = serializers.CharField(source='provider.insurance_type', read_only=True)

    class Meta:
        model = BuildingInsurance
        fields = '__all__'

class BuildingInsuranceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuildingInsurance
        fields = '__all__'

    def validate(self, data):
        if data.get('policy_end_date') and data.get('policy_start_date'):
            if data['policy_end_date'] <= data['policy_start_date']:
                raise serializers.ValidationError("Policy end date must be after start date")
        return data
