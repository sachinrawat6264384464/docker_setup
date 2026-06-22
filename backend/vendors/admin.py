# vendors/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.db.models import Sum, Avg
from .models import (
    VendorCategory, Vendor, VendorService, VendorContract,
    VendorReview, VendorPayment, VendorInsurance
)


@admin.register(VendorCategory)
class VendorCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'vendor_count', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']
    
    def vendor_count(self, obj):
        return obj.vendors.count()
    vendor_count.short_description = 'Vendors'


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = [
        'vendor_number', 'company_name', 'vendor_type',
        'contact_person', 'phone', 'email', 'status_badge',
        'rating_display', 'is_preferred', 'is_verified'
    ]
    list_filter = [
        'status', 'vendor_type', 'is_preferred', 'is_verified',
        'created_at', 'city', 'state'
    ]
    search_fields = [
        'vendor_number', 'company_name', 'contact_person',
        'email', 'phone', 'city', 'license_number', 'tax_id'
    ]
    readonly_fields = [
        'vendor_number', 'average_rating', 'total_reviews',
        'total_jobs', 'verified_at', 'created_at', 'updated_at'
    ]
    filter_horizontal = ['categories']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'vendor_number', 'company_name', 'vendor_type',
                'user', 'categories', 'status'
            )
        }),
        ('Contact Information', {
            'fields': (
                'contact_person', 'email', 'phone', 'alternate_phone',
                'website'
            )
        }),
        ('Address', {
            'fields': (
                'address_line1', 'address_line2', 'city',
                'state', 'zip_code', 'country'
            )
        }),
        ('Business Details', {
            'fields': (
                'tax_id', 'license_number', 'license_expiry',
                'payment_terms', 'contract_start_date', 'contract_end_date',
                'contract_value', 'hourly_rate', 'w9_form'
            )
        }),
        ('Verification & Preferences', {
            'fields': (
                'is_preferred', 'is_verified', 'verified_by',
                'verified_at'
            )
        }),
        ('Performance Metrics', {
            'fields': (
                'average_rating', 'total_reviews', 'total_jobs',
                'last_job_date'
            )
        }),
        ('Notes', {
            'fields': ('notes', 'availability_preferences'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def status_badge(self, obj):
        colors = {
            'active': '#16a34a',
            'inactive': '#6b7280',
            'suspended': '#dc2626',
            'blacklisted': '#000000'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, '#gray'),
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'
    
    def rating_display(self, obj):
        if obj.total_reviews == 0:
            return format_html('<span style="color: #6b7280;">No reviews</span>')
        
        stars = '⭐' * int(obj.average_rating)
        color = '#16a34a' if obj.average_rating >= 4 else '#f59e0b' if obj.average_rating >= 3 else '#dc2626'
        
        return format_html(
            '<span style="color: {};">{} ({:.1f}/5 - {} reviews)</span>',
            color, stars, obj.average_rating, obj.total_reviews
        )
    rating_display.short_description = 'Rating'
    
    actions = ['mark_as_preferred', 'verify_vendors', 'suspend_vendors']
    
    def mark_as_preferred(self, request, queryset):
        queryset.update(is_preferred=True)
        self.message_user(request, f'{queryset.count()} vendors marked as preferred.')
    mark_as_preferred.short_description = 'Mark as preferred'
    
    def verify_vendors(self, request, queryset):
        count = queryset.update(
            is_verified=True,
            verified_by=request.user,
            verified_at=timezone.now()
        )
        self.message_user(request, f'{count} vendors verified.')
    verify_vendors.short_description = 'Verify selected vendors'
    
    def suspend_vendors(self, request, queryset):
        queryset.update(status='suspended')
        self.message_user(request, f'{queryset.count()} vendors suspended.')
    suspend_vendors.short_description = 'Suspend vendors'


@admin.register(VendorService)
class VendorServiceAdmin(admin.ModelAdmin):
    list_display = [
        'service_name', 'vendor', 'category', 'pricing_type',
        'base_price', 'is_active', 'created_at'
    ]
    list_filter = ['pricing_type', 'is_active', 'category', 'created_at']
    search_fields = ['service_name', 'vendor__company_name', 'description']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Service Information', {
            'fields': ('vendor', 'category', 'service_name', 'description')
        }),
        ('Pricing', {
            'fields': ('pricing_type', 'base_price')
        }),
        ('Availability', {
            'fields': ('is_active', 'min_notice_hours')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )


@admin.register(VendorContract)
class VendorContractAdmin(admin.ModelAdmin):
    list_display = [
        'contract_number', 'vendor', 'title', 'contract_type',
        'contract_value', 'status_badge', 'signature_status',
        'start_date', 'end_date'
    ]
    list_filter = ['status', 'contract_type', 'start_date', 'created_at']
    search_fields = [
        'contract_number', 'title', 'vendor__company_name',
        'description'
    ]
    readonly_fields = [
        'contract_number', 'vendor_signature_date',
        'management_signature_date', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'start_date'
    
    fieldsets = (
        ('Contract Information', {
            'fields': (
                'contract_number', 'vendor', 'contract_type',
                'title', 'status'
            )
        }),
        ('Contract Details', {
            'fields': ('description', 'scope_of_work', 'contract_value', 'payment_schedule')
        }),
        ('Timeline', {
            'fields': ('start_date', 'end_date')
        }),
        ('Documents', {
            'fields': ('contract_document', 'signed_document')
        }),
        ('Signatures', {
            'fields': (
                'signed_by_vendor', 'vendor_signature_date',
                'signed_by_management', 'management_signature_date'
            )
        }),
        ('Management', {
            'fields': ('created_by',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def status_badge(self, obj):
        colors = {
            'draft': '#6b7280',
            'active': '#16a34a',
            'expired': '#f59e0b',
            'terminated': '#dc2626'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, '#gray'),
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'
    
    def signature_status(self, obj):
        if obj.signed_by_vendor and obj.signed_by_management:
            return format_html('<span style="color: #16a34a;">✓ Fully Signed</span>')
        elif obj.signed_by_vendor or obj.signed_by_management:
            return format_html('<span style="color: #f59e0b;">⚠ Partially Signed</span>')
        else:
            return format_html('<span style="color: #dc2626;">✗ Unsigned</span>')
    signature_status.short_description = 'Signatures'


@admin.register(VendorReview)
class VendorReviewAdmin(admin.ModelAdmin):
    list_display = [
        'vendor', 'reviewed_by', 'rating_display', 'quality_rating',
        'timeliness_rating', 'would_recommend', 'is_verified',
        'created_at'
    ]
    list_filter = [
        'overall_rating', 'would_recommend', 'is_verified',
        'created_at'
    ]
    search_fields = [
        'vendor__company_name', 'title', 'comment',
        'reviewed_by__username'
    ]
    readonly_fields = ['created_at', 'responded_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Review Information', {
            'fields': ('vendor', 'reviewed_by', 'created_at')
        }),
        ('Ratings', {
            'fields': (
                'overall_rating', 'quality_rating', 'timeliness_rating',
                'professionalism_rating', 'value_rating'
            )
        }),
        ('Review Content', {
            'fields': ('title', 'comment', 'would_recommend')
        }),
        ('Work Order', {
            'fields': ('work_order_id',),
            'classes': ('collapse',)
        }),
        ('Verification', {
            'fields': ('is_verified',)
        }),
        ('Vendor Response', {
            'fields': ('vendor_response', 'responded_at')
        }),
    )
    
    def rating_display(self, obj):
        stars = '⭐' * obj.overall_rating
        color = '#16a34a' if obj.overall_rating >= 4 else '#f59e0b' if obj.overall_rating == 3 else '#dc2626'
        return format_html(
            '<span style="color: {};">{} ({})</span>',
            color, stars, obj.overall_rating
        )
    rating_display.short_description = 'Overall Rating'
    
    actions = ['verify_reviews']
    
    def verify_reviews(self, request, queryset):
        queryset.update(is_verified=True)
        self.message_user(request, f'{queryset.count()} reviews verified.')
    verify_reviews.short_description = 'Verify selected reviews'


@admin.register(VendorPayment)
class VendorPaymentAdmin(admin.ModelAdmin):
    list_display = [
        'payment_number', 'vendor', 'amount', 'invoice_number',
        'status_badge', 'due_date', 'paid_date', 'payment_status'
    ]
    list_filter = ['status', 'due_date', 'created_at']
    search_fields = [
        'payment_number', 'invoice_number', 'vendor__company_name',
        'description'
    ]
    readonly_fields = [
        'payment_number', 'approved_at', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'due_date'
    
    fieldsets = (
        ('Payment Information', {
            'fields': (
                'payment_number', 'vendor', 'contract', 'status'
            )
        }),
        ('Invoice Details', {
            'fields': (
                'amount', 'description', 'invoice_number',
                'invoice_date', 'due_date', 'paid_date'
            )
        }),
        ('Documents', {
            'fields': ('invoice_document', 'payment_receipt')
        }),
        ('Approval', {
            'fields': ('created_by', 'approved_by', 'approved_at')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def status_badge(self, obj):
        colors = {
            'pending': '#f59e0b',
            'processing': '#3b82f6',
            'paid': '#16a34a',
            'failed': '#dc2626',
            'cancelled': '#6b7280'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, '#gray'),
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'
    
    def payment_status(self, obj):
        if obj.status == 'paid':
            return format_html('<span style="color: #16a34a;">✓ Paid</span>')
        
        if timezone.now().date() > obj.due_date:
            days_overdue = (timezone.now().date() - obj.due_date).days
            return format_html(
                '<span style="color: #dc2626;">⚠ Overdue ({} days)</span>',
                days_overdue
            )
        
        days_until_due = (obj.due_date - timezone.now().date()).days
        return format_html(
            '<span style="color: #f59e0b;">Due in {} days</span>',
            days_until_due
        )
    payment_status.short_description = 'Payment Status'
    
    actions = ['mark_as_paid', 'approve_payments']
    
    def mark_as_paid(self, request, queryset):
        count = queryset.update(
            status='paid',
            paid_date=timezone.now().date()
        )
        self.message_user(request, f'{count} payments marked as paid.')
    mark_as_paid.short_description = 'Mark as paid'
    
    def approve_payments(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='processing',
            approved_by=request.user,
            approved_at=timezone.now()
        )
        self.message_user(request, f'{count} payments approved.')
    approve_payments.short_description = 'Approve selected payments'


@admin.register(VendorInsurance)
class VendorInsuranceAdmin(admin.ModelAdmin):
    list_display = [
        'vendor', 'insurance_type', 'policy_number',
        'insurance_company', 'coverage_amount', 'expiry_status',
        'is_verified'
    ]
    list_filter = ['insurance_type', 'is_verified', 'expiry_date', 'created_at']
    search_fields = [
        'vendor__company_name', 'policy_number',
        'insurance_company'
    ]
    readonly_fields = ['verified_at', 'created_at', 'updated_at']
    date_hierarchy = 'expiry_date'
    
    fieldsets = (
        ('Vendor Information', {
            'fields': ('vendor',)
        }),
        ('Insurance Details', {
            'fields': (
                'insurance_type', 'policy_number', 'insurance_company',
                'coverage_amount'
            )
        }),
        ('Dates', {
            'fields': ('effective_date', 'expiry_date')
        }),
        ('Documents', {
            'fields': ('certificate_document',)
        }),
        ('Verification', {
            'fields': ('is_verified', 'verified_by', 'verified_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def expiry_status(self, obj):
        if obj.is_expired():
            return format_html(
                '<span style="background-color: #dc2626; color: white; padding: 3px 8px; border-radius: 3px;">EXPIRED</span>'
            )
        
        days_until_expiry = (obj.expiry_date - timezone.now().date()).days
        
        if days_until_expiry <= 30:
            return format_html(
                '<span style="background-color: #f59e0b; color: white; padding: 3px 8px; border-radius: 3px;">EXPIRING SOON ({} days)</span>',
                days_until_expiry
            )
        
        return format_html(
            '<span style="background-color: #16a34a; color: white; padding: 3px 8px; border-radius: 3px;">VALID ({} days)</span>',
            days_until_expiry
        )
    expiry_status.short_description = 'Expiry Status'
    
    actions = ['verify_insurance']
    
    def verify_insurance(self, request, queryset):
        count = queryset.update(
            is_verified=True,
            verified_by=request.user,
            verified_at=timezone.now()
        )
        self.message_user(request, f'{count} insurance certificates verified.')
    verify_insurance.short_description = 'Verify insurance certificates'