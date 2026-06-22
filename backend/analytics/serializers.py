from rest_framework import serializers
from .models import AnalyticsEvent, DailyMetricSnapshot


class AnalyticsEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticsEvent
        fields = ['id', 'event_type', 'user', 'tenant_schema', 'object_type',
                  'object_id', 'metadata', 'device_type', 'created_at']
        read_only_fields = fields


class DailyMetricSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyMetricSnapshot
        fields = ['tenant_schema', 'date', 'metric_key', 'metric_value']
