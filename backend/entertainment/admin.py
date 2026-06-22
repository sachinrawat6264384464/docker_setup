# ========================================
# FILE 2: entertainment/admin.py
# ========================================
from django.contrib import admin
from django.utils.html import format_html
from .models import Event, EventRegistration, Club


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'event_type', 'start_date', 'start_time',
        'status_badge', 'attendance_display', 'venue'
    ]
    list_filter = ['event_type', 'status', 'start_date', 'is_paid']
    search_fields = ['title', 'description', 'venue', 'organized_by']
    readonly_fields = ['created_at', 'updated_at', 'current_attendees']
    date_hierarchy = 'start_date'
    
    fieldsets = (
        ('Event Information', {
            'fields': ('title', 'description', 'event_type', 'status')
        }),
        ('Schedule', {
            'fields': (
                ('start_date', 'end_date'),
                ('start_time', 'end_time')
            )
        }),
        ('Location', {
            'fields': ('venue', 'building', 'location_details')
        }),
        ('Capacity', {
            'fields': (('max_attendees', 'current_attendees'),)
        }),
        ('Registration', {
            'fields': (
                'requires_registration', 'registration_deadline',
                'is_paid', 'ticket_price'
            )
        }),
        ('Media', {
            'fields': ('banner_image', 'images'),
            'classes': ('collapse',)
        }),
        ('Organization', {
            'fields': (
                'organized_by', 'contact_person',
                'contact_phone', 'contact_email'
            )
        }),
        ('Additional Details', {
            'fields': ('features', 'requirements', 'rules'),
            'classes': ('collapse',)
        }),
        ('Management', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )
    
    def status_badge(self, obj):
        colors = {
            'draft': '#6b7280',
            'published': '#3b82f6',
            'ongoing': '#10b981',
            'completed': '#059669',
            'cancelled': '#ef4444'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, '#gray'),
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'
    
    def attendance_display(self, obj):
        percentage = (obj.current_attendees / obj.max_attendees * 100) if obj.max_attendees > 0 else 0
        color = '#16a34a' if percentage < 80 else '#f59e0b' if percentage < 100 else '#dc2626'
        
        return format_html(
            '<span style="color: {};">{}/{} ({:.0f}%)</span>',
            color, obj.current_attendees, obj.max_attendees, percentage
        )
    attendance_display.short_description = 'Attendance'


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = [
        'event', 'user', 'number_of_guests',
        'status_badge', 'payment_status',
        'checked_in_at', 'created_at'
    ]
    list_filter = ['status', 'payment_status', 'created_at']
    search_fields = [
        'event__title', 'user__username', 'user__first_name',
        'user__last_name', 'payment_reference'
    ]
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Registration Information', {
            'fields': ('event', 'user', 'status')
        }),
        ('Guest Details', {
            'fields': ('number_of_guests', 'guest_names')
        }),
        ('Payment', {
            'fields': ('payment_status', 'payment_reference', 'amount_paid')
        }),
        ('Check-in', {
            'fields': ('checked_in_at',)
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def status_badge(self, obj):
        colors = {
            'registered': '#3b82f6',
            'confirmed': '#10b981',
            'attended': '#059669',
            'cancelled': '#ef4444',
            'no_show': '#6b7280'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, '#gray'),
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'category', 'admin', 'member_count_display',
        'is_active', 'created_at'
    ]
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['name', 'description', 'admin__username']
    readonly_fields = ['created_at', 'updated_at']
    filter_horizontal = ['members']
    
    fieldsets = (
        ('Club Information', {
            'fields': ('name', 'description', 'category', 'logo')
        }),
        ('Leadership', {
            'fields': ('admin',)
        }),
        ('Members', {
            'fields': ('members', 'max_members')
        }),
        ('Schedule', {
            'fields': ('meeting_schedule', 'meeting_location')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def member_count_display(self, obj):
        count = obj.member_count()
        percentage = (count / obj.max_members * 100) if obj.max_members > 0 else 0
        color = '#16a34a' if percentage < 80 else '#f59e0b' if percentage < 100 else '#dc2626'
        
        return format_html(
            '<span style="color: {};">{}/{} ({:.0f}%)</span>',
            color, count, obj.max_members, percentage
        )
    member_count_display.short_description = 'Members'