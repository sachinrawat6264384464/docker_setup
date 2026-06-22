from rest_framework import serializers
from .models import DataExportRecord


class DataExportRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataExportRecord
        fields = [
            'id', 'requestedBy', 'dataTypes', 'format', 'status',
            'dateFrom', 'dateTo', 'createdAt', 'updatedAt', 'error_message'
        ]
        read_only_fields = [
            'id', 'requestedBy', 'status', 'createdAt', 'updatedAt', 'error_message'
        ]


class DataExportCreateSerializer(serializers.Serializer):
    dataTypes = serializers.ListField(
        child=serializers.CharField(), min_length=1
    )
    format = serializers.ChoiceField(choices=['csv', 'json', 'xlsx'], default='csv')
    dateFrom = serializers.DateField(required=False, allow_null=True)
    dateTo = serializers.DateField(required=False, allow_null=True)

    def to_internal_value(self, data):
        # Clean empty strings to None before validation runs
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        if 'dateFrom' in data and data['dateFrom'] == '':
            data['dateFrom'] = None
        if 'dateTo' in data and data['dateTo'] == '':
            data['dateTo'] = None
        return super().to_internal_value(data)

    def validate(self, attrs):
        from datetime import date
        today = date.today()
        date_from = attrs.get('dateFrom')
        date_to = attrs.get('dateTo')

        if date_from and date_from > today:
            raise serializers.ValidationError({"dateFrom": "From date cannot be in the future."})
        if date_to and date_to > today:
            raise serializers.ValidationError({"dateTo": "To date cannot be in the future."})
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError({"dateTo": "To date cannot be earlier than From date."})
        
        return attrs
