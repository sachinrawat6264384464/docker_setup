# visitors/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import (
    VisitorType, Visitor, VisitorPass, VisitorLog,
    BlacklistedVisitor, VisitorFeedback
)


@admin.register(VisitorType)
class VisitorTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'requires_approval', 'max_duration_hours', 'color_badge', 'is_active', 'created_at']
    list_filter = ['requires_approval', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'color_code')
        }),
        ('Settings', {
            'fields': ('requires_approval', 'max_duration_hours', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )
    
    def color_badge(self, obj):
        return format_html(
            '<span style="background-color: {}; color: white; padding: 5px 10px; border-radius: 3px;">{}</span>',
            obj.color_code,
            obj.name
        )
    color_badge.short_description = 'Type'


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = [
        'visitor_number', 'full_name_display', 'phone', 'email',
        'company_name', 'visit_count', 'blacklist_status', 'last_visit'
    ]
    list_filter = ['is_blacklisted', 'gender', 'first_visit', 'last_visit']
    search_fields = [
        'visitor_number', 'first_name', 'last_name', 'email',
        'phone', 'company_name', 'vehicle_plate'
    ]
    readonly_fields = ['visitor_number', 'first_visit', 'last_visit', 'visit_count']
    date_hierarchy = 'last_visit'
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'visitor_number', 'first_name', 'last_name',
                'email', 'phone', 'gender'
            )
        }),
        ('Identification', {
            'fields': ('id_type', 'id_number', 'photo')
        }),
        ('Vehicle Information', {
            'fields': (
                'vehicle_make', 'vehicle_model',
                'vehicle_color', 'vehicle_plate'
            ),
            'classes': ('collapse',)
        }),
        ('Company Information', {
            'fields': ('company_name',),
            'classes': ('collapse',)
        }),
        ('Blacklist Status', {
            'fields': (
                'is_blacklisted', 'blacklist_reason',
                'blacklisted_at', 'blacklisted_by'
            )
        }),
        ('Visit Statistics', {
            'fields': ('first_visit', 'last_visit', 'visit_count')
        }),
    )
    
    def full_name_display(self, obj):
        return obj.get_full_name()
    full_name_display.short_description = 'Name'
    
    def blacklist_status(self, obj):
        if obj.is_blacklisted:
            return format_html(
                '<span style="background-color: #dc2626; color: white; padding: 3px 8px; border-radius: 3px;">BLACKLISTED</span>'
            )
        return format_html(
            '<span style="background-color: #16a34a; color: white; padding: 3px 8px; border-radius: 3px;">ACTIVE</span>'
        )
    blacklist_status.short_description = 'Status'
    
    actions = ['blacklist_visitors', 'remove_from_blacklist']
    
    def blacklist_visitors(self, request, queryset):
        count = 0
        for visitor in queryset:
            if not visitor.is_blacklisted:
                visitor.is_blacklisted = True
                visitor.blacklisted_at = timezone.now()
                visitor.blacklisted_by = request.user
                visitor.save()
                count += 1
        self.message_user(request, f'{count} visitors blacklisted successfully.')
    blacklist_visitors.short_description = 'Blacklist selected visitors'
    
    def remove_from_blacklist(self, request, queryset):
        queryset.update(is_blacklisted=False, blacklist_reason='')
        self.message_user(request, f'{queryset.count()} visitors removed from blacklist.')
    remove_from_blacklist.short_description = 'Remove from blacklist'


@admin.register(VisitorPass)
class VisitorPassAdmin(admin.ModelAdmin):
    list_display = [
        'pass_number', 'visitor_display', 'visitor_type', 'host',
        'building', 'unit_number', 'status_badge',
        'expected_arrival', 'expected_departure'
    ]
    list_filter = ['status', 'visitor_type', 'building', 'expected_arrival', 'created_at']
    search_fields = [
        'pass_number', 'visitor__first_name', 'visitor__last_name',
        'host__username', 'building', 'unit_number', 'access_code'
    ]
    readonly_fields = [
        'pass_number', 'access_code', 'qr_code', 'actual_arrival',
        'actual_departure', 'approved_at', 'rejected_at',
        'created_at', 'updated_at'
    ]
    date_hierarchy = 'expected_arrival'
    
    fieldsets = (
        ('Pass Information', {
            'fields': ('pass_number', 'access_code', 'status')
        }),
        ('Visitor Details', {
            'fields': ('visitor', 'visitor_type', 'host')
        }),
        ('Visit Details', {
            'fields': (
                'purpose', 'building', 'unit_number',
                'expected_arrival', 'expected_departure',
                'actual_arrival', 'actual_departure'
            )
        }),
        ('Approval', {
            'fields': (
                'approved_by', 'approved_at',
                'rejected_by', 'rejected_at', 'rejection_reason'
            )
        }),
        ('Security', {
            'fields': (
                'qr_code', 'security_notes',
                'can_drive_in', 'requires_escort'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def visitor_display(self, obj):
        return obj.visitor.get_full_name()
    visitor_display.short_description = 'Visitor'
    
    def status_badge(self, obj):
        colors = {
            'pending': '#f59e0b',
            'approved': '#3b82f6',
            'rejected': '#ef4444',
            'active': '#10b981',
            'expired': '#6b7280',
            'cancelled': '#6b7280',
            'completed': '#059669'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, '#gray'),
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'
    
    actions = ['approve_passes', 'reject_passes']
    
    def approve_passes(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='approved',
            approved_by=request.user,
            approved_at=timezone.now()
        )
        self.message_user(request, f'{count} passes approved successfully.')
    approve_passes.short_description = 'Approve selected passes'
    
    def reject_passes(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='rejected',
            rejected_by=request.user,
            rejected_at=timezone.now()
        )
        self.message_user(request, f'{count} passes rejected.')
    reject_passes.short_description = 'Reject selected passes'


@admin.register(VisitorLog)
class VisitorLogAdmin(admin.ModelAdmin):
    list_display = [
        'visitor_pass', 'log_type_badge', 'security_staff',
        'gate_number', 'health_status', 'timestamp'
    ]
    list_filter = ['log_type', 'health_screening_passed', 'timestamp']
    search_fields = [
        'visitor_pass__pass_number', 'visitor_pass__visitor__first_name',
        'visitor_pass__visitor__last_name', 'gate_number', 'entry_point'
    ]
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'
    
    fieldsets = (
        ('Log Information', {
            'fields': ('visitor_pass', 'log_type', 'security_staff', 'timestamp')
        }),
        ('Location', {
            'fields': ('gate_number', 'entry_point')
        }),
        ('Health Screening', {
            'fields': ('temperature', 'health_screening_passed')
        }),
        ('Additional Information', {
            'fields': ('notes', 'entry_photo')
        }),
    )
    
    def log_type_badge(self, obj):
        colors = {
            'check_in': '#10b981',
            'check_out': '#3b82f6',
            'denied_entry': '#ef4444',
            'alert': '#f59e0b'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.log_type, '#6b7280'),
            obj.get_log_type_display().upper()
        )
    log_type_badge.short_description = 'Type'
    
    def health_status(self, obj):
        if obj.log_type != 'check_in':
            return '-'
        
        if obj.health_screening_passed:
            return format_html(
                '<span style="color: #16a34a;">✓ Passed</span>'
            )
        else:
            return format_html(
                '<span style="color: #dc2626;">✗ Failed</span>'
            )
    health_status.short_description = 'Health Check'


@admin.register(BlacklistedVisitor)
class BlacklistedVisitorAdmin(admin.ModelAdmin):
    list_display = [
        'visitor', 'reason_preview', 'blacklisted_by',
        'blacklisted_at', 'status_display', 'expires_at'
    ]
    list_filter = ['is_permanent', 'blacklisted_at']
    search_fields = [
        'visitor__first_name', 'visitor__last_name',
        'reason', 'notes'
    ]
    readonly_fields = ['blacklisted_at']
    date_hierarchy = 'blacklisted_at'
    
    fieldsets = (
        ('Visitor Information', {
            'fields': ('visitor',)
        }),
        ('Blacklist Details', {
            'fields': ('reason', 'blacklisted_by', 'blacklisted_at')
        }),
        ('Expiration', {
            'fields': ('is_permanent', 'expires_at')
        }),
        ('Additional Notes', {
            'fields': ('notes',)
        }),
    )
    
    def reason_preview(self, obj):
        return obj.reason[:50] + '...' if len(obj.reason) > 50 else obj.reason
    reason_preview.short_description = 'Reason'
    
    def status_display(self, obj):
        if obj.is_active():
            return format_html(
                '<span style="background-color: #dc2626; color: white; padding: 3px 8px; border-radius: 3px;">ACTIVE</span>'
            )
        else:
            return format_html(
                '<span style="background-color: #6b7280; color: white; padding: 3px 8px; border-radius: 3px;">EXPIRED</span>'
            )
    status_display.short_description = 'Blacklist Status'


@admin.register(VisitorFeedback)
class VisitorFeedbackAdmin(admin.ModelAdmin):
    list_display = [
        'visitor_pass', 'rating_display', 'security_staff_rating',
        'process_ease_rating', 'would_recommend', 'submitted_at'
    ]
    list_filter = ['rating', 'would_recommend', 'submitted_at']
    search_fields = [
        'visitor_pass__visitor__first_name',
        'visitor_pass__visitor__last_name',
        'comments'
    ]
    readonly_fields = ['submitted_at']
    date_hierarchy = 'submitted_at'
    
    fieldsets = (
        ('Feedback Information', {
            'fields': ('visitor_pass', 'submitted_at')
        }),
        ('Ratings', {
            'fields': (
                'rating', 'security_staff_rating',
                'process_ease_rating'
            )
        }),
        ('Comments', {
            'fields': ('comments', 'would_recommend')
        }),
    )
    
    def rating_display(self, obj):
        stars = '⭐' * obj.rating
        color = '#16a34a' if obj.rating >= 4 else '#f59e0b' if obj.rating == 3 else '#dc2626'
        return format_html(
            '<span style="color: {};">{} ({})</span>',
            color, stars, obj.rating
        )
    rating_display.short_description = 'Overall Rating'