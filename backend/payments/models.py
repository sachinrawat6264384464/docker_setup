# payments/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator  # ← FIXED
from django.utils import timezone
from decimal import Decimal
import uuid
from cryptography.fernet import Fernet
from django.conf import settings

User = get_user_model()

# Fallback dev key - in production this MUST be in settings.py
DEFAULT_ENCRYPTION_KEY = b'vLpD9XnO_M8PjYwN6ZqT2bC4A1H3sR5uF7E9dK0xG2o='

class EncryptedCharField(models.CharField):
    """Custom field to automatically encrypt/decrypt strings using Fernet."""
    
    def get_fernet(self):
        key = getattr(settings, 'ENCRYPTION_KEY', DEFAULT_ENCRYPTION_KEY)
        return Fernet(key)

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return self.get_fernet().decrypt(value.encode('utf-8')).decode('utf-8')
        except Exception:
            # If it fails to decrypt, assume it's legacy plaintext
            return value

    def get_prep_value(self, value):
        if not value:
            return value
        # Fernet tokens start with gAAAA. We can check this to avoid double encryption.
        if value.startswith('gAAAA'):
            # Double check if it decrypts successfully before assuming it's encrypted
            try:
                self.get_fernet().decrypt(value.encode('utf-8'))
                return value
            except Exception:
                pass
        try:
            return self.get_fernet().encrypt(value.encode('utf-8')).decode('utf-8')
        except Exception:
            return value

class PaymentGateway(models.Model):
    """Payment gateway configuration"""
    GATEWAY_CHOICES = [
        ('razorpay', 'Razorpay'),
        ('stripe', 'Stripe'),
        ('paypal', 'PayPal'),
        ('manual', 'Manual/Cash'),
    ]

    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    gateway_type = models.CharField(max_length=50, choices=GATEWAY_CHOICES, unique=True)
    is_active = models.BooleanField(default=True)
    is_test_mode = models.BooleanField(default=True)
    
    # API Credentials (encrypted in production)
    public_key = models.CharField(max_length=500, blank=True)
    secret_key = EncryptedCharField(max_length=500, blank=True)
    webhook_secret = EncryptedCharField(max_length=500, blank=True)
    
    # Stripe Connect Express onboarding fields
    stripe_connected_account_id = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Stripe Express Connected Account ID (acct_xxx)"
    )
    charges_enabled = models.BooleanField(
        default=False,
        help_text="True when Stripe confirms HOA can accept payments"
    )
    payouts_enabled = models.BooleanField(
        default=False,
        help_text="True when HOA bank account is verified for payouts"
    )
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('NOT_CONNECTED', 'Not Connected'),
            ('PENDING', 'Pending KYC'),
            ('ACTIVE', 'Active'),
            ('DISABLED', 'Disabled'),
        ],
        default='NOT_CONNECTED',
        help_text="Stripe Connect onboarding status"
    )
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    
    onboarding_started   = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)
    bank_name            = models.CharField(max_length=100, blank=True, null=True)
    bank_last4           = models.CharField(max_length=4, blank=True, null=True)
    bank_connected       = models.BooleanField(default=False)
    financial_connections_account_id = models.CharField(
        max_length=100, blank=True, null=True
    )
    
    # Synced from Stripe Webhook (Reverse Sync)
    business_name = models.CharField(max_length=255, blank=True, null=True)
    business_phone = models.CharField(max_length=50, blank=True, null=True)
    business_url = models.CharField(max_length=255, blank=True, null=True)
    support_email = models.EmailField(blank=True, null=True)
    stripe_verification_status = models.CharField(max_length=50, blank=True, null=True)
    
    # Gateway Settings
    currency = models.CharField(max_length=3, default='USD')
    settings = models.JSONField(default=dict, blank=True)
    
    # Statistics
    total_transactions = models.IntegerField(default=0)
    successful_transactions = models.IntegerField(default=0)
    failed_transactions = models.IntegerField(default=0)
    total_amount_processed = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['gateway_type']

    def __str__(self):
        return f"{self.get_gateway_type_display()} ({'Test' if self.is_test_mode else 'Live'})"

class OwnerPaymentProfile(models.Model):
    """Stores Stripe Connect onboarding details for property owners"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name='payment_profile', limit_choices_to={'role__in': ['owner']})
    
    stripe_connected_account_id = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Stripe Express Connected Account ID (acct_xxx) for the owner"
    )
    charges_enabled = models.BooleanField(
        default=False,
        help_text="True when Stripe confirms owner can accept payments"
    )
    payouts_enabled = models.BooleanField(
        default=False,
        help_text="True when owner bank account is verified for payouts"
    )
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('NOT_CONNECTED', 'Not Connected'),
            ('PENDING', 'Pending KYC'),
            ('ACTIVE', 'Active'),
            ('DISABLED', 'Disabled'),
        ],
        default='NOT_CONNECTED',
        help_text="Stripe Connect onboarding status"
    )
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_last4 = models.CharField(max_length=4, blank=True, null=True)
    bank_connected = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Payment Profile for Owner: {self.owner.get_full_name() or self.owner.username}"

class Invoice(models.Model):
    """Invoices for rent, fees, and other charges"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('viewed', 'Viewed'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('partially_paid', 'Partially Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]
    
    INVOICE_TYPES = [
        ('rent', 'Total Rent'),
        ('maintenance_fee', 'Total Dues'),
        ('parking_fee', 'Parking Fee'),
        ('amenity_fee', 'Amenity Fee'),
        ('security_deposit', 'Security Deposit'),
        ('late_fee', 'Late Fee'),
        ('utility', 'Utility Bill'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_number = models.CharField(max_length=50, unique=True)
    
    # Billing Information
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    invoice_type = models.CharField(max_length=50, choices=INVOICE_TYPES)
    
    # Property Details
    building = models.CharField(max_length=200)
    unit_number = models.CharField(max_length=50)
    maintenance_request = models.ForeignKey(
        'maintenance.MaintenanceRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices',
    )
    owner_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='owner_invoices',
    )
    owner_email = models.EmailField(blank=True, default='')
    responsible_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='responsible_invoices',
    )
    payment_responsibility = models.CharField(
        max_length=20,
        choices=[('tenant', 'Tenant'), ('owner', 'Owner')],
        default='tenant',
    )
    transfer_status = models.CharField(
        max_length=20,
        choices=[
            ('none', 'None'),
            ('requested', 'Requested'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        default='none',
    )
    transfer_requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_transfer_requests',
    )
    transfer_requested_at = models.DateTimeField(null=True, blank=True)
    transfer_reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_transfer_reviews',
    )
    transfer_reviewed_at = models.DateTimeField(null=True, blank=True)
    transfer_rejection_reason = models.TextField(blank=True)
    
    # Amounts
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    late_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    late_fee_applied = models.BooleanField(default=False)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Dates
    issue_date = models.DateField()
    due_date = models.DateField()
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    billing_month = models.IntegerField(null=True, blank=True)
    billing_year = models.IntegerField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Line Items
    line_items = models.JSONField(default=list, blank=True)
    
    # Notes
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    terms_and_conditions = models.TextField(blank=True)
    
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Tracking
    sent_at = models.DateTimeField(null=True, blank=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # Recurring
    is_recurring = models.BooleanField(default=False)
    recurring_frequency = models.CharField(max_length=20, blank=True)  # monthly, quarterly, yearly
    parent_invoice = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='recurring_invoices')
    
    # Document
    pdf_file = models.CharField(max_length=500, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='invoices_created', blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['invoice_number']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['due_date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.user.get_full_name()} - ${self.total_amount}"
    
    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self._generate_invoice_number()
            
        if not self.expires_at:
            from datetime import timedelta
            self.expires_at = timezone.now() + timedelta(hours=124)
            
        if self.subtotal is None:
            self.subtotal = Decimal('0.00')

        # Coerce all amount fields to Decimal before arithmetic.
        # Field defaults (0.00) are Python floats until persisted to the DB;
        # mixing Decimal + float raises TypeError.
        subtotal        = Decimal(str(self.subtotal        or 0))
        tax_amount      = Decimal(str(self.tax_amount      or 0))
        late_fee        = Decimal(str(self.late_fee        or 0))
        discount_amount = Decimal(str(self.discount_amount or 0))
        amount_paid     = Decimal(str(self.amount_paid     or 0))

        # Calculate total
        self.total_amount = subtotal + tax_amount + late_fee - discount_amount
        current_platform_fee = Decimal('0.00')
        if isinstance(self.line_items, list):
            for item in self.line_items:
                if isinstance(item, dict) and item.get('type') == 'platform_fee':
                    current_platform_fee = Decimal(str(item.get('amount', 0)))
                    break
        
        self.total_amount += current_platform_fee
        self.amount_due = self.total_amount - amount_paid
        
        # Update status based on payment (use coerced Decimal locals, not raw self.*)
        # IMPORTANT: Only auto-mark as 'paid' when there is an actual balance to pay.
        # A zero-subtotal invoice (0 >= 0) must NOT be auto-promoted to 'paid'.
        if self.total_amount > 0 and amount_paid >= self.total_amount:
            self.status = 'paid'
            if not self.paid_at:
                self.paid_at = timezone.now()
        elif amount_paid > 0:
            self.status = 'partially_paid'
        elif self.due_date < timezone.now().date() and self.status not in ['paid', 'cancelled']:
            self.status = 'overdue'
        
        super().save(*args, **kwargs)
        
        # Synchronization: Update AmenityBooking if this was an amenity fee invoice that just got paid
        if self.status == 'paid' and self.invoice_type == 'amenity_fee' and self.notes:
            if 'Booking #' in self.notes:
                try:
                    import re
                    match = re.search(r'Booking #([\w-]+)', self.notes)
                    if match:
                        identifier = match.group(1)
                        from amenities.models import AmenityBooking
                        # The identifier might be the booking_number or the UUID
                        booking = AmenityBooking.objects.filter(booking_number=identifier).first()
                        if not booking:
                            # Try by UUID in case it fell back to bookingId
                            try:
                                booking = AmenityBooking.objects.filter(id=identifier).first()
                            except ValueError:
                                pass
                                
                        if booking and booking.payment_status != 'paid':
                            booking.payment_status = 'paid'
                            booking.payment_reference = self.invoice_number
                            # Avoid signals triggering unnecessary invoice recalculations down the line
                            booking.save(update_fields=['payment_status', 'payment_reference', 'updated_at'])
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Could not sync amenity booking payment status: {e}")
    
    def _generate_invoice_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m')
        prefix = f'INV-{date_str}-'
        last = Invoice.objects.filter(
            invoice_number__startswith=prefix
        ).order_by('-invoice_number').values_list('invoice_number', flat=True).first()
        if last:
            try:
                count = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                count = Invoice.objects.filter(invoice_number__startswith=prefix).count() + 1
        else:
            count = 1
        return f'{prefix}{count:05d}'


class Payment(models.Model):
    """Payment transactions"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
        ('partially_refunded', 'Partially Refunded'),
    ]
    
    PAYMENT_METHODS = [
        ('razorpay_upi', 'UPI (Razorpay)'),
        ('razorpay_card', 'Card (Razorpay)'),
        ('razorpay_netbanking', 'Net Banking (Razorpay)'),
        ('razorpay_wallet', 'Wallet (Razorpay)'),
        ('stripe_card', 'Card (Stripe)'),
        ('stripe_upi', 'UPI (Stripe)'),
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('bank_transfer', 'Bank Transfer'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_number = models.CharField(max_length=50, unique=True)
    
    # Payment Details
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    
    # Amount
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    currency = models.CharField(max_length=3, default='USD')
    
    # Payment Method
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHODS)
    gateway = models.ForeignKey(PaymentGateway, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Gateway Transaction Details
    gateway_transaction_id = models.CharField(max_length=200, blank=True)
    gateway_payment_id = models.CharField(max_length=200, blank=True)
    gateway_order_id = models.CharField(max_length=200, blank=True)
    gateway_signature = models.CharField(max_length=500, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Fees
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    gateway_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    net_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Additional Details
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Refund Information
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    refund_reason = models.TextField(blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    
    # Receipt
    receipt_number = models.CharField(max_length=50, blank=True)
    receipt_url = models.CharField(max_length=500, blank=True)
    
    # Timestamps
    initiated_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payment_number']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['gateway_transaction_id']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.payment_number} - {self.user.get_full_name()} - ₹{self.amount}"
    
    def save(self, *args, **kwargs):
        if not self.payment_number:
            self.payment_number = self._generate_payment_number()

        # Extract platform fee from invoice if not set
        if self.invoice and (self.platform_fee is None or Decimal(str(self.platform_fee)) == Decimal('0.00')):
            if isinstance(self.invoice.line_items, list):
                for item in self.invoice.line_items:
                    if isinstance(item, dict) and item.get('type') == 'platform_fee':
                        self.platform_fee = Decimal(str(item.get('amount', 0.00)))
                        break

        # Coerce all amount fields to Decimal before arithmetic.
        # Field defaults (0.00) are Python floats in memory until persisted;
        # mixing Decimal + float raises TypeError.
        amount       = Decimal(str(self.amount       or 0))
        platform_fee = Decimal(str(self.platform_fee or 0))
        gateway_fee  = Decimal(str(self.gateway_fee  or 0))

        # Calculate net amount
        self.net_amount = amount - platform_fee - gateway_fee

        # Update status-related timestamps
        if self.status == 'completed' and not self.completed_at:
            # Fallback to metadata payment_date if provided (useful for manual/historical recordings)
            manual_date = self.metadata.get('payment_date') if self.metadata else None
            if manual_date:
                try:
                    from datetime import datetime
                    from django.utils.dateparse import parse_datetime
                    parsed = parse_datetime(manual_date)
                    if not parsed:
                        from django.utils.dateparse import parse_date
                        parsed_date = parse_date(manual_date)
                        if parsed_date:
                            parsed = timezone.make_aware(datetime.combine(parsed_date, datetime.min.time()))
                    self.completed_at = parsed or timezone.now()
                except Exception:
                    self.completed_at = timezone.now()
            else:
                self.completed_at = timezone.now()
        elif self.status == 'failed' and not self.failed_at:
            self.failed_at = timezone.now()

        is_new = self._state.adding
        old_status = None
        if not is_new:
            try:
                old_status = Payment.objects.get(pk=self.pk).status
            except Exception:
                pass

        # Update invoice ONLY IF payment just transitioned to completed
        if self.status == 'completed' and old_status != 'completed' and self.invoice:
            self.invoice.amount_paid = Decimal(str(self.invoice.amount_paid or 0)) + amount
            self.invoice.save()

        super().save(*args, **kwargs)

        # Send payment success notification
        if old_status != 'completed' and self.status == 'completed':
            try:
                from notifications.services import NotificationService
                if self.invoice:
                    NotificationService.send_invoice_notification(self.invoice, 'invoice_paid')
                else:
                    NotificationService.send(
                        user=self.user,
                        title='Payment Successful',
                        message=f'Your payment of ₹{self.amount} was processed successfully.',
                        notification_type='payment',
                        priority='low',
                        send_push=True,
                        send_email=True,
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to send payment success notification: {e}")
    
    def _generate_payment_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        count = Payment.objects.filter(
            payment_number__startswith=f'PAY-{date_str}'
        ).count() + 1
        return f'PAY-{date_str}-{count:05d}'


class PaymentMethod(models.Model):
    """Saved payment methods for users"""
    METHOD_TYPES = [
        ('razorpay_card', 'Card (Razorpay)'),
        ('razorpay_upi', 'UPI (Razorpay)'),
        ('stripe_card', 'Card (Stripe)'),
        ('paypal', 'PayPal'),
        ('bank_account', 'Bank Account'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_methods')
    method_type = models.CharField(max_length=50, choices=METHOD_TYPES)
    
    # Gateway Details
    gateway = models.ForeignKey(PaymentGateway, on_delete=models.CASCADE)
    gateway_payment_method_id = models.CharField(max_length=200)
    gateway_customer_id = models.CharField(max_length=200, blank=True)
    
    # Card Details (masked)
    card_last4 = models.CharField(max_length=4, blank=True)
    card_brand = models.CharField(max_length=50, blank=True)
    card_exp_month = models.IntegerField(null=True, blank=True)
    card_exp_year = models.IntegerField(null=True, blank=True)
    
    # Bank Details (masked)
    bank_name = models.CharField(max_length=200, blank=True)
    account_last4 = models.CharField(max_length=4, blank=True)
    
    # UPI Details
    upi_id = models.CharField(max_length=200, blank=True)
    
    # Settings
    is_default = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        if self.card_last4:
            return f"{self.card_brand} •••• {self.card_last4}"
        elif self.upi_id:
            return f"UPI: {self.upi_id}"
        return f"{self.get_method_type_display()}"


class Refund(models.Model):
    """Refund records"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    refund_number = models.CharField(max_length=50, unique=True)
    
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='refunds')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Gateway Details
    gateway_refund_id = models.CharField(max_length=200, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='refunds_requested')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='refunds_approved')
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.refund_number} - ₹{self.amount}"
    
    def save(self, *args, **kwargs):
        if not self.refund_number:
            self.refund_number = self._generate_refund_number()
        super().save(*args, **kwargs)
    
    def _generate_refund_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        count = Refund.objects.filter(
            refund_number__startswith=f'REF-{date_str}'
        ).count() + 1
        return f'REF-{date_str}-{count:05d}'


class PaymentReminder(models.Model):
    """Payment reminders for overdue invoices"""
    REMINDER_TYPES = [
        ('before_due', 'Before Due Date'),
        ('on_due', 'On Due Date'),
        ('after_due', 'After Due Date (Overdue)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='reminders')
    reminder_type = models.CharField(max_length=50, choices=REMINDER_TYPES)
    
    # Delivery
    send_email = models.BooleanField(default=True)
    send_sms = models.BooleanField(default=False)
    send_push = models.BooleanField(default=True)
    
    # Status
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    # Schedule
    scheduled_for = models.DateTimeField()
    
    message = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['scheduled_for']

    def __str__(self):
        return f"Reminder for {self.invoice.invoice_number} - {self.get_reminder_type_display()}"


class PaymentPlan(models.Model):
    """Installment payment plans"""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('defaulted', 'Defaulted'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan_number = models.CharField(max_length=50, unique=True)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_plans')
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payment_plans')
    
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    installments = models.IntegerField(validators=[MinValueValidator(2)])
    installment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    start_date = models.DateField()
    frequency = models.CharField(max_length=20, default='monthly')  # weekly, biweekly, monthly
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    installments_paid = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.plan_number} - {self.user.get_full_name()}"

    def save(self, *args, **kwargs):
        if not self.plan_number:
            self.plan_number = self._generate_plan_number()
        super().save(*args, **kwargs)

    def _generate_plan_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m')
        count = PaymentPlan.objects.filter(
            plan_number__startswith=f'PPL-{date_str}'
        ).count() + 1
        return f'PPL-{date_str}-{count:05d}'


class Installment(models.Model):
    """Individual installments in a payment plan"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('skipped', 'Skipped'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    payment_plan = models.ForeignKey(PaymentPlan, on_delete=models.CASCADE, related_name='plan_installments')
    installment_number = models.IntegerField()
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['payment_plan', 'installment_number']
        unique_together = ['payment_plan', 'installment_number']

    def __str__(self):
        return f"{self.payment_plan.plan_number} - Installment {self.installment_number}"


class Transaction(models.Model):
    """Financial transaction log"""
    TRANSACTION_TYPES = [
        ('payment', 'Payment Received'),
        ('refund', 'Refund Issued'),
        ('fee', 'Fee Charged'),
        ('adjustment', 'Adjustment'),
        ('transfer', 'Transfer'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_number = models.CharField(max_length=50, unique=True)
    
    transaction_type = models.CharField(max_length=50, choices=TRANSACTION_TYPES)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    refund = models.ForeignKey(Refund, on_delete=models.SET_NULL, null=True, blank=True)
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transactions_created', blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_number} - {self.get_transaction_type_display()}"

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            self.transaction_number = self._generate_transaction_number()
        super().save(*args, **kwargs)

    def _generate_transaction_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        count = Transaction.objects.filter(
            transaction_number__startswith=f'TRX-{date_str}'
        ).count() + 1
        return f'TRX-{date_str}-{count:05d}'

# payments/models.py - ADD THESE MODELS TO YOUR EXISTING PAYMENTS MODELS

class AutoPayEnrollment(models.Model):
    """Auto-pay enrollment for recurring payments"""
    STATUS_CHOICES = [
        ('pending', 'Pending Authorization'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Failed'),
    ]
    
    FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', 'Semi-Annual'),
        ('annual', 'Annual'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment_number = models.CharField(max_length=50, unique=True)
    
    # User and Gateway
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='autopay_enrollments')
    gateway = models.ForeignKey(PaymentGateway, on_delete=models.CASCADE)
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.SET_NULL, null=True)
    
    # Enrollment Details
    enrollment_type = models.CharField(max_length=50, default='rent')  # rent, maintenance_fee, etc.
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    mandate_limit_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Razorpay Specific
    razorpay_customer_id = models.CharField(max_length=200, blank=True, default='')
    razorpay_subscription_id = models.CharField(max_length=200, blank=True, default='')
    razorpay_plan_id = models.CharField(max_length=200, blank=True, default='')

    # Stripe Specific
    stripe_customer_id = models.CharField(max_length=200, blank=True, default='')
    stripe_subscription_id = models.CharField(max_length=200, blank=True, default='')

    
    # Scheduling
    start_date = models.DateField()
    next_payment_date = models.DateField()
    last_payment_date = models.DateField(null=True, blank=True)
    billing_day = models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(31)])
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Retry Settings
    max_retry_attempts = models.IntegerField(default=3)
    current_retry_count = models.IntegerField(default=0)
    retry_interval_days = models.IntegerField(default=3)
    
    # Statistics
    total_payments = models.IntegerField(default=0)
    successful_payments = models.IntegerField(default=0)
    failed_payments = models.IntegerField(default=0)
    total_amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Notifications
    notify_before_days = models.IntegerField(default=3)
    send_payment_confirmation = models.BooleanField(default=True)
    send_failure_notification = models.BooleanField(default=True)
    
    # Additional Info
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Pause/Resume
    paused_at = models.DateTimeField(null=True, blank=True)
    paused_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                  related_name='autopay_enrollments_created', blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['enrollment_number']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['next_payment_date', 'status']),
            models.Index(fields=['razorpay_subscription_id']),
            models.Index(fields=['stripe_subscription_id']),
        ]


    def __str__(self):
        return f"{self.enrollment_number} - {self.user.get_full_name()} - ₹{self.amount}/{self.frequency}"
    
    def save(self, *args, **kwargs):
        if not self.enrollment_number:
            self.enrollment_number = self._generate_enrollment_number()
        super().save(*args, **kwargs)
    
    def _generate_enrollment_number(self):
        from datetime import datetime
        from django.db.models import Max
        
        date_str = datetime.now().strftime('%Y%m')
        prefix = f'APE-{date_str}-'
        
        last_item = AutoPayEnrollment.objects.filter(
            enrollment_number__startswith=prefix
        ).aggregate(Max('enrollment_number'))['enrollment_number__max']
        
        if last_item:
            try:
                # Extract the last 5 digits and increment
                count = int(last_item.split('-')[-1]) + 1
            except (ValueError, IndexError):
                count = 1
        else:
            count = 1
            
        return f'{prefix}{count:05d}'
    
    def calculate_next_payment_date(self):
        """Calculate next payment date based on frequency"""
        from dateutil.relativedelta import relativedelta
        
        if self.frequency == 'monthly':
            return self.last_payment_date + relativedelta(months=1) if self.last_payment_date else self.start_date
        elif self.frequency == 'quarterly':
            return self.last_payment_date + relativedelta(months=3) if self.last_payment_date else self.start_date
        elif self.frequency == 'semi_annual':
            return self.last_payment_date + relativedelta(months=6) if self.last_payment_date else self.start_date
        elif self.frequency == 'annual':
            return self.last_payment_date + relativedelta(years=1) if self.last_payment_date else self.start_date
        
        return self.start_date


class AutoPaymentLog(models.Model):
    """Log of auto-payment attempts"""
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('processing', 'Processing'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('retrying', 'Retrying'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    enrollment = models.ForeignKey(AutoPayEnrollment, on_delete=models.CASCADE, related_name='payment_logs')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Payment Details
    scheduled_date = models.DateField()
    attempted_date = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    
    # Retry Information
    attempt_number = models.IntegerField(default=1)
    next_retry_date = models.DateTimeField(null=True, blank=True)
    
    # Error Information
    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)
    
    # Gateway Response
    gateway_response = models.JSONField(default=dict, blank=True)
    
    # Notifications
    user_notified = models.BooleanField(default=False)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_date', '-created_at']
        indexes = [
            models.Index(fields=['enrollment', 'status']),
            models.Index(fields=['scheduled_date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.enrollment.enrollment_number} - {self.scheduled_date} - {self.status}"


class RazorpayWebhookEvent(models.Model):
    """Store processed Razorpay webhook events for idempotency and traceability."""

    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.event_id} ({self.event_type or 'unknown'})"


class RecurringInvoice(models.Model):
    """Template for recurring invoices"""
    FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', 'Semi-Annual'),
        ('annual', 'Annual'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template_number = models.CharField(max_length=50, unique=True)
    
    # User
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recurring_invoices')
    
    # Invoice Details
    invoice_type = models.CharField(max_length=50, choices=Invoice.INVOICE_TYPES)
    description = models.TextField()
    
    # Property Details
    building = models.CharField(max_length=200)
    unit_number = models.CharField(max_length=50)
    
    # Amounts
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    # Recurrence
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    next_invoice_date = models.DateField()
    billing_day = models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(31)])
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Auto-pay Integration
    auto_pay_enabled = models.BooleanField(default=False)
    autopay_enrollment = models.ForeignKey(AutoPayEnrollment, on_delete=models.SET_NULL, 
                                          null=True, blank=True, related_name='recurring_invoices')
    
    # Line Items Template
    line_items_template = models.JSONField(default=list, blank=True)
    
    # Statistics
    invoices_generated = models.IntegerField(default=0)
    last_invoice_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                  related_name='recurring_invoices_created', blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['template_number']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['next_invoice_date', 'status']),
        ]

    def __str__(self):
        return f"{self.template_number} - {self.user.get_full_name()} - {self.frequency}"
    
    def save(self, *args, **kwargs):
        if not self.template_number:
            self.template_number = self._generate_template_number()
        super().save(*args, **kwargs)
    
    def _generate_template_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m')
        count = RecurringInvoice.objects.filter(
            template_number__startswith=f'RIT-{date_str}'
        ).count() + 1
        return f'RIT-{date_str}-{count:05d}'


class WebhookEventLog(models.Model):
    stripe_event_id = models.CharField(max_length=255, unique=True)
    event_type      = models.CharField(max_length=100)
    processed_at    = models.DateTimeField(auto_now_add=True)
    payload         = models.JSONField()

    class Meta:
        indexes = [models.Index(fields=['stripe_event_id'])]

    def __str__(self):
        return f"{self.event_type} — {self.stripe_event_id}"