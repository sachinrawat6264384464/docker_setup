from rest_framework import serializers
from .models import APIKey, WebhookEndpoint, WebhookDelivery, APIGuide, APIChangelog


class APIKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = APIKey
        fields = ['id', 'name', 'prefix', 'scopes', 'is_active', 'last_used_at',
                  'expires_at', 'created_at']
        read_only_fields = ['id', 'prefix', 'last_used_at', 'created_at']


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = ['id', 'event_type', 'response_status', 'delivered_at',
                  'attempt_count', 'created_at']


class WebhookEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = ['id', 'url', 'events', 'is_active', 'last_delivery_at',
                  'failure_count', 'created_at']
        read_only_fields = ['id', 'last_delivery_at', 'failure_count', 'created_at']


class APIGuideSerializer(serializers.ModelSerializer):
    class Meta:
        model = APIGuide
        fields = ['id', 'title', 'slug', 'content', 'category', 'order']


class APIChangelogSerializer(serializers.ModelSerializer):
    class Meta:
        model = APIChangelog
        fields = ['id', 'version', 'release_date', 'summary', 'breaking_changes',
                  'new_features', 'deprecations', 'bug_fixes']
