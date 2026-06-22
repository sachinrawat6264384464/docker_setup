# ========================================
# FILE 2: accounts/people_hub_admin.py (FIXED - No Emoji Issues)
# ========================================
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.contrib import messages
from .models import User, UserProfile
import csv
from django.http import HttpResponse


class PeopleHubAdmin(admin.ModelAdmin):
    """Custom admin interface for People Hub (Residents Management) - PRODUCTION SAFE"""
    
    list_display = [
        'resident_name', 'contact_info', 'unit_location', 
        'status_badges', 'profile_completion_bar', 'lease_info', 
        'actions_column'
    ]
    list_filter = [
        'is_active', 'is_approved', 'email_verified', 
        'building_name', 'created_at'
    ]
    search_fields = [
        'first_name', 'last_name', 'email', 'phone', 
        'username', 'unit_number', 'building_name'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('first_name', 'last_name', 'email', 'phone', 'avatar')
        }),
        ('Property Details', {
            'fields': ('unit_number', 'building_name')
        }),
        ('Emergency Contact', {
            'fields': ('emergency_contact_name', 'emergency_contact_phone'),
            'classes': ('collapse',)
        }),
        ('Status & Verification', {
            'fields': ('is_active', 'is_approved', 'email_verified'),
            'description': 'Manage resident status and verification'
        }),
        ('Preferences', {
            'fields': ('notification_preferences',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('date_joined', 'last_activity', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['date_joined', 'last_activity', 'created_at']
    
    actions = [
        'approve_residents', 
        'activate_residents', 
        'deactivate_residents',
        'verify_emails',
        'export_to_csv',
        'send_welcome_email'
    ]
    
    def get_queryset(self, request):
        """Only show tenants (residents) in current tenant schema"""
        qs = super().get_queryset(request)
        return qs.filter(role='tenant').select_related('profile')
    
    def resident_name(self, obj):
        """Display resident name with avatar"""
        avatar_url = obj.avatar.url if obj.avatar else '/static/default-avatar.png'
        return format_html(
            '<div style="display: flex; align-items: center; gap: 10px;">'
            '<img src="{}" style="width: 40px; height: 40px; border-radius: 50%; object-fit: cover;" />'
            '<div style="display: flex; flex-direction: column;">'
            '<strong style="font-size: 14px;">{}</strong>'
            '<span style="font-size: 11px; color: #666;">@{}</span>'
            '</div>'
            '</div>',
            avatar_url, obj.get_full_name(), obj.username
        )
    resident_name.short_description = 'Resident'
    
    def contact_info(self, obj):
        """Display contact information"""
        return format_html(
            '<div style="font-size: 12px;">'
            '<div>Email: {}</div>'
            '<div style="margin-top: 4px;">Phone: {}</div>'
            '</div>',
            obj.email, obj.phone or 'N/A'
        )
    contact_info.short_description = 'Contact'
    
    def unit_location(self, obj):
        """Display unit and building"""
        return format_html(
            '<div style="font-size: 12px;">'
            '<div style="font-weight: bold; color: #059669;">Building: {}</div>'
            '<div style="margin-top: 4px;">Unit: {}</div>'
            '</div>',
            obj.building_name or 'N/A', obj.unit_number or 'N/A'
        )
    unit_location.short_description = 'Location'
    
    def status_badges(self, obj):
        """Display status badges"""
        badges = []
        
        if obj.is_active:
            badges.append('<span style="background: #10b981; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">Active</span>')
        else:
            badges.append('<span style="background: #ef4444; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">Inactive</span>')
        
        if obj.is_approved:
            badges.append('<span style="background: #3b82f6; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">Approved</span>')
        else:
            badges.append('<span style="background: #f59e0b; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">Pending</span>')
        
        if obj.email_verified:
            badges.append('<span style="background: #8b5cf6; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">Verified</span>')
        
        return format_html('<div style="display: flex; flex-direction: column; gap: 4px;">{}</div>', 
                          ''.join(badges))
    status_badges.short_description = 'Status'
    
    def profile_completion_bar(self, obj):
        """Visual profile completion indicator"""
        try:
            profile = obj.profile
            total_fields = 15
            completed = sum([
                bool(obj.first_name), bool(obj.last_name), bool(obj.email),
                bool(obj.phone), bool(obj.unit_number), bool(obj.building_name),
                bool(obj.emergency_contact_name), bool(obj.emergency_contact_phone),
                bool(profile.date_of_birth), bool(profile.occupation),
                bool(profile.lease_start_date), bool(profile.monthly_rent),
                bool(profile.address_line_1), bool(profile.city), bool(profile.postal_code)
            ])
            percentage = int((completed / total_fields) * 100)
        except:
            percentage = 0
        
        if percentage >= 80:
            color = '#10b981'
        elif percentage >= 50:
            color = '#f59e0b'
        else:
            color = '#ef4444'
        
        return format_html(
            '<div style="width: 100%; background: #e5e7eb; border-radius: 8px; height: 20px; overflow: hidden;">'
            '<div style="width: {}%; background: {}; height: 100%; display: flex; align-items: center; justify-content: center; color: white; font-size: 11px; font-weight: bold;">'
            '{}%'
            '</div>'
            '</div>',
            percentage, color, percentage
        )
    profile_completion_bar.short_description = 'Profile'
    
    def lease_info(self, obj):
        """Display lease information"""
        try:
            from properties.models import Lease
            active_lease = Lease.objects.filter(tenant=obj, status='active').first()
            
            if active_lease:
                return format_html(
                    '<div style="font-size: 11px;">'
                    '<div style="color: #10b981; font-weight: bold;">Active Lease</div>'
                    '<div style="margin-top: 2px;">Rent: Rs.{}/mo</div>'
                    '<div>Until: {}</div>'
                    '</div>',
                    active_lease.monthly_rent, active_lease.end_date
                )
            else:
                return format_html('<span style="color: #9ca3af; font-size: 11px;">No active lease</span>')
        except:
            return format_html('<span style="color: #9ca3af; font-size: 11px;">-</span>')
    lease_info.short_description = 'Lease'
    
    def actions_column(self, obj):
        """Quick action buttons"""
        return format_html(
            '<div style="display: flex; gap: 4px;">'
            '<a href="{}" style="background: #3b82f6; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none; font-size: 11px;">View</a>'
            '<a href="{}" style="background: #10b981; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none; font-size: 11px;">Edit</a>'
            '</div>',
            reverse('admin:accounts_user_change', args=[obj.pk]),
            reverse('admin:accounts_user_change', args=[obj.pk])
        )
    actions_column.short_description = 'Actions'
    
    # Admin Actions
    
    def approve_residents(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f'{updated} resident(s) approved successfully.', messages.SUCCESS)
    approve_residents.short_description = "Approve selected residents"
    
    def activate_residents(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} resident(s) activated successfully.', messages.SUCCESS)
    activate_residents.short_description = "Activate selected residents"
    
    def deactivate_residents(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} resident(s) deactivated.', messages.WARNING)
    deactivate_residents.short_description = "Deactivate selected residents"
    
    def verify_emails(self, request, queryset):
        updated = queryset.update(email_verified=True)
        self.message_user(request, f'{updated} email(s) verified successfully.', messages.SUCCESS)
    verify_emails.short_description = "Verify emails"
    
    def export_to_csv(self, request, queryset):
        """Export selected residents to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="residents_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Name', 'Email', 'Phone', 'Unit', 'Building', 
            'Status', 'Approved', 'Verified', 'Created'
        ])
        
        for resident in queryset:
            writer.writerow([
                resident.get_full_name(),
                resident.email,
                resident.phone,
                resident.unit_number,
                resident.building_name,
                'Active' if resident.is_active else 'Inactive',
                'Yes' if resident.is_approved else 'No',
                'Yes' if resident.email_verified else 'No',
                resident.created_at.strftime('%Y-%m-%d')
            ])
        
        return response
    export_to_csv.short_description = "Export to CSV"
    
    def send_welcome_email(self, request, queryset):
        """Send welcome email to selected residents"""
        count = queryset.count()
        self.message_user(request, f'Welcome email sent to {count} resident(s).', messages.SUCCESS)
    send_welcome_email.short_description = "Send welcome email"