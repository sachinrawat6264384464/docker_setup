# accounts/admin.py - COMPLETE SECURE VERSION
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.db import models, connection
from django.forms import Textarea
from django import forms
from django.contrib.auth.forms import UserCreationForm

from django.utils import timezone
from django.core.exceptions import PermissionDenied
from .models import User, UserProfile, Role, Permission, UserRole, ActivityLog
from .csv_admin import CSVUploadAdmin, CSVRowResultAdmin, CSVTemplateAdmin
from .csv_models import CSVUpload, CSVRowResult, CSVTemplate


class UserAdminForm(forms.ModelForm):
    """Custom form with role restrictions based on current user's permissions"""
    
    class Meta:
        model = User
        fields = [
        'username', 'password', 'email', 'first_name', 'last_name',
        'role', 'tenant_id', 'unit_number', 'building_name',
        'phone', 'emergency_contact_name', 'emergency_contact_phone',
        'is_active', 'is_approved', 'email_verified',
        'avatar', ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = getattr(self, '_request', None)
        
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            current_user = request.user
            
            # Define role hierarchy and what each role can assign
            if current_user.is_master_admin:
                # Master admin can assign any role except master_admin
                allowed_roles = [
                    ('super_admin', 'Super Admin'),
                    ('platform_member', 'Platform Member'),
                    ('facility_manager', 'Facility Manager'),
                    ('property_staff', 'Property Staff'),
                    ('owner', 'Property Owner'),
                    ('tenant_vendor', 'Tenant Vendor'),
                    ('tenant', 'Tenant/Resident'),
                    ('maintenance_staff', 'Maintenance Staff'),
                    ('security_guard', 'Security Guard'),
                ]
            elif current_user.is_super_admin:
                # Super admin can assign facility manager and below
                allowed_roles = [
                    ('platform_member', 'Platform Member'),
                    ('facility_manager', 'Facility Manager'),
                    ('property_staff', 'Property Staff'),
                    ('owner', 'Property Owner'),
                    ('tenant_vendor', 'Tenant Vendor'),
                    ('tenant', 'Tenant/Resident'),
                    ('maintenance_staff', 'Maintenance Staff'),
                    ('security_guard', 'Security Guard'),
                ]
            elif current_user.is_facility_manager:
                # Facility manager can only assign property staff and below
                allowed_roles = [
                    ('property_staff', 'Property Staff'),
                    ('owner', 'Property Owner'),
                    ('tenant_vendor', 'Tenant Vendor'),
                    ('tenant', 'Tenant/Resident'),
                    ('maintenance_staff', 'Maintenance Staff'),
                    ('security_guard', 'Security Guard'),
                ]
            elif current_user.is_property_staff:
                # Property staff can only assign tenant role
                allowed_roles = [
                    ('tenant', 'Tenant/Resident'),
                ]
            else:
                # Default: can only assign tenant
                allowed_roles = [
                    ('tenant', 'Tenant/Resident'),
                ]
            
            # Update role field choices
            self.fields['role'].choices = allowed_roles
            #self.fields['notification_preferences'].required = False
            # Restrict sensitive fields for non-system admins
            if not current_user.is_system_admin:
                sensitive_fields = ['is_superuser', 'is_staff', 'groups', 'user_permissions']
                for field_name in sensitive_fields:
                    if field_name in self.fields:
                        self.fields[field_name].widget.attrs['readonly'] = True
                        self.fields[field_name].help_text = "Only system administrators can modify this field"
        
        if 'notification_preferences' in self.fields:
            del self.fields['notification_preferences']

    def clean_role(self):
        """Validate role assignment permissions"""
        role = self.cleaned_data.get('role')
        request = getattr(self, '_request', None)
        
        if not request or not request.user.is_authenticated:
            raise forms.ValidationError("Authentication required")
        
        current_user = request.user
        
        # Define what roles each user type can assign
        role_permissions = {
            'master_admin': ['super_admin', 'platform_member', 'facility_manager', 'property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
            'super_admin': ['platform_member', 'facility_manager', 'property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
            'facility_manager': ['property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
            'property_staff': ['tenant'],
        }
        
        allowed_roles = role_permissions.get(current_user.role, ['tenant'])
        
        if role not in allowed_roles:
            raise forms.ValidationError(f"You don't have permission to assign the role '{role}'. You can only assign: {', '.join(allowed_roles)}")
        
        return role
    
    def clean_is_superuser(self):
        """Prevent non-system admins from granting superuser status"""
        is_superuser = self.cleaned_data.get('is_superuser')
        request = getattr(self, '_request', None)
        
        if is_superuser and request and not request.user.is_system_admin:
            raise forms.ValidationError("Only system administrators can grant superuser status")
        
        return is_superuser

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserAdminForm
    add_form = UserCreationForm
    exclude = ('notification_preferences',)
    list_display = [
        'username', 'email', 'full_name_display', 'role', 
        'tenant_display', 'status_display', 'last_activity'
    ]
    list_filter = ['role', 'is_active', 'is_approved', 'email_verified', 'created_at']
    search_fields = ['username', 'email', 'first_name', 'last_name', 'phone', 'unit_number']
    ordering = ['-created_at']
    add_fieldsets = (
        ('Basic Information', {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'email', 'first_name', 'last_name'),
        }),
        ('Role Assignment', {
            'fields': ('role',),
        }),
    )
    def get_form(self, request, obj=None, **kwargs):
        """Pass request to form for role validation"""
        if obj is None:
        # Add page
            kwargs['form'] = getattr(self, 'add_form', UserCreationForm)
        else:
        # Change page
            kwargs['form'] = getattr(self, 'form', UserAdminForm)
        form = super().get_form(request, obj, **kwargs)
        form._request = request
        return form
    
    def get_fieldsets(self, request, obj=None):
        """Dynamic fieldsets based on user permissions"""
        if request.user.is_system_admin:
            # System admins see all fields
            return (
                ('Basic Information', {
                    'fields': ('username', 'password', 'email', 'first_name', 'last_name')
                }),
                ('Role & Tenant', {
                    'fields': ('role', 'tenant_id'),
                    'description': 'Role assignment is restricted based on your permissions'
                }),
                ('Property Information', {
                    'fields': ('unit_number', 'building_name'),
                    'classes': ('collapse',)
                }),
                ('Contact Information', {
                    'fields': ('phone', 'emergency_contact_name', 'emergency_contact_phone'),
                    'classes': ('collapse',)
                }),
                ('Status & Verification', {
                    'fields': ('is_active', 'is_approved', 'email_verified')
                }),
                ('System Permissions', {
                    'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions'),
                    'classes': ('collapse',),
                    'description': 'System-level permissions - use with caution'
                }),
                ('Preferences', {
                    'fields': ( 'avatar',),
                    'classes': ('collapse',)
                }),
                ('Security', {
                    'fields': ('otp_attempts', 'otp_blocked_until'),
                    'classes': ('collapse',)
                }),
                ('Timestamps', {
                    'fields': ('last_login', 'date_joined', 'last_activity', 'created_at', 'updated_at'),
                    'classes': ('collapse',)
                }),
            )
        else:
            # Non-system admins see limited fields
            return (
                ('Basic Information', {
                    'fields': ('username', 'password', 'email', 'first_name', 'last_name')
                }),
                ('Role & Property', {
                    'fields': ('role', 'unit_number', 'building_name'),
                    'description': f'You can assign roles: {self._get_allowed_roles_display(request.user)}'
                }),
                ('Contact Information', {
                    'fields': ('phone', 'emergency_contact_name', 'emergency_contact_phone'),
                }),
                ('Status', {
                    'fields': ('is_active', 'is_approved', 'email_verified')
                }),
                ('Timestamps', {
                    'fields': ('created_at', 'updated_at'),
                    'classes': ('collapse',)
                }),
            )
    
    def _get_allowed_roles_display(self, user):
        """Get display text for allowed roles"""
        role_permissions = {
            'master_admin': 'Platform Member, Super Admin, and tenant roles',
            'super_admin': 'Platform Member, Facility Manager, and tenant roles',
            'facility_manager': 'Property Staff, Owner, Tenant Vendor, Tenant, Maintenance, Security',
            'property_staff': 'Tenant only',
        }
        return role_permissions.get(user.role, 'Tenant only')
    
    def get_readonly_fields(self, request, obj=None):
        """Dynamic readonly fields based on user permissions"""
        readonly = ['date_joined', 'last_login', 'created_at', 'updated_at', 'last_activity']
        
        if not request.user.is_system_admin:
            readonly.extend(['tenant_id', 'is_staff', 'is_superuser', 'groups', 'user_permissions', 'otp_attempts', 'otp_blocked_until'])
        
        return readonly
    
    def full_name_display(self, obj):
        """Display full name with fallback"""
        full_name = obj.get_full_name()
        return full_name if full_name.strip() else obj.username
    full_name_display.short_description = 'Full Name'
    
    def tenant_display(self, obj):
        """Display tenant information with security considerations"""
        if obj.tenant_id:
            try:
                if hasattr(connection, 'tenant') and connection.tenant.schema_name == 'public':
                    from tenants.models import Client
                    tenant = Client.objects.filter(schema_name=obj.tenant_id).first()
                    if tenant:
                        return format_html(
                            '<span style="color: #0066cc; font-weight: bold;">{}</span>',
                            tenant.name
                        )
                return format_html('<span style="color: #cc6600;">{}</span>', obj.tenant_id)
            except:
                return obj.tenant_id
        return format_html('<span style="color: #999;">System User</span>')
    tenant_display.short_description = 'Tenant'
    
    def status_display(self, obj):
        """Display user status with security indicators"""
        statuses = []
        
        if obj.is_active:
            statuses.append('<span style="color: green;">✓ Active</span>')
        else:
            statuses.append('<span style="color: red;">✗ Inactive</span>')
            
        if obj.is_approved:
            statuses.append('<span style="color: green;">✓ Approved</span>')
        else:
            statuses.append('<span style="color: orange;">⚠ Pending</span>')
            
        if obj.email_verified:
            statuses.append('<span style="color: green;">✓ Verified</span>')
        else:
            statuses.append('<span style="color: red;">✗ Unverified</span>')
        
        # Security indicators
        if obj.is_superuser:
            statuses.append('<span style="color: red; font-weight: bold;">⚡ SUPERUSER</span>')
        
        if obj.role in ['master_admin', 'super_admin']:
            statuses.append('<span style="color: purple; font-weight: bold;">🔒 SYSTEM</span>')
        
        return format_html(' | '.join(statuses))
    status_display.short_description = 'Status'
    
    def get_queryset(self, request):
        """Filter users based on permissions and schema"""
        qs = super().get_queryset(request)
        
        # In public schema
        if hasattr(connection, 'tenant') and connection.tenant.schema_name == 'public':
            if request.user.is_superuser:
                return qs  # Superuser sees all
            elif request.user.is_master_admin:
                return qs.exclude(role='master_admin')  # Master admin sees all except other master admins
            else:
                return qs.filter(role__in=['super_admin'])  # Others see limited
        
        # In tenant schema - apply strict filtering
        current_user = request.user
        
        if current_user.is_facility_manager:
            # Facility managers see all tenant users except system admins
            return qs.exclude(role__in=['master_admin', 'super_admin'])
        elif current_user.is_property_staff:
            # Property staff see tenants and service staff only
            return qs.filter(role__in=['tenant', 'maintenance_staff', 'security_guard', 'tenant_vendor'])
        else:
            # Default: users see only themselves
            return qs.filter(id=current_user.id)
    
    def has_change_permission(self, request, obj=None):
        """Strict permission checking for user modifications"""
        if obj is None:
            return True  # Allow access to change list
        
        current_user = request.user
        
        # Users can always edit themselves (limited fields)
        if obj == current_user:
            return True
        
        # System admins have broad permissions but with restrictions
        if current_user.is_system_admin:
            # Master admin can edit anyone except other master admins
            if obj.is_master_admin and not current_user.is_master_admin:
                return False
            return True
        
        # Facility managers can edit users in their tenant (except system admins)
        if current_user.is_facility_manager:
            return (
                obj.tenant_id == current_user.tenant_id and
                not obj.is_system_admin and
                obj.role not in ['master_admin', 'super_admin']
            )
        
        # Property staff can edit tenants and service staff in their tenant
        if current_user.is_property_staff:
            return (
                obj.tenant_id == current_user.tenant_id and
                obj.role in ['tenant', 'maintenance_staff', 'security_guard', 'tenant_vendor']
            )
        
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Strict delete permissions"""
        if obj is None:
            return False
        
        current_user = request.user
        
        # Only system admins can delete users, with restrictions
        if current_user.is_system_admin:
            # Cannot delete other master admins or superusers
            if obj.is_master_admin or (obj.is_superuser and not current_user.is_master_admin):
                return False
            return True
        
        return False
    
    def has_add_permission(self, request):
        """Control who can add users"""
        return request.user.can_manage_property
    
    def save_model(self, request, obj, form, change):
        """Custom save logic with security checks"""
        # Set tenant_id for new users in tenant schema
        if not change and hasattr(connection, 'tenant'):
            if connection.tenant.schema_name != 'public':
                obj.tenant_id = connection.tenant.schema_name
        
        # Security check: prevent privilege escalation
        if change and hasattr(form, 'cleaned_data'):
            old_obj = User.objects.get(pk=obj.pk)
            
            # Prevent role escalation beyond permissions
            if old_obj.role != obj.role:
                if not request.user.can_assign_role(obj.role):
                    raise PermissionDenied(f"You cannot assign the role '{obj.role}'")
        
        super().save_model(request, obj, form, change)
        
        # Log the action
        ActivityLog.objects.create(
            user=request.user,
            action='user_modified' if change else 'user_created',
            description=f'{"Modified" if change else "Created"} user {obj.username} with role {obj.role}',
            affected_user=obj,
            tenant_schema=getattr(connection, 'schema_name', 'unknown')
        )
    
    def get_actions(self, request):
        """Filter available actions based on permissions"""
        actions = super().get_actions(request)
        
        # Only facility managers and above can perform bulk actions
        if not request.user.can_manage_property:
            return {}
        
        return actions
    
    actions = ['approve_users', 'activate_users', 'deactivate_users', 'verify_emails']
    
    def approve_users(self, request, queryset):
        """Bulk approve users with permission checks"""
        updated = 0
        for user in queryset:
            if self.has_change_permission(request, user) and not user.is_system_admin:
                user.is_approved = True
                user.save()
                updated += 1
        self.message_user(request, f'Approved {updated} users.')
    approve_users.short_description = "Approve selected users"
    
    def activate_users(self, request, queryset):
        """Bulk activate users with permission checks"""
        updated = 0
        for user in queryset:
            if self.has_change_permission(request, user):
                user.is_active = True
                user.save()
                updated += 1
        self.message_user(request, f'Activated {updated} users.')
    activate_users.short_description = "Activate selected users"
    
    def deactivate_users(self, request, queryset):
        """Bulk deactivate users with permission checks"""
        updated = 0
        for user in queryset:
            if self.has_change_permission(request, user) and user != request.user:
                user.is_active = False
                user.save()
                updated += 1
        self.message_user(request, f'Deactivated {updated} users.')
    deactivate_users.short_description = "Deactivate selected users"
    
    def verify_emails(self, request, queryset):
        """Bulk verify emails with permission checks"""
        updated = 0
        for user in queryset:
            if self.has_change_permission(request, user):
                user.email_verified = True
                user.save()
                updated += 1
        self.message_user(request, f'Verified emails for {updated} users.')
    verify_emails.short_description = "Verify emails for selected users"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'user_role',  'lease_dates', 
        'monthly_rent', 'household_size', 'has_pets', 'vehicle_count', #'notification_summary',
    ]
    list_filter = ['has_pets', 'gender', 'country', 'lease_start_date']
    search_fields = [
        'user__username', 'user__email', 'user__first_name', 'user__last_name',
        'occupation', 'employee_id'
    ]
    autocomplete_fields = ['user', 'supervisor']
    readonly_fields = ['created_at', 'updated_at',] #'notification_preferences_display'
    
    fieldsets = (
        ('👤 User', {
            'fields': ('user',)
        }),
        ('📋 Personal Information', {
            'fields': ('date_of_birth', 'gender', 'occupation', 'bio')
        }),
        ('📍 Address', {
            'fields': ('address_line_1', 'address_line_2', 'city', 'state', 'postal_code', 'country'),
            'classes': ('collapse',)
        }),
        ('📄 Lease Information', {
            'fields': ('lease_start_date', 'lease_end_date', 'monthly_rent', 'security_deposit'),
            'description': 'Lease and rental details for this resident'
        }),
        ('🏠 Household Details', {
            'fields': ('household_size', 'has_pets', 'pet_details'),
            'classes': ('collapse',)
        }),
        ('🚗 Vehicle Information', {
            'fields': ('vehicle_count', 'vehicle_details'),
            'classes': ('collapse',)
        }),
        ('💼 Work Information', {
            'fields': ('employee_id', 'department', 'supervisor'),
            'classes': ('collapse',),
            'description': 'For property staff members only'
        }),
        ('🆘 Emergency Information', {
            'fields': ('medical_conditions', 'insurance_provider', 'insurance_policy_number'),
            'classes': ('collapse',),
            'description': 'Medical and insurance information for emergencies'
        }),
        ('📅 Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    formfield_overrides = {
        models.JSONField: {'widget': Textarea(attrs={'rows': 20, 'cols': 80})},
        models.TextField: {'widget': Textarea(attrs={'rows': 4, 'cols': 80})},
    }
    
    # Custom display methods
    
    def user_role(self, obj):
        """Display user role with color coding"""
        role = obj.user.role
        colors = {
            'master_admin': '#dc3545',
            'super_admin': '#fd7e14',
            'platform_member': '#0b7285',
            'facility_manager': '#28a745',
            'property_staff': '#17a2b8',
            'owner': '#495057',
            'tenant_vendor': '#9c36b5',
            'tenant': '#6c757d',
            'maintenance_staff': '#ffc107',
            'security_guard': '#6610f2',
        }
        color = colors.get(role, '#6c757d')
        display = obj.user.get_role_display()
        
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            color, display
        )
    user_role.short_description = 'Role'
    
    # def notification_summary(self, obj):
    #     """Display notification preferences summary in list"""
    #     if not obj.notification_preferences:
    #         return format_html(
    #             '<span style="color: #dc3545; font-size: 18px;" title="Not configured">❌</span>'
    #         )
        
    #     prefs = obj.notification_preferences
    #     email_enabled = prefs.get('email', {}).get('enabled', False)
    #     sms_enabled = prefs.get('sms', {}).get('enabled', False)
    #     push_enabled = prefs.get('push', {}).get('enabled', False)
        
    #     badges = []
    #     if email_enabled:
    #         badges.append('📧')
    #     if sms_enabled:
    #         badges.append('📱')
    #     if push_enabled:
    #         badges.append('🔔')
        
    #     if badges:
    #         return format_html(
    #             '<span style="font-size: 16px;" title="Enabled channels">{}</span>',
    #             ' '.join(badges)
    #         )
    #     return format_html(
    #         '<span style="color: #6c757d; font-size: 18px;" title="All disabled">🔕</span>'
    #     )
    # notification_summary.short_description = 'Notifications'
    
    # def notification_preferences_display(self, obj):
    #     """Display detailed notification preferences in a nice format"""
    #     if not obj.notification_preferences:
    #         return format_html(
    #             '<div style="padding: 15px; background: #fff3cd; border-left: 4px solid #ffc107; '
    #             'border-radius: 4px; margin: 10px 0;">'
    #             '<strong style="color: #856404;">⚠️ Not Configured</strong><br>'
    #             'Notification preferences have not been set up for this user.<br><br>'
    #             '<em>Default preferences will be automatically applied on next login.</em>'
    #             '</div>'
    #         )
        
    #     prefs = obj.notification_preferences
        
    #     html = '<div style="background: #f8f9fa; padding: 15px; border-radius: 8px; font-family: monospace;">'
        
    #     # Email Section
    #     email = prefs.get('email', {})
    #     email_status = '✅ Enabled' if email.get('enabled') else '❌ Disabled'
    #     html += f'<div style="margin-bottom: 15px;">'
    #     html += f'<strong style="font-size: 14px;">📧 Email Notifications: {email_status}</strong><br>'
    #     if email.get('enabled'):
    #         html += '<div style="margin-left: 20px; margin-top: 5px; font-size: 12px;">'
    #         html += f"• Maintenance Updates: {'✅' if email.get('maintenance_updates') else '❌'}<br>"
    #         html += f"• Payment Reminders: {'✅' if email.get('payment_reminders') else '❌'}<br>"
    #         html += f"• Payment Receipts: {'✅' if email.get('payment_receipts') else '❌'}<br>"
    #         html += f"• Announcements: {'✅' if email.get('announcements') else '❌'}<br>"
    #         html += f"• Security Alerts: {'✅' if email.get('security_alerts') else '❌'}<br>"
    #         html += f"• Account Activity: {'✅' if email.get('account_activity') else '❌'}<br>"
    #         html += f"• Monthly Statements: {'✅' if email.get('monthly_statements') else '❌'}"
    #         html += '</div>'
    #     html += '</div>'
        
    #     # SMS Section
    #     sms = prefs.get('sms', {})
    #     sms_status = '✅ Enabled' if sms.get('enabled') else '❌ Disabled'
    #     html += f'<div style="margin-bottom: 15px;">'
    #     html += f'<strong style="font-size: 14px;">📱 SMS Notifications: {sms_status}</strong><br>'
    #     if sms.get('enabled'):
    #         html += '<div style="margin-left: 20px; margin-top: 5px; font-size: 12px;">'
    #         html += f"• Payment Due: {'✅' if sms.get('payment_due') else '❌'}<br>"
    #         html += f"• Urgent Maintenance: {'✅' if sms.get('maintenance_urgent') else '❌'}<br>"
    #         html += f"• Security Alerts: {'✅' if sms.get('security_alerts') else '❌'}<br>"
    #         html += f"• OTP Codes: ✅ (Always enabled)"
    #         html += '</div>'
    #     html += '</div>'
        
    #     # Push Section
    #     push = prefs.get('push', {})
    #     push_status = '✅ Enabled' if push.get('enabled') else '❌ Disabled'
    #     html += f'<div style="margin-bottom: 15px;">'
    #     html += f'<strong style="font-size: 14px;">🔔 Push Notifications: {push_status}</strong><br>'
    #     if push.get('enabled'):
    #         html += '<div style="margin-left: 20px; margin-top: 5px; font-size: 12px;">'
    #         html += f"• Maintenance Updates: {'✅' if push.get('maintenance_updates') else '❌'}<br>"
    #         html += f"• Payment Reminders: {'✅' if push.get('payment_reminders') else '❌'}<br>"
    #         html += f"• Announcements: {'✅' if push.get('announcements') else '❌'}<br>"
    #         html += f"• Chat Messages: {'✅' if push.get('chat_messages') else '❌'}<br>"
    #         html += f"• Amenity Bookings: {'✅' if push.get('amenity_bookings') else '❌'}<br>"
    #         html += f"• Visitor Alerts: {'✅' if push.get('visitor_alerts') else '❌'}<br>"
    #         html += f"• Package Delivery: {'✅' if push.get('package_delivery') else '❌'}"
    #         html += '</div>'
    #     html += '</div>'
        
    #     # In-App Section
    #     in_app = prefs.get('in_app', {})
    #     in_app_status = '✅ Enabled' if in_app.get('enabled') else '❌ Disabled'
    #     html += f'<div style="margin-bottom: 15px;">'
    #     html += f'<strong style="font-size: 14px;">💬 In-App Notifications: {in_app_status}</strong><br>'
    #     if in_app.get('enabled'):
    #         html += '<div style="margin-left: 20px; margin-top: 5px; font-size: 12px;">'
    #         html += f"• All Activities: {'✅' if in_app.get('all_activities') else '❌'}"
    #         html += '</div>'
    #     html += '</div>'
        
    #     # Frequency Settings
    #     frequency = prefs.get('frequency', {})
    #     html += f'<div style="margin-bottom: 0;">'
    #     html += f'<strong style="font-size: 14px;">⏰ Frequency Settings</strong><br>'
    #     html += '<div style="margin-left: 20px; margin-top: 5px; font-size: 12px;">'
    #     html += f"• Digest Emails: <strong>{frequency.get('digest_emails', 'daily').upper()}</strong><br>"
    #     html += f"• Payment Reminders: <strong>{frequency.get('reminder_advance_days', 3)} days</strong> before due"
    #     html += '</div>'
    #     html += '</div>'
        
    #     html += '</div>'
        
    #     # Add management link
    #     html += '<div style="margin-top: 15px; padding: 10px; background: #d1ecf1; border-left: 4px solid #0c5460; border-radius: 4px;">'
    #     html += '<strong style="color: #0c5460;">💡 Pro Tip:</strong> '
    #     html += 'Users can manage their notification preferences via:<br>'
    #     html += '<code style="background: #bee5eb; padding: 2px 6px; border-radius: 3px; margin-top: 5px; display: inline-block;">'
    #     html += 'PUT /api/auth/notification-preferences/'
    #     html += '</code>'
    #     html += '</div>'
        
    #     return format_html(html)
    
    # notification_preferences_display.short_description = 'Notification Settings Preview'
    
    def lease_dates(self, obj):
        """Display lease period with visual indicator"""
        if obj.lease_start_date and obj.lease_end_date:
            # Check if lease is active, expiring soon, or expired
            from datetime import date, timedelta
            today = date.today()
            days_until_end = (obj.lease_end_date - today).days
            
            if days_until_end < 0:
                # Expired
                color = '#dc3545'
                icon = '🔴'
                status = 'EXPIRED'
            elif days_until_end <= 30:
                # Expiring soon
                color = '#ffc107'
                icon = '⚠️'
                status = f'{days_until_end} days left'
            else:
                # Active
                color = '#28a745'
                icon = '✅'
                status = 'Active'
            
            return format_html(
                '<span style="color: {};">{}</span> {} to {}<br>'
                '<small style="background: {}; color: white; padding: 2px 6px; '
                'border-radius: 3px; font-size: 10px;">{}</small>',
                color, icon,
                obj.lease_start_date.strftime('%b %d, %Y'),
                obj.lease_end_date.strftime('%b %d, %Y'),
                color, status
            )
        elif obj.lease_start_date:
            return format_html(
                '🟡 From {}',
                obj.lease_start_date.strftime('%b %d, %Y')
            )
        return format_html('<span style="color: #6c757d;">Not set</span>')
    
    lease_dates.short_description = 'Lease Period'
    
    def monthly_rent(self, obj):
        """Display monthly rent with currency formatting"""
        if obj.monthly_rent:
            return format_html(
                '<strong style="color: #28a745;">₹{:,.2f}</strong>',
                obj.monthly_rent
            )
        return format_html('<span style="color: #6c757d;">-</span>')
    monthly_rent.short_description = 'Rent/Month'
    
    def household_size(self, obj):
        """Display household size with icon"""
        if obj.household_size:
            return format_html(
                '👨‍👩‍👧‍👦 {}',
                obj.household_size
            )
        return format_html('<span style="color: #6c757d;">-</span>')
    household_size.short_description = 'Household'
    
    def has_pets(self, obj):
        """Display pet status with icon"""
        if obj.has_pets:
            pet_info = obj.pet_details if obj.pet_details else 'Yes'
            return format_html(
                '<span style="color: #28a745;" title="{}">🐾 Yes</span>',
                pet_info
            )
        return format_html('<span style="color: #6c757d;">❌</span>')
    has_pets.short_description = 'Pets'
    
    def vehicle_count(self, obj):
        """Display vehicle count with icon"""
        if obj.vehicle_count:
            return format_html(
                '🚗 {}',
                obj.vehicle_count
            )
        return format_html('<span style="color: #6c757d;">-</span>')
    vehicle_count.short_description = 'Vehicles'
    
    # Actions
    actions = [ 'export_profiles'] # 'initialize_notification_preferences'
    
    # def initialize_notification_preferences(self, request, queryset):
    #     """Initialize notification preferences for selected users"""
    #     updated = 0
    #     for profile in queryset:
    #         if not profile.notification_preferences:
    #             profile.notification_preferences = profile.get_default_notification_preferences()
    #             profile.save()
    #             updated += 1
        
    #     self.message_user(
    #         request,
    #         f'✅ Initialized notification preferences for {updated} user profile(s).'
    #     )
    # initialize_notification_preferences.short_description = "🔔 Initialize notification preferences"
    
    def export_profiles(self, request, queryset):
        """Export selected profiles to CSV"""
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="user_profiles.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Username', 'Email', 'Role', 'Occupation', 'Lease Start', 
            'Lease End', 'Monthly Rent', 'Household Size', 'Has Pets', 
            'Vehicle Count', 'Notifications Enabled'
        ])
        
        for profile in queryset:
            prefs = profile.notification_preferences or {}
            email_enabled = prefs.get('email', {}).get('enabled', False)
            sms_enabled = prefs.get('sms', {}).get('enabled', False)
            push_enabled = prefs.get('push', {}).get('enabled', False)
            notif_status = f"Email: {email_enabled}, SMS: {sms_enabled}, Push: {push_enabled}"
            
            writer.writerow([
                profile.user.username,
                profile.user.email,
                profile.user.get_role_display(),
                profile.occupation or '',
                profile.lease_start_date or '',
                profile.lease_end_date or '',
                profile.monthly_rent or '',
                profile.household_size or '',
                'Yes' if profile.has_pets else 'No',
                profile.vehicle_count or '',
                notif_status
            ])
        
        return response
    export_profiles.short_description = "📥 Export selected profiles to CSV"

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'name', 'level', 'permission_count', 'is_system_role', 'is_active']
    list_filter = ['is_system_role', 'is_active', 'level']
    search_fields = ['name', 'display_name', 'description']
    ordering = ['-level', 'name']
    
    fieldsets = (
        ('Role Information', {
            'fields': ('name', 'display_name', 'description', 'level')
        }),
        ('Type & Status', {
            'fields': ('is_system_role', 'is_active')
        }),
        ('Permissions', {
            'fields': ('permissions',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def permission_count(self, obj):
        return len(obj.permissions) if obj.permissions else 0
    permission_count.short_description = 'Permissions'

@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'category', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'code', 'description']
    ordering = ['category', 'name']

@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'role', 'assigned_by', 'assigned_at', 
        'validity_period', 'status_display'
    ]
    list_filter = ['role', 'is_active', 'assigned_at']
    search_fields = ['user__username', 'user__email', 'role__name']
    autocomplete_fields = ['user', 'role', 'assigned_by']
    
    def validity_period(self, obj):
        if obj.valid_until:
            return f"{obj.valid_from.date()} to {obj.valid_until.date()}"
        return f"From {obj.valid_from.date()}"
    validity_period.short_description = 'Validity'
    
    def status_display(self, obj):
        if obj.is_valid:
            return format_html('<span style="color: green;">✓ Active</span>')
        else:
            return format_html('<span style="color: red;">✗ Inactive</span>')
    status_display.short_description = 'Status'

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'action', 'description_short', 'affected_user',
        'tenant_schema', 'created_at'
    ]
    list_filter = ['action', 'tenant_schema', 'created_at']
    search_fields = ['user__username', 'action', 'description']
    readonly_fields = [
        'user', 'action', 'description', 'ip_address', 'user_agent',
        'tenant_schema', 'affected_user', 'metadata', 'created_at'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    fieldsets = (
        ('Activity Information', {
            'fields': ('user', 'action', 'description', 'affected_user')
        }),
        ('Context', {
            'fields': ('tenant_schema', 'ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
        ('Additional Data', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )
    
    formfield_overrides = {
        models.JSONField: {'widget': Textarea(attrs={'rows': 4, 'cols': 80})},
    }
    
    def description_short(self, obj):
        return (obj.description[:50] + '...') if len(obj.description) > 50 else obj.description
    description_short.short_description = 'Description'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False

# Customize admin based on schema
def customize_admin_for_schema():
    if hasattr(connection, 'tenant'):
        if connection.tenant.schema_name == 'public':
            admin.site.site_header = "PropFlow System Administration"
            admin.site.site_title = "System Admin"
            admin.site.index_title = "Manage System Users & Roles"
        else:
            admin.site.site_header = "Property Management Dashboard"
            admin.site.site_title = "Property Admin"
            admin.site.index_title = "Manage Residents & Staff"

customize_admin_for_schema()