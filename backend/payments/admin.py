# payments/admin.py
from django.contrib import admin
from .models import (
    PaymentGateway, Invoice, Payment, PaymentMethod, Refund,
    PaymentReminder, PaymentPlan, Installment, Transaction
)
from .models import AutoPayEnrollment, AutoPaymentLog, RecurringInvoice


@admin.register(PaymentGateway)
class PaymentGatewayAdmin(admin.ModelAdmin):
    list_display = ['gateway_type', 'is_active', 'is_test_mode', 'currency', 'total_transactions', 'successful_transactions']
    list_filter = ['gateway_type', 'is_active', 'is_test_mode']
    readonly_fields = ['total_transactions', 'successful_transactions', 'failed_transactions', 'total_amount_processed']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'user', 'invoice_type', 'total_amount', 'amount_due', 'status', 'due_date']
    list_filter = ['status', 'invoice_type', 'due_date']
    search_fields = ['invoice_number', 'user__username', 'user__email']
    readonly_fields = ['invoice_number', 'amount_paid', 'amount_due']
    date_hierarchy = 'created_at'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_number', 'user', 'amount', 'payment_method', 'status', 'gateway', 'created_at']
    list_filter = ['status', 'payment_method', 'gateway']
    search_fields = ['payment_number', 'user__username', 'gateway_transaction_id']
    readonly_fields = ['payment_number', 'net_amount']
    date_hierarchy = 'created_at'


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['user', 'method_type', 'card_last4', 'is_default', 'is_verified']
    list_filter = ['method_type', 'is_default', 'is_verified']
    search_fields = ['user__username', 'card_last4']


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ['refund_number', 'payment', 'amount', 'status', 'requested_at']
    list_filter = ['status']
    search_fields = ['refund_number']
    readonly_fields = ['refund_number']


@admin.register(PaymentReminder)
class PaymentReminderAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'reminder_type', 'scheduled_for', 'is_sent', 'sent_at']
    list_filter = ['reminder_type', 'is_sent']
    search_fields = ['invoice__invoice_number']
    ordering = ['-scheduled_for']


@admin.register(PaymentPlan)
class PaymentPlanAdmin(admin.ModelAdmin):
    list_display = ['plan_number', 'user', 'total_amount', 'installments', 'status', 'installments_paid']
    list_filter = ['status', 'frequency']
    search_fields = ['plan_number', 'user__username']
    readonly_fields = ['plan_number']


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ['payment_plan', 'installment_number', 'amount', 'due_date', 'status']
    list_filter = ['status']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['transaction_number', 'transaction_type', 'user', 'amount', 'created_at']
    list_filter = ['transaction_type']
    search_fields = ['transaction_number']
    readonly_fields = ['transaction_number']
    date_hierarchy = 'created_at'
    
    
@admin.register(AutoPayEnrollment)
class AutoPayEnrollmentAdmin(admin.ModelAdmin):
    list_display = [
        'enrollment_number', 'user', 'enrollment_type', 'frequency', 
        'amount', 'status', 'next_payment_date', 'total_payments', 
        'successful_payments', 'failed_payments'
    ]
    list_filter = ['status', 'frequency', 'enrollment_type', 'gateway']
    search_fields = ['enrollment_number', 'user__username', 'user__email', 'razorpay_subscription_id']
    readonly_fields = [
        'enrollment_number', 'razorpay_subscription_id',
        'total_payments', 'successful_payments', 
        'failed_payments', 'total_amount_paid', 'current_retry_count',
        'created_at', 'updated_at'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('enrollment_number', 'user', 'enrollment_type', 'status')
        }),
        ('Payment Details', {
            'fields': ('gateway', 'payment_method', 'amount', 'frequency')
        }),
        ('Gateway Information', {
            'fields': ('razorpay_subscription_id',),
            'classes': ('collapse',)
        }),
        ('Schedule', {
            'fields': ('start_date', 'next_payment_date', 'last_payment_date', 'billing_day')
        }),
        ('Retry Settings', {
            'fields': ('max_retry_attempts', 'current_retry_count', 'retry_interval_days')
        }),
        ('Statistics', {
            'fields': ('total_payments', 'successful_payments', 'failed_payments', 'total_amount_paid')
        }),
        ('Notifications', {
            'fields': ('notify_before_days', 'send_payment_confirmation', 'send_failure_notification')
        }),
        ('Additional', {
            'fields': ('description', 'metadata', 'paused_at', 'paused_reason', 
                      'cancelled_at', 'cancellation_reason'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'created_by')
        }),
    )
    
    date_hierarchy = 'created_at'
    
    actions = ['activate_enrollments', 'pause_enrollments', 'cancel_enrollments']
    
    def activate_enrollments(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f'{updated} enrollments activated.')
    activate_enrollments.short_description = "Activate selected enrollments"
    
    def pause_enrollments(self, request, queryset):
        updated = queryset.update(status='paused')
        self.message_user(request, f'{updated} enrollments paused.')
    pause_enrollments.short_description = "Pause selected enrollments"
    
    def cancel_enrollments(self, request, queryset):
        updated = queryset.update(status='cancelled')
        self.message_user(request, f'{updated} enrollments cancelled.')
    cancel_enrollments.short_description = "Cancel selected enrollments"


@admin.register(AutoPaymentLog)
class AutoPaymentLogAdmin(admin.ModelAdmin):
    list_display = [
        'enrollment', 'scheduled_date', 'attempted_date', 'amount', 
        'status', 'attempt_number'
    ]
    list_filter = ['status', 'scheduled_date']
    search_fields = ['enrollment__enrollment_number', 'enrollment__user__username']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Enrollment', {
            'fields': ('enrollment', 'payment')
        }),
        ('Payment Details', {
            'fields': ('scheduled_date', 'attempted_date', 'completed_date', 'amount', 'status')
        }),
        ('Retry Information', {
            'fields': ('attempt_number', 'next_retry_date')
        }),
        ('Error Information', {
            'fields': ('error_code', 'error_message', 'gateway_response'),
            'classes': ('collapse',)
        }),
        ('Notifications', {
            'fields': ('user_notified', 'notification_sent_at')
        }),
    )
    
    date_hierarchy = 'scheduled_date'


@admin.register(RecurringInvoice)
class RecurringInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'template_number', 'user', 'invoice_type', 'frequency', 
        'subtotal', 'status', 'next_invoice_date', 'auto_pay_enabled',
        'invoices_generated'
    ]
    list_filter = ['status', 'frequency', 'invoice_type', 'auto_pay_enabled']
    search_fields = ['template_number', 'user__username', 'user__email']
    readonly_fields = ['template_number', 'invoices_generated', 'last_invoice_date', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('template_number', 'user', 'invoice_type', 'status')
        }),
        ('Invoice Details', {
            'fields': ('description', 'building', 'unit_number')
        }),
        ('Amounts', {
            'fields': ('subtotal', 'tax_percentage')
        }),
        ('Recurrence', {
            'fields': ('frequency', 'start_date', 'end_date', 'next_invoice_date', 'billing_day')
        }),
        ('Auto-Pay', {
            'fields': ('auto_pay_enabled', 'autopay_enrollment')
        }),
        ('Template', {
            'fields': ('line_items_template',),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('invoices_generated', 'last_invoice_date')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'created_by')
        }),
    )
    
    date_hierarchy = 'created_at'    