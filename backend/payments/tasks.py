# payments/tasks.py - COMPLETE VERSION WITH ALL SCHEDULED TASKS

from celery import shared_task
from django.utils import timezone
from django.db.models import Sum, Count, Q
from datetime import timedelta, datetime
from decimal import Decimal
import logging
from notifications.services import NotificationService

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# AUTO-PAY PROCESSING TASKS
# ═══════════════════════════════════════════════════════════════════════════

@shared_task(name='payments.tasks.run_autopay_for_all_tenants')
def run_autopay_for_all_tenants():
    """
    Master task to run autopay for all tenants.
    Iterates through all non-public tenants and triggers processing.
    """
    from tenants.models import Client
    
    tenants = Client.objects.exclude(schema_name='public')
    logger.info(f"Starting autopay for {tenants.count()} tenants")
    
    for tenant in tenants:
        try:
            logger.info(f"Triggering autopay for tenant: {tenant.schema_name}")
            # Pass schema_name so the worker knows which schema to use
            process_scheduled_autopay_payments.delay(schema_name=tenant.schema_name)
        except Exception as e:
            logger.error(f"Error triggering autopay for tenant {tenant.schema_name}: {e}")

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_scheduled_autopay_payments(self, schema_name=None):
    """
    Process all auto-pay payments that are due today.
    Supports Razorpay gateway.
    Run this task daily via Celery Beat at 2 AM.
    """
    from payments.models import AutoPayEnrollment, AutoPaymentLog, Payment
    from payments.services.razorpay_autopay_service import RazorpayAutoPayService
    from django_tenants.utils import schema_context
    from django.db import connection

    # Use schema_context if schema_name is provided (for multi-tenant safety in workers)
    if schema_name:
        connection.set_schema(schema_name)
        logger.info(f"Processing autopay for schema: {schema_name}")

    try:
        today = timezone.now().date()

        # Get all active enrollments due today
        due_enrollments = AutoPayEnrollment.objects.filter(
            status='active',
            next_payment_date__lte=today
        ).select_related('user', 'gateway', 'payment_method')

        logger.info(f"Processing {due_enrollments.count()} auto-pay enrollments")

        success_count = 0
        failure_count = 0

        for enrollment in due_enrollments:
            try:
                gateway_type = enrollment.gateway.gateway_type
                charge_metadata = {
                    'enrollment_id': str(enrollment.id),
                    'enrollment_number': enrollment.enrollment_number,
                    'enrollment_type': enrollment.enrollment_type,
                    'user_id': str(enrollment.user.id),
                    'email': enrollment.user.email,
                    'contact': getattr(enrollment.user, 'phone', '')
                }

                # Select service and customer_id based on gateway type
                if gateway_type != 'razorpay':
                    logger.warning(f"Unsupported gateway {gateway_type} for enrollment {enrollment.enrollment_number}, skipping")
                    continue
                service = RazorpayAutoPayService(enrollment.gateway)
                customer_id = enrollment.razorpay_customer_id
                payment_method_label = 'razorpay_card'

                # Get the payment token from the linked payment method
                token_id = enrollment.payment_method.gateway_payment_method_id if enrollment.payment_method else None

                # Charge customer off-session
                result = service.charge_customer_off_session(
                    customer_id=customer_id,
                    amount=float(enrollment.amount),
                    metadata=charge_metadata,
                    token_id=token_id
                )

                if result['success']:
                    # Create payment record
                    payment = Payment.objects.create(
                        user=enrollment.user,
                        amount=enrollment.amount,
                        currency=enrollment.gateway.currency,
                        payment_method=payment_method_label,
                        gateway=enrollment.gateway,
                        gateway_transaction_id=result.get('charge_id', ''),
                        gateway_payment_id=result.get('payment_intent_id', result.get('order_id', '')),
                        status='completed',
                        description=f"Auto-pay: {enrollment.enrollment_type}",
                        metadata={'enrollment_id': str(enrollment.id)},
                        completed_at=timezone.now()
                    )

                    # --- NEW: Admin Visibility Fix ---
                    # The Admin Dashboard fetches Invoices (getInvoices), but standalone autopay 
                    # creates only a Payment. We need to create/link an Invoice so it shows up for Admins.
                    try:
                        from payments.models import Invoice
                        
                        # Use enrollment description or default
                        description = enrollment.description or f"Auto-pay {enrollment.enrollment_type}"
                        
                        # Try to find a building/unit from user if enrollment doesn't have it
                        building = getattr(enrollment.user, 'building', 'System')
                        unit = getattr(enrollment.user, 'unit_number', 'N/A')

                        invoice = Invoice.objects.create(
                            user=enrollment.user,
                            invoice_type=enrollment.enrollment_type if enrollment.enrollment_type in dict(Invoice.INVOICE_TYPES) else 'other',
                            building=building,
                            unit_number=unit,
                            subtotal=enrollment.amount,
                            total_amount=enrollment.amount,
                            amount_paid=enrollment.amount,
                            amount_due=0,
                            issue_date=today,
                            due_date=today,
                            status='paid',
                            paid_at=timezone.now(),
                            description=description,
                            notes=f"Automatically generated via Autopay Enrollment {enrollment.enrollment_number}"
                        )
                        # Link payment to the new invoice
                        payment.invoice = invoice
                        payment.save()
                        logger.info(f"Generated paid invoice {invoice.invoice_number} for autopay payment {payment.payment_number}")
                    except Exception as inv_err:
                        logger.error(f"Failed to generate invoice for autopay: {str(inv_err)}")
                    # --- END FIX ---

                    # Update enrollment
                    enrollment.successful_payments += 1
                    enrollment.total_payments += 1
                    enrollment.total_amount_paid += enrollment.amount
                    enrollment.last_payment_date = today
                    enrollment.next_payment_date = enrollment.calculate_next_payment_date()
                    enrollment.current_retry_count = 0
                    enrollment.save()

                    # Create successful log
                    AutoPaymentLog.objects.create(
                        enrollment=enrollment,
                        payment=payment,
                        scheduled_date=today,
                        attempted_date=timezone.now(),
                        completed_date=timezone.now(),
                        amount=enrollment.amount,
                        status='succeeded',
                        gateway_response=result
                    )

                    # Send success notification
                    send_autopay_success_notification.delay(enrollment.id, payment.id)

                    success_count += 1
                    logger.info(f"Successfully processed auto-pay for enrollment {enrollment.enrollment_number} via {gateway_type}")

                else:
                    # Payment failed
                    enrollment.failed_payments += 1
                    enrollment.total_payments += 1
                    enrollment.current_retry_count += 1

                    # Check if max retries reached
                    if enrollment.current_retry_count >= enrollment.max_retry_attempts:
                        enrollment.status = 'failed'
                        logger.warning(f"Enrollment {enrollment.enrollment_number} failed after max retries")

                    enrollment.save()

                    # Create failed log
                    log = AutoPaymentLog.objects.create(
                        enrollment=enrollment,
                        scheduled_date=today,
                        attempted_date=timezone.now(),
                        amount=enrollment.amount,
                        status='failed',
                        attempt_number=enrollment.current_retry_count,
                        error_message=result.get('error', 'Unknown error'),
                        error_code=result.get('decline_code', ''),
                        gateway_response=result
                    )

                    # Schedule retry if not max attempts
                    if enrollment.current_retry_count < enrollment.max_retry_attempts:
                        retry_date = timezone.now() + timedelta(days=enrollment.retry_interval_days)
                        log.next_retry_date = retry_date
                        log.status = 'retrying'
                        log.save()

                        # Schedule retry task
                        retry_failed_autopay_payment.apply_async(
                            args=[enrollment.id],
                            eta=retry_date
                        )

                    # Send failure notification
                    send_autopay_failure_notification.delay(enrollment.id, log.id)

                    failure_count += 1
                    logger.error(f"Failed to process auto-pay for enrollment {enrollment.enrollment_number}: {result.get('error')}")

            except Exception as e:
                failure_count += 1
                logger.error(f"Error processing enrollment {enrollment.id}: {str(e)}")
                continue

        logger.info(f"Auto-pay processing complete: {success_count} succeeded, {failure_count} failed")
        return f"Processed {due_enrollments.count()} enrollments: {success_count} succeeded, {failure_count} failed"

    except Exception as exc:
        logger.error('Task %s failed: %s', self.name, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def retry_failed_autopay_payment(self, enrollment_id):
    """Retry a failed auto-pay payment via Razorpay"""
    from payments.models import AutoPayEnrollment, AutoPaymentLog, Payment
    from payments.services.razorpay_autopay_service import RazorpayAutoPayService

    try:
        enrollment = AutoPayEnrollment.objects.get(id=enrollment_id)

        if enrollment.status not in ['active', 'failed']:
            logger.warning(f"Skipping retry for enrollment {enrollment.enrollment_number} - status is {enrollment.status}")
            return

        gateway_type = enrollment.gateway.gateway_type

        # Select service and customer_id based on gateway type
        if gateway_type != 'razorpay':
            logger.warning(f"Unsupported gateway {gateway_type} for retry on enrollment {enrollment.enrollment_number}")
            return
        service = RazorpayAutoPayService(enrollment.gateway)
        customer_id = enrollment.razorpay_customer_id
        payment_method_label = 'razorpay_card'
        token_id = enrollment.payment_method.gateway_payment_method_id if enrollment.payment_method else None

        # Attempt charge
        result = service.charge_customer_off_session(
            customer_id=customer_id,
            amount=float(enrollment.amount),
            metadata={
                'enrollment_id': str(enrollment.id),
                'enrollment_number': enrollment.enrollment_number,
                'is_retry': 'true',
                'retry_attempt': enrollment.current_retry_count,
                'email': enrollment.user.email,
                'contact': getattr(enrollment.user, 'phone', ''),
            },
            token_id=token_id,
        )

        if result['success']:
            # Create payment record
            payment = Payment.objects.create(
                user=enrollment.user,
                amount=enrollment.amount,
                currency=enrollment.gateway.currency,
                payment_method=payment_method_label,
                gateway=enrollment.gateway,
                gateway_payment_id=result.get('payment_intent_id', result.get('order_id', '')),
                status='completed',
                description=f"Auto-pay retry: {enrollment.enrollment_type}",
                completed_at=timezone.now()
            )

            # --- NEW: Admin Visibility Fix for Retry ---
            try:
                from payments.models import Invoice
                invoice = Invoice.objects.create(
                    user=enrollment.user,
                    invoice_type=enrollment.enrollment_type if enrollment.enrollment_type in dict(Invoice.INVOICE_TYPES) else 'other',
                    building=getattr(enrollment.user, 'building', 'System'),
                    unit_number=getattr(enrollment.user, 'unit_number', 'N/A'),
                    subtotal=enrollment.amount,
                    total_amount=enrollment.amount,
                    amount_paid=enrollment.amount,
                    amount_due=0,
                    issue_date=timezone.now().date(),
                    due_date=timezone.now().date(),
                    status='paid',
                    paid_at=timezone.now(),
                    description=f"Auto-pay Retry: {enrollment.enrollment_type}",
                    notes=f"Generated via Autopay Retry for {enrollment.enrollment_number}"
                )
                payment.invoice = invoice
                payment.save()
            except Exception as inv_err:
                logger.error(f"Failed to generate invoice for autopay retry: {str(inv_err)}")
            # --- END FIX ---

            # Update enrollment
            enrollment.successful_payments += 1
            enrollment.total_payments += 1
            enrollment.total_amount_paid += enrollment.amount
            enrollment.last_payment_date = timezone.now().date()
            enrollment.next_payment_date = enrollment.calculate_next_payment_date()
            enrollment.current_retry_count = 0
            enrollment.status = 'active'
            enrollment.save()

            # Create log
            AutoPaymentLog.objects.create(
                enrollment=enrollment,
                payment=payment,
                scheduled_date=timezone.now().date(),
                attempted_date=timezone.now(),
                completed_date=timezone.now(),
                amount=enrollment.amount,
                status='succeeded',
                attempt_number=enrollment.current_retry_count,
                gateway_response=result
            )

            send_autopay_success_notification.delay(enrollment.id, payment.id)
            logger.info(f"Retry successful for enrollment {enrollment.enrollment_number} via {gateway_type}")

        else:
            # Still failed
            enrollment.current_retry_count += 1
            if enrollment.current_retry_count >= enrollment.max_retry_attempts:
                enrollment.status = 'failed'
            enrollment.save()

            logger.error(f"Retry failed for enrollment {enrollment.enrollment_number}")

    except Exception as exc:
        logger.error('Task %s failed: %s', self.name, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_recurring_invoices(self):
    """
    Generate invoices from recurring invoice templates.
    Run this task daily via Celery Beat at 1 AM.

    OPTIMIZED: Uses bulk_create for invoices (N INSERT -> 1 INSERT) and
    bulk_update for templates (N UPDATE -> 1 UPDATE), reducing DB queries
    from 2N+1 to ~3 total.
    """
    from payments.models import RecurringInvoice, Invoice

    try:
        today = timezone.now().date()

        # OPTIMIZATION: Fetch tenant settings ONCE outside the loop (was: N queries)
        from tenants.models import TenantSettings
        tenant_settings = TenantSettings.objects.first()
        due_days = tenant_settings.payment_due_days if tenant_settings else 5

        # Get all active recurring invoices due today (1 query)
        due_templates = RecurringInvoice.objects.filter(
            status='active',
            next_invoice_date__lte=today
        ).select_related('user')

        logger.info(f"Generating {due_templates.count()} recurring invoices")

        # OPTIMIZATION: Collect objects instead of creating one-by-one
        invoices_to_create = []
        templates_to_update = []
        autopay_pairs = []  # (template, invoice_index) for deferred autopay dispatch

        for template in due_templates:
            try:
                issue_date = today
                due_date = today + timedelta(days=due_days)

                if template.frequency == 'monthly':
                    period_start = today.replace(day=1)
                    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
                    period_end = next_month - timedelta(days=1)
                else:
                    period_start = today
                    period_end = today + timedelta(days=30)

                tax_amount = (template.subtotal * template.tax_percentage) / 100

                # OPTIMIZATION: Build Invoice object in memory, don't hit DB yet
                invoice_obj = Invoice(
                    user=template.user,
                    invoice_type=template.invoice_type,
                    building=template.building,
                    unit_number=template.unit_number,
                    subtotal=template.subtotal,
                    tax_amount=tax_amount,
                    tax_percentage=template.tax_percentage,
                    issue_date=issue_date,
                    due_date=due_date,
                    period_start=period_start,
                    period_end=period_end,
                    line_items=template.line_items_template,
                    description=template.description,
                    status='sent',
                    sent_at=timezone.now()
                )
                invoice_index = len(invoices_to_create)
                invoices_to_create.append(invoice_obj)

                # Update template fields in memory
                template.invoices_generated += 1
                template.last_invoice_date = today
                if template.frequency == 'monthly':
                    template.next_invoice_date = (today.replace(day=template.billing_day) + timedelta(days=32)).replace(day=template.billing_day)
                elif template.frequency == 'quarterly':
                    template.next_invoice_date = today + timedelta(days=90)
                elif template.frequency == 'semi_annual':
                    template.next_invoice_date = today + timedelta(days=180)
                elif template.frequency == 'annual':
                    template.next_invoice_date = today + timedelta(days=365)
                templates_to_update.append(template)

                if template.auto_pay_enabled and template.autopay_enrollment:
                    autopay_pairs.append((template, invoice_index))

            except Exception as e:
                logger.error(f"Error preparing invoice from template {template.id}: {str(e)}")
                continue

        # OPTIMIZATION: 1 bulk INSERT instead of N individual INSERTs
        created_invoices = Invoice.objects.bulk_create(invoices_to_create)
        generated_count = len(created_invoices)
        logger.info(f"bulk_create: inserted {generated_count} invoices in 1 query")

        # OPTIMIZATION: 1 bulk UPDATE instead of N individual saves for templates
        if templates_to_update:
            RecurringInvoice.objects.bulk_update(
                templates_to_update,
                ['invoices_generated', 'last_invoice_date', 'next_invoice_date']
            )
            logger.info(f"bulk_update: updated {len(templates_to_update)} templates in 1 query")

        # Dispatch autopay for invoices that now have real PKs after bulk_create
        for template, invoice_index in autopay_pairs:
            if invoice_index < len(created_invoices):
                created_invoice = created_invoices[invoice_index]
                if created_invoice.pk:
                    process_autopay_invoice.delay(created_invoice.id, template.autopay_enrollment.id)

        return f"Generated {generated_count} recurring invoices"

    except Exception as exc:
        logger.error('Task %s failed: %s', self.name, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_autopay_invoice(self, invoice_id, enrollment_id):
    """Process payment for an invoice using auto-pay via Razorpay"""
    from payments.models import Invoice, AutoPayEnrollment, Payment
    from payments.services.razorpay_autopay_service import RazorpayAutoPayService

    try:
        invoice = Invoice.objects.get(id=invoice_id)
        enrollment = AutoPayEnrollment.objects.get(id=enrollment_id)

        gateway_type = enrollment.gateway.gateway_type
        charge_metadata = {
            'invoice_id': str(invoice.id),
            'invoice_number': invoice.invoice_number,
            'enrollment_id': str(enrollment.id)
        }

        # Select service and customer_id based on gateway type
        if gateway_type != 'razorpay':
            logger.warning(f"Unsupported gateway {gateway_type} for invoice autopay, enrollment {enrollment.enrollment_number}")
            return
        service = RazorpayAutoPayService(enrollment.gateway)
        customer_id = enrollment.razorpay_customer_id
        payment_method_label = 'razorpay_card'
        token_id = enrollment.payment_method.gateway_payment_method_id if enrollment.payment_method else None

        # Charge customer
        result = service.charge_customer_off_session(
            customer_id=customer_id,
            amount=float(invoice.total_amount),
            metadata=charge_metadata,
            token_id=token_id,
        )

        if result['success']:
            # Create payment
            Payment.objects.create(
                user=invoice.user,
                invoice=invoice,
                amount=invoice.total_amount,
                currency=enrollment.gateway.currency,
                payment_method=payment_method_label,
                gateway=enrollment.gateway,
                gateway_payment_id=result.get('payment_intent_id', result.get('order_id', '')),
                status='completed',
                description=f"Auto-pay for invoice {invoice.invoice_number}",
                completed_at=timezone.now()
            )

            logger.info(f"Successfully processed auto-pay for invoice {invoice.invoice_number} via {gateway_type}")
        else:
            logger.error(f"Failed to process auto-pay for invoice {invoice.invoice_number}: {result.get('error')}")

    except Exception as exc:
        logger.error('Task %s failed: %s', self.name, exc)
        raise self.retry(exc=exc)


# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATION TASKS
# ═══════════════════════════════════════════════════════════════════════════

@shared_task
def send_autopay_reminder_notifications():
    """Send reminders before auto-pay is processed"""
    from payments.models import AutoPayEnrollment
    
    today = timezone.now().date()
    
    # Get enrollments with payments coming up in the next 7 days
    upcoming_enrollments = AutoPayEnrollment.objects.filter(
        status='active',
        next_payment_date__gt=today,
        next_payment_date__lte=today + timedelta(days=7)
    ).select_related('user')
    
    sent_count = 0
    
    for enrollment in upcoming_enrollments:
        days_until = (enrollment.next_payment_date - today).days
        
        if days_until == enrollment.notify_before_days:
            try:
                NotificationService.send(
                    user=enrollment.user,
                    title='Auto-Pay Scheduled',
                    message=f'Your auto-pay of ₹{enrollment.amount} for {enrollment.enrollment_type} will be processed on {enrollment.next_payment_date}',
                    notification_type='payment',
                    priority='medium',
                    send_email=True,
                    send_push=True
                )
                sent_count += 1
                logger.info(f"Sent reminder for enrollment {enrollment.enrollment_number}")
            except Exception as e:
                logger.error(f"Error sending reminder for enrollment {enrollment.id}: {str(e)}")
    
    return f"Sent {sent_count} auto-pay reminders"


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_autopay_success_notification(self, enrollment_id, payment_id):
    """Send success notification after auto-pay"""
    from payments.models import AutoPayEnrollment, Payment

    try:
        enrollment = AutoPayEnrollment.objects.get(id=enrollment_id)
        payment = Payment.objects.get(id=payment_id)

        if enrollment.send_payment_confirmation:
            NotificationService.send(
                user=enrollment.user,
                title='Auto-Pay Successful',
                message=f'Your auto-pay of ₹{payment.amount} was processed successfully. Payment ID: {payment.payment_number}',
                notification_type='payment',
                priority='low',
                send_email=True,
                send_push=True
            )
    except Exception as exc:
        logger.error('Task %s failed: %s', self.name, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_autopay_failure_notification(self, enrollment_id, log_id):
    """Send failure notification after auto-pay fails"""
    from payments.models import AutoPayEnrollment, AutoPaymentLog

    try:
        enrollment = AutoPayEnrollment.objects.get(id=enrollment_id)
        log = AutoPaymentLog.objects.get(id=log_id)

        if enrollment.send_failure_notification:
            NotificationService.send(
                user=enrollment.user,
                title='Auto-Pay Failed',
                message=f'Your auto-pay of ₹{log.amount} failed. Reason: {log.error_message}. Please update your payment method.',
                notification_type='payment',
                priority='high',
                send_email=True,
                send_sms=True,
                send_push=True
            )
    except Exception as exc:
        logger.error('Task %s failed: %s', self.name, exc)
        raise self.retry(exc=exc)


@shared_task
def send_payment_reminders():
    """Send payment reminders for upcoming due dates"""
    from payments.models import Invoice
    
    today = timezone.now().date()
    reminder_date = today + timedelta(days=3)  # 3 days before due
    
    # Get invoices due in 3 days
    upcoming_invoices = Invoice.objects.filter(
        due_date=reminder_date,
        status__in=['sent', 'viewed', 'partially_paid']
    ).select_related('user')
    
    sent_count = 0
    
    for invoice in upcoming_invoices:
        try:
            NotificationService.send(
                user=invoice.user,
                title='Payment Reminder',
                message=f'Your payment of ₹{invoice.amount_due} for invoice {invoice.invoice_number} is due on {invoice.due_date}',
                notification_type='payment',
                priority='medium',
                send_email=True,
                send_push=True
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Error sending payment reminder for invoice {invoice.id}: {str(e)}")
    
    return f"Sent {sent_count} payment reminders"


# ═══════════════════════════════════════════════════════════════════════════
# INVOICE MANAGEMENT TASKS
# ═══════════════════════════════════════════════════════════════════════════

@shared_task
def check_overdue_invoices():
    """Mark invoices as overdue, apply late fees if 10 days overdue, and send notifications.

    OPTIMIZED:
    - Status change (sent->overdue): uses a single queryset.update() call instead of N saves.
    - Late fee logic: still per-invoice (requires individual save) since it recalculates totals.
    - TenantSettings fetched ONCE outside the loop (was: N queries, one per invoice).
    """
    from payments.models import Invoice

    today = timezone.now().date()

    # OPTIMIZATION: Fetch tenant settings ONCE outside the loop (was: N queries)
    from tenants.models import TenantSettings
    tenant_settings = TenantSettings.objects.first()

    # Find invoices that are now overdue or already overdue (1 query)
    overdue_invoices = Invoice.objects.filter(
        due_date__lt=today,
        status__in=['sent', 'viewed', 'partially_paid', 'overdue']
    ).select_related('user')

    # ─── OPTIMIZATION: Bulk status update ───────────────────────────────────────
    # BEFORE: for invoice in overdue_invoices: invoice.status='overdue'; invoice.save()  -> N UPDATE queries
    # AFTER:  single queryset.update() -> 1 UPDATE query
    newly_overdue_qs = overdue_invoices.filter(status__in=['sent', 'viewed', 'partially_paid'])
    newly_overdue_ids = list(newly_overdue_qs.values_list('id', flat=True))
    updated_count = newly_overdue_qs.update(status='overdue')
    logger.info(f"bulk queryset.update(): marked {updated_count} invoices as overdue in 1 query")

    # Re-fetch the updated invoices for notification (select_related to avoid N+1)
    newly_overdue_invoices = Invoice.objects.filter(id__in=newly_overdue_ids).select_related('user')
    for invoice in newly_overdue_invoices:
        try:
            NotificationService.send(
                user=invoice.user,
                title='Invoice Overdue',
                message=f'Your invoice {invoice.invoice_number} for ₹{invoice.amount_due} is now overdue. Please make payment as soon as possible.',
                notification_type='payment',
                priority='high',
                send_email=True,
                send_sms=True,
                send_push=True,
            )
        except Exception as e:
            logger.error(f"Error sending overdue notification: {str(e)}")
    # ────────────────────────────────────────────────────────────────────────────

    late_fee_count = 0

    # Late fee logic: must remain per-invoice because save() triggers total recalculation
    if tenant_settings and tenant_settings.late_fee_enabled:
        all_overdue = Invoice.objects.filter(
            due_date__lt=today,
            status='overdue'
        ).select_related('user')

        for invoice in all_overdue:
            try:
                days_late = (today - invoice.due_date).days
                if days_late > tenant_settings.grace_period_days:
                    if tenant_settings.late_fee_type == 'percentage':
                        daily_fee = (invoice.subtotal * tenant_settings.late_fee_percentage) / Decimal('100.00')
                    else:
                        daily_fee = tenant_settings.late_fee_amount

                    expected_total_late_fee = daily_fee * days_late

                    if invoice.late_fee < expected_total_late_fee:
                        is_first_time = (invoice.late_fee == Decimal('0.00'))
                        invoice.late_fee = expected_total_late_fee

                        if not isinstance(invoice.line_items, list):
                            invoice.line_items = []

                        late_fee_item_found = False
                        for item in invoice.line_items:
                            if item.get('type') == 'late_fee':
                                item['amount'] = float(expected_total_late_fee)
                                item['unit_price'] = float(expected_total_late_fee)
                                item['description'] = f'Late Fee ({days_late} days past due)'
                                late_fee_item_found = True
                                break

                        if not late_fee_item_found:
                            invoice.line_items.append({
                                'description': f'Late Fee ({days_late} days past due)',
                                'quantity': 1,
                                'unit_price': float(expected_total_late_fee),
                                'amount': float(expected_total_late_fee),
                                'type': 'late_fee'
                            })

                        # save() triggers recalculation of totals and platform fee automatically
                        invoice.save()
                        late_fee_count += 1
                        logger.info(f"Updated late fee to ${expected_total_late_fee} for invoice {invoice.invoice_number}")

                        if is_first_time:
                            try:
                                NotificationService.send(
                                    user=invoice.user,
                                    title='Late Fee Applied',
                                    message=f'A late fee has started applying to your invoice {invoice.invoice_number} as it is past the grace period.',
                                    notification_type='payment',
                                    priority='high',
                                    send_email=True,
                                    send_sms=True,
                                    send_push=True,
                                )
                            except Exception as e:
                                logger.error(f"Error sending late fee notification: {str(e)}")
            except Exception as fee_err:
                logger.error(f"Error calculating late fee for invoice {invoice.id}: {str(fee_err)}")

    return f"Marked {updated_count} invoices as overdue and applied/updated late fees to {late_fee_count} invoices"


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP & MAINTENANCE TASKS
# ═══════════════════════════════════════════════════════════════════════════

@shared_task
def cleanup_failed_payments():
    """Archive old failed payment attempts"""
    from payments.models import Payment
    
    # Archive payments failed more than 90 days ago
    cutoff_date = timezone.now() - timedelta(days=90)
    
    failed_payments = Payment.objects.filter(
        status='failed',
        failed_at__lt=cutoff_date
    )
    
    count = failed_payments.count()
    
    # You could archive to a separate table or just log
    logger.info(f"Found {count} old failed payments to clean up")
    
    # Optional: Delete or archive
    # failed_payments.delete()
    
    return f"Cleaned up {count} old failed payments"

@shared_task
def cleanup_draft_payments():
    """Cancel or delete draft Stripe payments older than 24 hours"""
    from payments.models import Payment
    
    # 24 hours ago
    cutoff_date = timezone.now() - timedelta(hours=24)
    
    draft_payments = Payment.objects.filter(
        status__in=['draft', 'pending'],
        created_at__lt=cutoff_date
    )
    
    count = draft_payments.count()
    if count > 0:
        logger.info(f"Found {count} old draft payments to clean up")
        # We can either mark them cancelled or delete them. We will mark them cancelled.
        draft_payments.update(status='cancelled', description='Cancelled due to 24h timeout')
        
    return f"Cleaned up {count} old draft payments"


@shared_task
def update_subscription_statuses():
    """Update auto-pay subscription statuses.

    OPTIMIZED: Uses queryset.update() instead of a loop with individual .save() calls.
    BEFORE: N UPDATE queries (one per enrollment)
    AFTER:  1 UPDATE query (entire queryset at once)
    """
    from payments.models import AutoPayEnrollment

    # OPTIMIZATION: Single queryset.update() replaces N individual .save() calls
    updated_count = AutoPayEnrollment.objects.filter(
        status='active',
        current_retry_count__gte=3
    ).update(status='failed')

    logger.info(f"queryset.update(): marked {updated_count} enrollments as failed in 1 query")
    return f"Updated {updated_count} subscription statuses"


# ═══════════════════════════════════════════════════════════════════════════
# REPORTING TASKS
# ═══════════════════════════════════════════════════════════════════════════

@shared_task
def generate_daily_payment_report():
    """Generate daily payment statistics report"""
    from payments.models import Payment, Invoice
    
    today = timezone.now().date()
    
    # Calculate stats
    daily_payments = Payment.objects.filter(
        completed_at__date=today,
        status='completed'
    )
    
    stats = {
        'date': today.isoformat(),
        'total_payments': daily_payments.count(),
        'total_amount': float(daily_payments.aggregate(Sum('amount'))['amount__sum'] or 0),
        'invoices_paid': Invoice.objects.filter(paid_at__date=today).count(),
        'autopay_payments': daily_payments.filter(description__icontains='auto-pay').count(),
    }
    
    logger.info(f"Daily payment report: {stats}")
    
    # You could save this to a Report model or send via email
    return stats


@shared_task
def generate_monthly_revenue_report():
    """Generate monthly revenue report"""
    from payments.models import Payment
    
    # Get last month's date range
    today = timezone.now().date()
    first_of_month = today.replace(day=1)
    last_month = (first_of_month - timedelta(days=1)).replace(day=1)
    
    monthly_payments = Payment.objects.filter(
        completed_at__date__gte=last_month,
        completed_at__date__lt=first_of_month,
        status='completed'
    )
    
    stats = {
        'month': last_month.strftime('%Y-%m'),
        'total_revenue': float(monthly_payments.aggregate(Sum('amount'))['amount__sum'] or 0),
        'total_transactions': monthly_payments.count(),
        'average_transaction': float(monthly_payments.aggregate(Sum('amount'))['amount__sum'] or 0) / (monthly_payments.count() or 1),
    }
    
    logger.info(f"Monthly revenue report: {stats}")
    
    return stats


# ═══════════════════════════════════════════════════════════════════════════
# UTILITY TASKS
# ═══════════════════════════════════════════════════════════════════════════

@shared_task(name='payments.tasks.sync_payments_to_accounting')
def sync_payments_to_accounting():
    """
    Simulate syncing successful payments to an external accounting system (e.g., Tally, Zoho).
    In a real scenario, this would call an external API.
    For now, it logs the sync event in analytics.
    """
    from payments.models import Payment
    from analytics.models import AnalyticsEvent
    from django.db import connection
    
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    
    payments_to_sync = Payment.objects.filter(
        status='completed',
        completed_at__date=yesterday,
        metadata__accounting_synced__isnull=True
    )
    
    count = payments_to_sync.count()
    total_amount = float(payments_to_sync.aggregate(Sum('amount'))['amount__sum'] or 0)
    
    if count > 0:
        # OPTIMIZATION: Build updated objects in memory, then bulk_update in 1 query
        # BEFORE: N UPDATE queries (one per payment in loop)
        # AFTER:  1 UPDATE query via bulk_update
        synced_at = timezone.now().isoformat()
        payments_list = list(payments_to_sync)
        for payment in payments_list:
            if not isinstance(payment.metadata, dict):
                payment.metadata = {}
            payment.metadata['accounting_synced'] = True
            payment.metadata['synced_at'] = synced_at

        from payments.models import Payment as PaymentModel
        PaymentModel.objects.bulk_update(payments_list, ['metadata'])
        logger.info(f"bulk_update: synced metadata for {count} payments in 1 query")

        AnalyticsEvent.objects.create(
            event_type='accounting_sync_completed',
            tenant_schema=connection.schema_name,
            metadata={
                'payment_count': count,
                'total_amount': total_amount,
                'sync_date': yesterday.isoformat()
            }
        )

        logger.info(f"Synced {count} payments (₹{total_amount}) to accounting system")
    
    return f"Synced {count} payments to accounting"


@shared_task
def test_celery():
    """Test task to verify Celery is working"""
    logger.info("Celery test task executed successfully!")
    return "Celery is working!"