# notifications/admin.py
from django.contrib import admin
from .models import Notification, NotificationPreference, Announcement, EmailTemplate, EmailLog, UnsubscribeRecord


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'recipient', 'notification_type', 'priority', 'is_read', 'created_at']
    list_filter = ['notification_type', 'priority', 'is_read']
    search_fields = ['title', 'message']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'email_enabled', 'sms_enabled', 'push_enabled']


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['title', 'audience_type', 'is_published', 'created_by', 'created_at']
    list_filter = ['audience_type', 'is_published']
    search_fields = ['title', 'content']


admin.site.register(EmailTemplate)
admin.site.register(EmailLog)
admin.site.register(UnsubscribeRecord)