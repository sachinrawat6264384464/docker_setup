# notifications/serializers.py
from rest_framework import serializers
from .models import (Notification, NotificationPreference, Announcement,
                     EmailTemplate, EmailLog, UnsubscribeRecord, EmailCampaign, SMSAlert)


class NotificationSerializer(serializers.ModelSerializer):
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    recipient_name = serializers.CharField(source='recipient.get_full_name', read_only=True)
    
    class Meta:
        model = Notification
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'read_at', 'sent_at']


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = '__all__'
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']


class AnnouncementSerializer(serializers.ModelSerializer):
    audience_type_display = serializers.CharField(source='get_audience_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    
    class Meta:
        model = Announcement
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'sent_count', 'read_count']


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ['id', 'name', 'slug', 'subject', 'html_body', 'plain_body',
                  'variables_list', 'category', 'is_active', 'created_at']


class EmailLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailLog
        fields = ['id', 'recipient_email', 'subject', 'status', 'tenant_schema',
                  'opened_at', 'clicked_at', 'created_at']


class UnsubscribeRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnsubscribeRecord
        fields = ['id', 'email', 'category', 'created_at']


class EmailCampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailCampaign
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'sent_count', 'open_count', 'click_count', 'status']


class SMSAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = SMSAlert
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'sent_count', 'status']