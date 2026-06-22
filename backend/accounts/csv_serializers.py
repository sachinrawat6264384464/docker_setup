# accounts/csv_serializers.py - CSV Related Serializers
from rest_framework import serializers
from .csv_models import CSVUpload, CSVRowResult, CSVTemplate

class CSVUploadSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True)
    file_url = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = CSVUpload
        fields = [
            'id', 'uploaded_by', 'uploaded_by_name', 'file', 'file_url',
            'original_filename', 'file_size', 'status', 'total_rows',
            'processed_rows', 'success_count', 'error_count', 'warning_count',
            'progress_percentage', 'success_rate', 'processing_started_at',
            'processing_completed_at', 'processing_time_seconds', 'summary',
            'errors', 'warnings', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'uploaded_by', 'file_size', 'status', 'total_rows',
            'processed_rows', 'success_count', 'error_count', 'warning_count',
            'processing_started_at', 'processing_completed_at',
            'processing_time_seconds', 'summary', 'errors', 'warnings',
            'created_at', 'updated_at'
        ]
    
    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None
    
    def get_progress_percentage(self, obj):
        if obj.total_rows > 0:
            return round((obj.processed_rows / obj.total_rows) * 100, 2)
        return 0

class CSVRowResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = CSVRowResult
        fields = [
            'id', 'row_number', 'result_type', 'raw_data', 'message',
            'details', 'created_user_id', 'created_building_id',
            'created_unit_id', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

class CSVTemplateSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    template_file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = CSVTemplate
        fields = [
            'id', 'name', 'template_type', 'description', 'required_columns',
            'optional_columns', 'column_descriptions', 'validation_rules',
            'template_file', 'template_file_url', 'is_active', 'created_by',
            'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']
    
    def get_template_file_url(self, obj):
        if obj.template_file:
            return obj.template_file.url
        return None

class CSVUploadCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CSVUpload
        fields = ['file', 'original_filename']
    
    def validate_file(self, value):
        # File type validation
        if not value.name.lower().endswith(('.csv', '.xlsx', '.xls')):
            raise serializers.ValidationError("Only CSV and Excel files are allowed")
        
        # File size validation (10MB)
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("File size too large. Maximum 10MB allowed")
        
        return value
    
    def create(self, validated_data):
        validated_data['uploaded_by'] = self.context['request'].user
        validated_data['file_size'] = validated_data['file'].size
        if not validated_data.get('original_filename'):
            validated_data['original_filename'] = validated_data['file'].name
        return super().create(validated_data)

class CSVProcessingStatsSerializer(serializers.Serializer):
    total_uploads = serializers.IntegerField()
    successful_uploads = serializers.IntegerField()
    failed_uploads = serializers.IntegerField()
    partial_uploads = serializers.IntegerField()
    processing_uploads = serializers.IntegerField()
    total_rows_processed = serializers.IntegerField()
    total_users_created = serializers.IntegerField()
    total_errors = serializers.IntegerField()
    recent_uploads_count = serializers.IntegerField()

class CSVValidationResultSerializer(serializers.Serializer):
    is_valid = serializers.BooleanField()
    errors = serializers.ListField(child=serializers.CharField())
    warnings = serializers.ListField(child=serializers.CharField())
    column_mapping = serializers.DictField()
    detected_columns = serializers.ListField(child=serializers.CharField())
    missing_columns = serializers.ListField(child=serializers.CharField())
    sample_data = serializers.ListField()

class BulkCSVActionSerializer(serializers.Serializer):
    upload_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True
    )
    action = serializers.ChoiceField(
        choices=['delete', 'retry'],
        write_only=True
    )
    
    def validate_upload_ids(self, value):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication required")
        
        # Check that all uploads belong to the current user
        uploads = CSVUpload.objects.filter(id__in=value, uploaded_by=request.user)
        if uploads.count() != len(value):
            raise serializers.ValidationError("Some upload IDs are invalid or don't belong to you")
        
        return value