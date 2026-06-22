# inspections/serializers.py
from rest_framework import serializers
from .models import InspectionTemplate, Inspection, InspectionPhoto


class InspectionTemplateSerializer(serializers.ModelSerializer):
    inspection_count = serializers.SerializerMethodField()

    class Meta:
        model = InspectionTemplate
        fields = '__all__'
        read_only_fields = ['created_by']

    def get_inspection_count(self, obj):
        return obj.inspections.count()


class InspectionPhotoSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True, default='')

    class Meta:
        model = InspectionPhoto
        fields = '__all__'
        read_only_fields = ['uploaded_by']


class InspectionSerializer(serializers.ModelSerializer):
    photos = InspectionPhotoSerializer(many=True, read_only=True)
    inspector_name = serializers.CharField(source='inspector.get_full_name', read_only=True, default='')
    requested_by_name = serializers.CharField(source='requested_by.get_full_name', read_only=True, default='')
    template_name = serializers.CharField(source='template.name', read_only=True, default='')

    class Meta:
        model = Inspection
        fields = '__all__'
        read_only_fields = ['inspection_number', 'completed_date']


class InspectionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inspection
        fields = [
            'template', 'inspection_type', 'unit_id', 'building_id',
            'location_description', 'scheduled_date', 'inspector', 'notes',
        ]
        extra_kwargs = {
            'notes': {'source': 'overall_notes'},
        }
