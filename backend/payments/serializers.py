# payments/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from maintenance.models import MaintenanceRequest
from .models import (
    PaymentGateway, Invoice, Payment, PaymentMethod, Refund,
    PaymentReminder, PaymentPlan, Installment, Transaction
)
from .models import AutoPayEnrollment, AutoPaymentLog, RecurringInvoice

User = get_user_model()


class PaymentGatewaySerializer(serializers.ModelSerializer):
    gateway_type_display = serializers.CharField(source='get_gateway_type_display', read_only=True)
    success_rate = serializers.SerializerMethodField()
    has_secret_key = serializers.SerializerMethodField()
    has_webhook_secret = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentGateway
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'total_transactions', 
                           'successful_transactions', 'failed_transactions', 'total_amount_processed']
        extra_kwargs = {
            'secret_key': {'write_only': True},
            'webhook_secret': {'write_only': True},
        }
    
    def get_has_secret_key(self, obj):
        return bool(obj.secret_key)
        
    def get_has_webhook_secret(self, obj):
        return bool(obj.webhook_secret)
    
    def get_success_rate(self, obj):
        if obj.total_transactions == 0:
            return 0
        return round((obj.successful_transactions / obj.total_transactions) * 100, 2)

    def update(self, instance, validated_data):
        # Prevent overwriting keys with empty strings if they already exist
        # This fixes the issue where frontend sends empty strings for write-only fields
        secret_key = validated_data.get('secret_key')
        if secret_key == "" or secret_key is None:
            validated_data.pop('secret_key', None)
            
        webhook_secret = validated_data.get('webhook_secret')
        if webhook_secret == "" or webhook_secret is None:
            validated_data.pop('webhook_secret', None)
            
        return super().update(instance, validated_data)


class InvoiceSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    invoice_type_display = serializers.CharField(source='get_invoice_type_display', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    owner_name = serializers.CharField(source='owner_user.get_full_name', read_only=True, allow_null=True)
    responsible_user_name = serializers.CharField(source='responsible_user.get_full_name', read_only=True, allow_null=True)
    transfer_requested_by_name = serializers.CharField(source='transfer_requested_by.get_full_name', read_only=True, allow_null=True)
    transfer_reviewed_by_name = serializers.CharField(source='transfer_reviewed_by.get_full_name', read_only=True, allow_null=True)
    payment_responsibility_display = serializers.CharField(source='get_payment_responsibility_display', read_only=True)
    transfer_status_display = serializers.CharField(source='get_transfer_status_display', read_only=True)
    maintenance_request_title = serializers.CharField(source='maintenance_request.title', read_only=True, allow_null=True)
    
    # Frontend compatibility fields for Super Admin
    organization_name = serializers.CharField(source='building', read_only=True)
    admin_name = serializers.CharField(source='user.get_full_name', read_only=True)
    admin_email = serializers.CharField(source='user.email', read_only=True)
    plan = serializers.CharField(source='get_invoice_type_display', read_only=True)
    
    is_overdue = serializers.SerializerMethodField()
    days_until_due = serializers.SerializerMethodField()
    paid_by_role = serializers.SerializerMethodField()
    paid_by_role_display = serializers.SerializerMethodField()
    kyc_status = serializers.SerializerMethodField()
    tenant_details = serializers.SerializerMethodField()
    
    class Meta:
        model = Invoice
        fields = [
            'id', 'user', 'invoice_number', 'invoice_type', 'building', 'unit_number',
            'owner_user', 'owner_email', 'responsible_user', 'payment_responsibility',
            'subtotal', 'tax_amount', 'tax_percentage', 'discount_amount',
            'late_fee', 'total_amount', 'amount_paid', 'amount_due',
            'issue_date', 'due_date', 'period_start', 'period_end', 'status',
            'description', 'notes', 'terms_and_conditions', 'line_items', 'created_at', 'updated_at',
            'status_display', 'invoice_type_display', 'user_name', 'owner_name',
            'responsible_user_name', 'transfer_requested_by_name', 'transfer_reviewed_by_name',
            'payment_responsibility_display', 'transfer_status_display', 'maintenance_request_title',
            'organization_name', 'admin_name', 'admin_email', 'plan',
            'is_overdue', 'days_until_due', 'paid_by_role', 'paid_by_role_display',
            'kyc_status', 'tenant_details'
        ]
        read_only_fields = ['id', 'invoice_number', 'created_at', 'updated_at', 'amount_paid', 'amount_due']
    
    def get_kyc_status(self, obj):
        """
        Fetch the KYC status of the organization associated with the invoice user.
        Uses request-level cache to avoid per-invoice DB queries.
        """
        from tenants.models import Client, KYC
        
        tenant_id = getattr(obj.user, 'tenant_id', None)
        
        # Use serializer-level cache (dict keyed by tenant_id)
        cache_attr = '_kyc_status_cache'
        if not hasattr(self, cache_attr):
            setattr(self, cache_attr, {})
        kyc_cache = getattr(self, cache_attr)
        
        cache_key = tenant_id or getattr(obj, 'building', '') or ''
        if cache_key in kyc_cache:
            return kyc_cache[cache_key]
            
        try:
            client = None
            if tenant_id:
                client = Client.objects.filter(schema_name=tenant_id).first()
            elif obj.building:
                client = Client.objects.filter(name=obj.building).first()
                
            if client and hasattr(client, 'kyc'):
                result = client.kyc.status
            else:
                result = 'pending'
        except Exception:
            result = 'pending'
        
        kyc_cache[cache_key] = result
        return result

    def get_is_overdue(self, obj):
        from django.utils import timezone
        return obj.due_date < timezone.now().date() and obj.status not in ['paid', 'cancelled']
    
    def get_days_until_due(self, obj):
        from django.utils import timezone
        delta = obj.due_date - timezone.now().date()
        return delta.days

    def get_paid_by_role(self, obj):
        # Use prefetched completed payments to avoid N+1
        if hasattr(obj, 'completed_payments_prefetched'):
            completed = obj.completed_payments_prefetched
            payment = completed[0] if completed else None
        else:
            payment = obj.payments.filter(status='completed').select_related('user').order_by('-completed_at', '-created_at').first()
        if not payment or not payment.user:
            return None
        role = getattr(payment.user, 'role', None)
        # Cache result on the object to avoid recomputing in get_paid_by_role_display / get_tenant_details
        obj._cached_paid_by_role = role
        return role

    def get_paid_by_role_display(self, obj):
        # Use cached value if available to avoid repeating get_paid_by_role DB call
        if hasattr(obj, '_cached_paid_by_role'):
            role = obj._cached_paid_by_role
        else:
            role = self.get_paid_by_role(obj)
        return {
            'tenant': 'Paid by Tenant',
            'tenant_vendor': 'Paid by Tenant',
            'owner': 'Paid by Owner',
        }.get(role, 'Payment Pending')

    def get_tenant_details(self, obj):
        """
        Return tenant reference details only when an owner paid a tenant-linked invoice.
        Keeps backward compatibility by returning null in all other cases.
        """
        # Use cached value if available to avoid repeating get_paid_by_role DB call
        if hasattr(obj, '_cached_paid_by_role'):
            paid_by_role = obj._cached_paid_by_role
        else:
            paid_by_role = self.get_paid_by_role(obj)
        tenant_related = getattr(getattr(obj, 'user', None), 'role', None) in ('tenant', 'tenant_vendor')
        if not (tenant_related and paid_by_role == 'owner'):
            return None

        tenant = obj.user
        lease_start = obj.period_start
        lease_end = obj.period_end

        lease = getattr(getattr(obj, 'maintenance_request', None), 'lease', None)
        if lease:
            lease_start = lease.start_date or lease_start
            lease_end = lease.end_date or lease_end

        lease_period = None
        if lease_start or lease_end:
            lease_period = {
                'start_date': lease_start.isoformat() if lease_start else None,
                'end_date': lease_end.isoformat() if lease_end else None,
            }

        return {
            'name': tenant.get_full_name() or tenant.username,
            'email': tenant.email,
            'phone': getattr(tenant, 'phone', '') or None,
            'unit_number': obj.unit_number,
            'lease_period': lease_period,
        }



class InvoiceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            'user', 'invoice_type', 'maintenance_request', 'building', 'unit_number', 'subtotal',
            'tax_percentage', 'discount_amount', 'issue_date', 'due_date',
            'period_start', 'period_end', 'line_items', 'description', 'notes', 'status',
            'payment_responsibility', 'owner_user', 'owner_email', 'responsible_user',
        ]

    def validate(self, data):
        # Owners cannot be charged rent — they own their unit
        invoice_type = data.get('invoice_type')
        resident = data.get('user')
        maintenance_request = data.get('maintenance_request')
        if invoice_type == 'rent' and resident and getattr(resident, 'role', None) == 'owner':
            raise serializers.ValidationError({
                'invoice_type': (
                    'Rent invoices cannot be created for owners. '
                    'Owners are not charged rent. Use maintenance_fee, utility, or other types instead.'
                )
            })

        if maintenance_request and isinstance(maintenance_request, str):
            maintenance_request = MaintenanceRequest.objects.select_related('unit', 'lease').filter(id=maintenance_request).first()
            if maintenance_request:
                data['maintenance_request'] = maintenance_request

        if maintenance_request and getattr(maintenance_request, 'unit', None):
            unit = maintenance_request.unit
            data['building'] = unit.building.name if unit.building_id else data.get('building', '')
            data['unit_number'] = unit.unit_number
            owner_user = getattr(unit, 'owner_user', None)
            data['owner_user'] = data.get('owner_user') or owner_user
            data['owner_email'] = unit.owner_email or getattr(owner_user, 'email', '') or data.get('owner_email', '')
            if unit.owner_email and not data.get('owner_user'):
                data['owner_user'] = User.objects.filter(email__iexact=unit.owner_email).first()
            if not data.get('responsible_user'):
                data['responsible_user'] = resident
            if not data.get('payment_responsibility'):
                data['payment_responsibility'] = 'tenant'
        return data

    def create(self, validated_data):
        # Calculate tax
        subtotal = validated_data['subtotal']
        tax_percentage = validated_data.get('tax_percentage', 0)
        validated_data['tax_amount'] = (subtotal * tax_percentage) / 100

        if validated_data.get('maintenance_request') and not validated_data.get('owner_user'):
            unit = getattr(validated_data['maintenance_request'], 'unit', None)
            if unit:
                owner_user = getattr(unit, 'owner_user', None)
                validated_data['owner_user'] = owner_user or validated_data.get('owner_user')
                validated_data['owner_email'] = unit.owner_email or getattr(owner_user, 'email', '') or validated_data.get('owner_email', '')
                if unit.owner_email and not validated_data.get('owner_user'):
                    validated_data['owner_user'] = User.objects.filter(email__iexact=unit.owner_email).first()

        if not validated_data.get('responsible_user'):
            validated_data['responsible_user'] = validated_data.get('user')

        return super().create(validated_data)


class PaymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    tenant_name = serializers.CharField(source='user.get_full_name', read_only=True)
    tenant_email = serializers.CharField(source='user.email', read_only=True)
    unit_number = serializers.CharField(source='user.unit_number', read_only=True)
    paid_date = serializers.SerializerMethodField()
    due_date = serializers.SerializerMethodField()
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    gateway_name = serializers.CharField(source='gateway.get_gateway_type_display', read_only=True)
    payer_role = serializers.CharField(source='user.role', read_only=True)
    payer_role_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Payment
        fields = [
            'id', 'payment_number', 'user', 'invoice', 'amount', 'currency', 'payment_method', 
            'status', 'description', 'metadata', 'initiated_at', 'completed_at',
            'failed_at', 'failure_reason', 'created_at', 'updated_at',
            'status_display', 'payment_method_display', 'user_name', 
            'tenant_name', 'tenant_email', 'unit_number', 'paid_date',
            'due_date', 'invoice_number', 'gateway_name', 'payer_role',
            'payer_role_display', 'receipt_number', 'receipt_url', 'platform_fee', 'net_amount'
        ]
        read_only_fields = ['id', 'payment_number', 'created_at', 'updated_at', 'net_amount']

    def get_payer_role_display(self, obj):
        return {
            'tenant': 'Paid by Tenant',
            'tenant_vendor': 'Paid by Tenant',
            'owner': 'Paid by Owner',
        }.get(getattr(obj.user, 'role', None), 'Paid')

    def get_paid_date(self, obj):
        if obj.completed_at:
            return obj.completed_at
        return obj.metadata.get('payment_date') if obj.metadata else None

    def get_due_date(self, obj):
        if obj.invoice and obj.invoice.due_date:
            return obj.invoice.due_date
        return obj.metadata.get('due_date') if obj.metadata else None


class PaymentInitiateSerializer(serializers.Serializer):
    invoice_id = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    payment_method = serializers.CharField(max_length=50, required=False, default='card')
    gateway_type = serializers.ChoiceField(choices=['razorpay', 'stripe', 'paypal', 'manual'])
    save_payment_method = serializers.BooleanField(default=False)
    use_saved_method = serializers.UUIDField(required=False, allow_null=True)
    return_url = serializers.URLField(required=False)
    
    def validate(self, data):
        if data.get('use_saved_method'):
            # Validate saved payment method exists
            from .models import PaymentMethod
            try:
                PaymentMethod.objects.get(id=data['use_saved_method'])
            except PaymentMethod.DoesNotExist:
                raise serializers.ValidationError("Invalid payment method")
        
        return data


class PaymentMethodSerializer(serializers.ModelSerializer):
    method_type_display = serializers.CharField(source='get_method_type_display', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    gateway_name = serializers.CharField(source='gateway.get_gateway_type_display', read_only=True)
    
    class Meta:
        model = PaymentMethod
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'user']


class RefundSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_number = serializers.CharField(source='payment.payment_number', read_only=True)
    requested_by_name = serializers.CharField(source='requested_by.get_full_name', read_only=True)
    
    class Meta:
        model = Refund
        fields = '__all__'
        read_only_fields = ['id', 'refund_number', 'created_at', 'updated_at']


class PaymentReminderSerializer(serializers.ModelSerializer):
    reminder_type_display = serializers.CharField(source='get_reminder_type_display', read_only=True)
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    
    class Meta:
        model = PaymentReminder
        fields = '__all__'
        read_only_fields = ['id', 'created_at']


class PaymentPlanSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    progress_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentPlan
        fields = '__all__'
        read_only_fields = ['id', 'plan_number', 'created_at', 'updated_at', 'amount_paid', 'installments_paid']
    
    def get_progress_percentage(self, obj):
        if obj.total_amount == 0:
            return 0
        return round((float(obj.amount_paid) / float(obj.total_amount)) * 100, 2)


class InstallmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_number = serializers.CharField(source='payment.payment_number', read_only=True)
    
    class Meta:
        model = Installment
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class TransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = Transaction
        fields = '__all__'
        read_only_fields = ['id', 'transaction_number', 'created_at']


# Dashboard Serializers
class PaymentDashboardSerializer(serializers.Serializer):
    total_revenue = serializers.DecimalField(max_digits=15, decimal_places=2)
    revenue_this_month = serializers.DecimalField(max_digits=15, decimal_places=2)
    pending_payments = serializers.DecimalField(max_digits=15, decimal_places=2)
    overdue_invoices_count = serializers.IntegerField()
    overdue_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_invoices = serializers.IntegerField()
    paid_invoices = serializers.IntegerField()
    pending_invoices = serializers.IntegerField()


class RevenueStatisticsSerializer(serializers.Serializer):
    period = serializers.CharField()
    revenue = serializers.DecimalField(max_digits=15, decimal_places=2)
    transaction_count = serializers.IntegerField()
    
class AutoPayEnrollmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    frequency_display = serializers.CharField(source='get_frequency_display', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    payment_method_display = serializers.SerializerMethodField()
    payment_method_details = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()
    is_due = serializers.SerializerMethodField()
    
    class Meta:
        model = AutoPayEnrollment
        fields = '__all__'
        read_only_fields = ['id', 'enrollment_number', 'created_at', 'updated_at', 
                           'total_payments', 'successful_payments', 'failed_payments',
                           'total_amount_paid', 'current_retry_count']
    
    def get_payment_method_display(self, obj):
        if obj.payment_method:
            return str(obj.payment_method)
        return 'No payment method'
        
    def get_payment_method_details(self, obj):
        if obj.payment_method:
            # Import here to avoid circular dependencies if any
            from .serializers import PaymentMethodSerializer
            return PaymentMethodSerializer(obj.payment_method).data
        return None
    
    def get_success_rate(self, obj):
        if obj.total_payments == 0:
            return 0
        return round((obj.successful_payments / obj.total_payments) * 100, 2)
    
    def get_is_due(self, obj):
        from django.utils import timezone
        return obj.next_payment_date <= timezone.now().date() if obj.next_payment_date else False


class AutoPayEnrollmentCreateSerializer(serializers.Serializer):
    enrollment_type = serializers.CharField(default='rent')
    frequency = serializers.ChoiceField(choices=AutoPayEnrollment.FREQUENCY_CHOICES)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    mandate_limit_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    gateway_type = serializers.CharField(default='razorpay')
    payment_method_id = serializers.UUIDField()
    start_date = serializers.DateField()
    billing_day = serializers.IntegerField(min_value=1, max_value=31, default=1)
    notify_before_days = serializers.IntegerField(default=3)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        amount = attrs.get('amount')
        mandate_limit = attrs.get('mandate_limit_amount')
        if mandate_limit is not None and amount is not None and mandate_limit < amount:
            raise serializers.ValidationError({
                'mandate_limit_amount': 'Mandate limit must be greater than or equal to amount.'
            })
        return attrs
    
    def validate_payment_method_id(self, value):
        from .models import PaymentMethod
        try:
            PaymentMethod.objects.get(id=value)
        except PaymentMethod.DoesNotExist:
            raise serializers.ValidationError("Invalid payment method")
        return value


class AutoPaymentLogSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    enrollment_number = serializers.CharField(source='enrollment.enrollment_number', read_only=True)
    user_name = serializers.CharField(source='enrollment.user.get_full_name', read_only=True)
    
    class Meta:
        model = AutoPaymentLog
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class RecurringInvoiceSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    frequency_display = serializers.CharField(source='get_frequency_display', read_only=True)
    invoice_type_display = serializers.CharField(source='get_invoice_type_display', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    autopay_status = serializers.SerializerMethodField()
    
    class Meta:
        model = RecurringInvoice
        fields = '__all__'
        read_only_fields = ['id', 'template_number', 'created_at', 'updated_at', 
                           'invoices_generated', 'last_invoice_date']
    
    def get_autopay_status(self, obj):
        if obj.auto_pay_enabled and obj.autopay_enrollment:
            return obj.autopay_enrollment.status
        return 'not_enrolled'    