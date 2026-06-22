# calendar/admin.py
from django.contrib import admin
from .models import CalendarAlert, AlertRecipient

@admin.register(CalendarAlert)
class CalendarAlertAdmin(admin.ModelAdmin):
    list_display = ['title', 'alert_type', 'priority', 'status', 'building', 'start_datetime', 'end_datetime', 'notify_tenants', 'created_at']
    list_filter = ['alert_type', 'priority', 'status', 'building', 'start_datetime', 'notify_tenants']
    search_fields = ['title', 'description', 'affected_area']
    ordering = ['-start_datetime']
    readonly_fields = ['created_by', 'notification_sent_at']
    
    fieldsets = (
        ('Alert Information', {
            'fields': ('title', 'description', 'alert_type', 'priority', 'status')
        }),
        ('Location', {
            'fields': ('building', 'affected_area')
        }),
        ('Schedule', {
            'fields': ('start_datetime', 'end_datetime', 'is_all_day')
        }),
        ('Notifications', {
            'fields': ('notify_tenants', 'notification_sent', 'notification_sent_at')
        }),
        ('Metadata', {
            'fields': ('created_by',)
        }),
    )

@admin.register(AlertRecipient)
class AlertRecipientAdmin(admin.ModelAdmin):
    list_display = ['alert', 'user', 'notification_sent', 'notification_sent_at', 'is_read', 'read_at', 'created_at']
    list_filter = ['notification_sent', 'is_read', 'created_at']
    search_fields = ['alert__title', 'user__first_name', 'user__last_name', 'user__email']
    ordering = ['-created_at']
    readonly_fields = ['notification_sent_at', 'read_at']
