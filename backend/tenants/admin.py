# tenants/admin.py - FINAL COMPLETE VERSION
from django.contrib import admin
from django.utils.html import format_html
from django.db import models
from django.forms import Textarea
from django.contrib import messages
from .models import Client, Domain, TenantSettings, TenantFeature, TenantSubscription
from .forms import ClientAdminForm, DomainAdminForm


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    form = ClientAdminForm  # Use custom form with auto-populate features
    
    list_display = [
        'name', 'schema_name', 'subscription_plan', 'status_display', 
        'features_count', 'domain_count', 'created_on'
    ]
    list_filter = ['subscription_plan', 'is_active', 'created_on']
    search_fields = ['name', 'contact_email', 'contact_phone', 'schema_name']
    readonly_fields = ['schema_name', 'created_on', 'updated_on']
    ordering = ['-created_on']
    
    def get_readonly_fields(self, request, obj=None):
        """Make schema_name readonly only when editing existing tenant"""
        if obj:  # Editing existing tenant
            return ['schema_name', 'created_on', 'updated_on']
        else:  # Creating new tenant - exclude schema_name from form
            return ['created_on', 'updated_on']
    
    def get_fields(self, request, obj=None):
        """Exclude schema_name from form when creating new tenant"""
        fields = super().get_fields(request, obj)
        if not obj:  # Creating new tenant
            # Remove schema_name from fields
            fields = [f for f in fields if f != 'schema_name']
        return fields
    
    def get_fieldsets(self, request, obj=None):
        """Dynamic fieldsets based on whether creating or editing"""
        if obj:  # Editing existing tenant
            return (
                ('🏢 Company Information', {
                    'fields': ('name', 'description', 'logo')
                }),
                ('📞 Contact Information', {
                    'fields': ('contact_email', 'contact_phone', 'address')
                }),
                ('💎 Subscription & Status', {
                    'fields': ('subscription_plan', 'is_active'),
                    'description': 'Subscription plan determines available features and limits'
                }),
                ('⚙️ Feature Toggles', {
                    'fields': ('features',),
                    'classes': ('collapse',),
                    'description': (
                        '<div style="padding: 10px; background: #e7f3ff; border-left: 4px solid #2196F3; margin: 10px 0;">'
                        '<strong>ℹ️ Auto-Populated Based on Plan:</strong><br>'
                        '• <strong>Basic Plan</strong>: Core features only<br>'
                        '• <strong>Premium Plan</strong>: Basic + Amenities + Reports<br>'
                        '• <strong>Enterprise Plan</strong>: All features enabled<br><br>'
                        'You can manually edit this JSON to enable/disable specific features.'
                        '</div>'
                    )
                }),
                ('🔧 System Information', {
                    'fields': ('schema_name', 'created_on', 'updated_on'),
                    'classes': ('collapse',)
                }),
            )
        else:  # Creating new tenant
            return (
                ('🏢 Company Information', {
                    'fields': ('name', 'description', 'logo')
                }),
                ('📞 Contact Information', {
                    'fields': ('contact_email', 'contact_phone', 'address')
                }),
                ('🌐 Domain Setup', {
                    'fields': ('primary_domain',),
                    'description': 'Set the primary domain for accessing this tenant (e.g., abc.localhost:8000)'
                }),
                ('💎 Subscription & Status', {
                    'fields': ('subscription_plan', 'is_active'),
                    'description': 'Subscription plan determines available features and limits'
                }),
                ('⚙️ Feature Toggles', {
                    'fields': ('features',),
                    'classes': ('collapse',),
                    'description': (
                        '<div style="padding: 10px; background: #e7f3ff; border-left: 4px solid #2196F3; margin: 10px 0;">'
                        '<strong>ℹ️ Auto-Populated Based on Plan:</strong><br>'
                        '• <strong>Basic Plan</strong>: Core features only<br>'
                        '• <strong>Premium Plan</strong>: Basic + Amenities + Reports<br>'
                        '• <strong>Enterprise Plan</strong>: All features enabled<br><br>'
                        'You can manually edit this JSON to enable/disable specific features.'
                        '</div>'
                    )
                }),
            )
    
    formfield_overrides = {
        models.JSONField: {'widget': Textarea(attrs={'rows': 15, 'cols': 80})},
    }
    
    def save_model(self, request, obj, form, change):
        """Custom save with success notifications"""
        is_new = not obj.pk
        
        # Save the tenant
        super().save_model(request, obj, form, change)
        
        if is_new:
            messages.success(
                request,
                format_html(
                    '✅ <strong>Tenant Created Successfully!</strong><br>'
                    '📋 Schema: <code>{}</code><br>'
                    '🌐 Domain: <code>{}</code><br>'
                    '💡 Default features have been enabled based on the <strong>{}</strong> plan.',
                    obj.schema_name,
                    form.cleaned_data.get('primary_domain', 'Not set'),
                    obj.get_subscription_plan_display()
                )
            )
        else:
            messages.success(request, f'✅ Tenant "{obj.name}" updated successfully.')
    
    def status_display(self, obj):
        """Display tenant status with color coding"""
        if obj.is_active:
            return format_html(
                '<span style="color: #28a745; font-weight: bold;">✅ Active</span>'
            )
        else:
            return format_html(
                '<span style="color: #dc3545; font-weight: bold;">❌ Inactive</span>'
            )
    status_display.short_description = 'Status'
    
    def features_count(self, obj):
        """Count enabled features with visual indicator"""
        if obj.features:
            enabled = sum(1 for v in obj.features.values() if v)
            total = len(obj.features)
            percentage = (enabled / total * 100) if total > 0 else 0
            
            color = '#28a745' if percentage > 70 else '#ffc107' if percentage > 40 else '#dc3545'
            
            return format_html(
                '<span style="color: {}; font-weight: bold;">{}/{} ({}%)</span>',
                color, enabled, total, int(percentage)
            )
        return format_html('<span style="color: #6c757d;">0/0</span>')
    features_count.short_description = 'Features Enabled'
    
    def domain_count(self, obj):
        """Count domains for this tenant and show primary"""
        count = obj.domains.count()
        if count > 0:
            primary = obj.domains.filter(is_primary=True).first()
            if primary:
                return format_html(
                    '<span style="font-weight: bold; color: #28a745;">{}</span><br>'
                    '<small style="color: #666;">⭐ {}</small>',
                    count, primary.domain
                )
            return format_html('<span style="color: #ffc107;">{}</span>', count)
        return format_html('<span style="color: #dc3545;">⚠️ No domains</span>')
    domain_count.short_description = 'Domains'
    
    actions = ['activate_tenants', 'deactivate_tenants', 'reset_features_to_plan', 'view_features']
    
    def activate_tenants(self, request, queryset):
        """Activate selected tenants"""
        updated = queryset.update(is_active=True)
        self.message_user(
            request, 
            f'✅ Successfully activated {updated} tenant(s).',
            messages.SUCCESS
        )
    activate_tenants.short_description = "✅ Activate selected tenants"
    
    def deactivate_tenants(self, request, queryset):
        """Deactivate selected tenants"""
        updated = queryset.update(is_active=False)
        self.message_user(
            request, 
            f'⛔ Successfully deactivated {updated} tenant(s).',
            messages.WARNING
        )
    deactivate_tenants.short_description = "⛔ Deactivate selected tenants"
    
    def reset_features_to_plan(self, request, queryset):
        """Reset features to match subscription plan defaults"""
        form = ClientAdminForm()
        updated_count = 0
        
        for tenant in queryset:
            tenant.features = form.get_default_features(tenant.subscription_plan)
            tenant.save()
            updated_count += 1
        
        self.message_user(
            request, 
            f'🔄 Reset features for {updated_count} tenant(s) based on their subscription plans.',
            messages.INFO
        )
    reset_features_to_plan.short_description = "🔄 Reset features to match plan"
    
    def view_features(self, request, queryset):
        """Display features summary for selected tenant"""
        if queryset.count() == 1:
            tenant = queryset.first()
            enabled = [k for k, v in tenant.features.items() if v]
            disabled = [k for k, v in tenant.features.items() if not v]
            
            self.message_user(
                request,
                format_html(
                    '<strong>📊 Features for "{}":</strong><br>'
                    '✅ Enabled ({}): {}<br>'
                    '❌ Disabled ({}): {}',
                    tenant.name,
                    len(enabled), ', '.join(enabled) or 'None',
                    len(disabled), ', '.join(disabled) or 'None'
                ),
                messages.INFO
            )
        else:
            self.message_user(
                request,
                '⚠️ Please select only one tenant to view features.',
                messages.WARNING
            )
    view_features.short_description = "📊 View features summary"


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    form = DomainAdminForm  # Use custom form with validation
    
    list_display = ['domain', 'tenant', 'primary_display', 'status_check', 'created_display']
    list_filter = ['is_primary']
    search_fields = ['domain', 'tenant__name']
    autocomplete_fields = ['tenant']
    ordering = ['domain']
    
    fieldsets = (
        ('🌐 Domain Configuration', {
            'fields': ('domain', 'tenant', 'is_primary'),
            'description': (
                '<div style="padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107; margin: 10px 0;">'
                '<strong>⚠️ Important Notes:</strong><br>'
                '• Use format: <code>subdomain.localhost:8000</code> for development<br>'
                '• Use format: <code>subdomain.yourdomain.com</code> for production<br>'
                '• Each tenant must have at least ONE primary domain<br>'
                '• Primary domain is used as the default access point'
                '</div>'
            )
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Custom save with notifications"""
        is_new = not obj.pk
        
        super().save_model(request, obj, form, change)
        
        if is_new:
            messages.success(
                request,
                format_html(
                    '✅ Domain <strong>{}</strong> added for tenant <strong>{}</strong>',
                    obj.domain, obj.tenant.name
                )
            )
    
    def primary_display(self, obj):
        """Display primary status with icon"""
        if obj.is_primary:
            return format_html(
                '<span style="color: #ffc107; font-weight: bold; font-size: 14px;">⭐ Primary</span>'
            )
        else:
            return format_html(
                '<span style="color: #6c757d;">Secondary</span>'
            )
    primary_display.short_description = 'Type'
    
    def status_check(self, obj):
        """Check if domain configuration looks correct"""
        domain = obj.domain.lower()
        
        # Check for common issues
        if not ('localhost' in domain or '.' in domain):
            return format_html(
                '<span style="color: #dc3545;">⚠️ Invalid format</span>'
            )
        elif 'localhost' in domain and ':' not in domain:
            return format_html(
                '<span style="color: #ffc107;">⚠️ Missing port</span>'
            )
        else:
            return format_html(
                '<span style="color: #28a745;">✅ OK</span>'
            )
    status_check.short_description = 'Status'
    
    def created_display(self, obj):
        """Display creation date from tenant"""
        return obj.tenant.created_on.strftime('%Y-%m-%d %H:%M')
    created_display.short_description = 'Created At'


@admin.register(TenantSettings)
class TenantSettingsAdmin(admin.ModelAdmin):
    list_display = [
        'tenant', 'color_preview', 'notifications_summary', 
        'otp_status', 'updated_at'
    ]
    list_filter = [
        'email_notifications', 'sms_notifications', 'push_notifications',
        'otp_required', 'auto_assign_maintenance'
    ]
    search_fields = ['tenant__name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Tenant', {
            'fields': ('tenant',)
        }),
        ('🎨 Branding & Identity', {
            'fields': (
                'primary_color', 'secondary_color', 'accent_color', 
                'logo_url', 'favicon_url', 'login_message', 
                'login_page_message', 'footer_text'
            ),
            'description': 'Customize the visual appearance and branding for this tenant'
        }),
        ('🌐 General Settings', {
            'fields': ('currency', 'date_format', 'fiscal_year_start')
        }),
        ('🔔 Notification Preferences', {
            'fields': (
                'email_notifications', 'sms_notifications', 'push_notifications',
                'payment_reminders', 'payment_reminder_days', 'maintenance_updates',
                'lease_expiry_alerts', 'lease_expiry_days', 'security_alerts',
                'weekly_digest', 'monthly_report', 'new_resident_welcome',
                'document_expiry_alerts'
            )
        }),
        ('🔐 OTP Configuration', {
            'fields': ('otp_required', 'otp_expire_minutes')
        }),
        ('💰 Payment Rules', {
            'fields': (
                'payment_due_days', 'late_fee_enabled', 'late_fee_type', 
                'late_fee_percentage', 'late_fee_amount', 'grace_period_days', 
                'auto_invoicing', 'invoice_day_of_month'
            )
        }),
        ('💳 Payment Gateways', {
            'fields': (
                'razorpay_enabled', 'razorpay_key_id', 'razorpay_webhook_secret',
                'paypal_enabled', 'paypal_client_id', 'bank_transfer_enabled',
                'bank_name', 'bank_account_name', 'bank_account_number', 'bank_routing_number'
            ),
            'classes': ('collapse',)
        }),
        ('🔌 Integrations', {
            'fields': (
                'quickbooks_enabled', 'google_calendar_enabled', 'slack_enabled',
                'slack_webhook_url', 'api_enabled', 'api_key', 'webhook_url', 'webhook_secret'
            ),
            'classes': ('collapse',)
        }),
        ('🔧 Maintenance Settings', {
            'fields': ('auto_assign_maintenance', 'maintenance_categories'),
            'classes': ('collapse',)
        }),
        ('📅 Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    formfield_overrides = {
        models.JSONField: {'widget': Textarea(attrs={'rows': 8, 'cols': 80})},
    }
    
    def color_preview(self, obj):
        """Display color swatches"""
        return format_html(
            '<div style="display: flex; gap: 5px;">'
            '<div style="width: 30px; height: 30px; background: {}; border: 1px solid #ddd;" title="Primary"></div>'
            '<div style="width: 30px; height: 30px; background: {}; border: 1px solid #ddd;" title="Secondary"></div>'
            '<div style="width: 30px; height: 30px; background: {}; border: 1px solid #ddd;" title="Accent"></div>'
            '</div>',
            obj.primary_color, obj.secondary_color, obj.accent_color
        )
    color_preview.short_description = 'Colors'
    
    def notifications_summary(self, obj):
        """Summary of enabled notifications"""
        settings = []
        if obj.email_notifications:
            settings.append('<span style="color: #28a745;">📧 Email</span>')
        if obj.sms_notifications:
            settings.append('<span style="color: #28a745;">📱 SMS</span>')
        if obj.push_notifications:
            settings.append('<span style="color: #28a745;">🔔 Push</span>')
        
        if settings:
            return format_html(' '.join(settings))
        return format_html('<span style="color: #6c757d;">None</span>')
    notifications_summary.short_description = 'Notifications'
    
    def otp_status(self, obj):
        """Display OTP configuration"""
        if obj.otp_required:
            return format_html(
                '<span style="color: #28a745;">🔐 {} min</span>',
                obj.otp_expire_minutes
            )
        return format_html('<span style="color: #6c757d;">Disabled</span>')
    otp_status.short_description = 'OTP'


@admin.register(TenantFeature)
class TenantFeatureAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_name', 'category', 'active_display', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['name', 'display_name', 'description']
    ordering = ['category', 'name']
    
    fieldsets = (
        ('Feature Information', {
            'fields': ('name', 'display_name', 'description', 'category')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def active_display(self, obj):
        if obj.is_active:
            return format_html('<span style="color: #28a745; font-weight: bold;">✅ Active</span>')
        return format_html('<span style="color: #dc3545;">❌ Inactive</span>')
    active_display.short_description = 'Status'


@admin.register(TenantSubscription)
class TenantSubscriptionAdmin(admin.ModelAdmin):
    list_display = [
        'tenant', 'status_display', 'billing_cycle', 'monthly_amount',
        'usage_limits', 'days_remaining_display', 'trial_badge'
    ]
    list_filter = ['status', 'billing_cycle', 'is_trial', 'start_date']
    search_fields = ['tenant__name']
    autocomplete_fields = ['tenant']
    readonly_fields = ['created_at', 'updated_at', 'is_expired', 'days_remaining']
    
    fieldsets = (
        ('Tenant', {
            'fields': ('tenant',)
        }),
        ('Subscription Period', {
            'fields': ('start_date', 'end_date', 'is_trial', 'trial_end_date')
        }),
        ('Billing Information', {
            'fields': ('monthly_amount', 'billing_cycle', 'status')
        }),
        ('Usage Limits', {
            'fields': ('max_users', 'max_properties', 'max_units'),
            'description': 'Set limits for this subscription plan'
        }),
        ('System Information', {
            'fields': ('is_expired', 'days_remaining', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def status_display(self, obj):
        colors = {
            'active': '#28a745',
            'suspended': '#ffc107',
            'expired': '#dc3545',
            'cancelled': '#6c757d'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_display.short_description = 'Status'
    
    def usage_limits(self, obj):
        return format_html(
            '<small>👥 {} users | 🏢 {} properties | 🏠 {} units</small>',
            obj.max_users, obj.max_properties, obj.max_units
        )
    usage_limits.short_description = 'Limits'
    
    def days_remaining_display(self, obj):
        days = obj.days_remaining
        if days is None:
            return format_html('<span style="color: #6c757d;">No expiry</span>')
        elif days < 7:
            return format_html('<span style="color: #dc3545; font-weight: bold;">⚠️ {} days</span>', days)
        elif days < 30:
            return format_html('<span style="color: #ffc107;">{} days</span>', days)
        else:
            return format_html('<span style="color: #28a745;">{} days</span>', days)
    days_remaining_display.short_description = 'Remaining'
    
    def trial_badge(self, obj):
        if obj.is_trial:
            return format_html(
                '<span style="background: #ffc107; color: #000; padding: 2px 8px; '
                'border-radius: 3px; font-size: 11px; font-weight: bold;">TRIAL</span>'
            )
        return ''
    trial_badge.short_description = 'Type'


# Customize admin site header and titles
admin.site.site_header = "PropFlow System Administration"
admin.site.site_title = "PropFlow Admin"
admin.site.index_title = "System Management Dashboard"