from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
import logging

from maintenance.models import MaintenanceRequest
from payments.models import Invoice
from tenants.models import TenantSettings
from accounts.email_service import EmailService

logger = logging.getLogger(__name__)

@receiver(post_save, sender=MaintenanceRequest)
def auto_generate_maintenance_invoice(sender, instance, created, **kwargs):
    """
    Auto-generates an invoice when a personal maintenance request is marked as 'completed'.
    """
    if instance.status != 'completed' or instance.request_type != 'personal' or instance.invoiced:
        return

    # To avoid N+1 and duplicate generation, check if invoice already exists for this fingerprint
    fingerprint_note = f"Req #{instance.request_number}"
    
    # Check if this note already exists for this user in the current month
    current_month = timezone.now().month
    current_year = timezone.now().year
    
    exists = Invoice.objects.filter(
        invoice_type='maintenance_fee',
        notes__icontains=fingerprint_note,
        user=instance.requested_by
    ).exists()

    if exists:
        return

    target_user = instance.requested_by
    if not target_user:
        return
        
    try:
        # Get due days from tenant settings
        settings = TenantSettings.objects.first()
        due_days = settings.payment_due_days if settings else 5
        
        issue_date = timezone.now().date()
        due_date = issue_date + timedelta(days=due_days)
        
        # Calculate cost
        cost = instance.total_cost if getattr(instance, 'total_cost', 0) > 0 else 500
        
        # Generate Invoice Number logic identical to backend
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m')
        inv_prefix = f'INV-{date_str}-'
        last_invoice = Invoice.objects.filter(
            invoice_number__startswith=inv_prefix
        ).order_by('-invoice_number').values_list('invoice_number', flat=True).first()
        
        if last_invoice:
            try:
                invoice_counter = int(last_invoice.split('-')[-1]) + 1
            except (ValueError, IndexError):
                invoice_counter = Invoice.objects.filter(invoice_number__startswith=inv_prefix).count() + 1
        else:
            invoice_counter = 1
            
        inv_expires_at = timezone.now() + timedelta(hours=124)
        
        # Create invoice
        invoice = Invoice.objects.create(
            invoice_number=f'{inv_prefix}{invoice_counter:05d}',
            user=target_user,
            invoice_type='maintenance_fee',
            building=instance.building or "",
            unit_number=instance.unit_number or "",
            maintenance_request=instance,
            subtotal=cost,
            total_amount=cost,
            amount_due=cost,
            issue_date=issue_date,
            due_date=due_date,
            billing_month=current_month,
            billing_year=current_year,
            description=f"Maintenance Charge: {instance.title}",
            notes=fingerprint_note,
            created_by=None,  # System generated
            status='sent',
            expires_at=inv_expires_at
        )
        
        # Update MaintenanceRequest cleanly without triggering infinite signals
        MaintenanceRequest.objects.filter(pk=instance.pk).update(invoiced=True)
        
        # Send Email Notification
        try:
            EmailService.send_email(
                to_email=target_user.email,
                subject=f"New Invoice Generated for Maintenance Request #{instance.request_number}",
                template_name='invoice_sent',
                context={
                    'user': target_user,
                    'invoice': invoice,
                    'invoice_number': invoice.invoice_number,
                    'amount_due': invoice.amount_due,
                    'due_date': invoice.due_date,
                }
            )
        except Exception as e:
            logger.warning(f"Could not send email for auto-generated maintenance invoice {invoice.invoice_number}: {e}")
            
    except Exception as e:
        logger.error(f"Error auto-generating maintenance invoice for {instance.request_number}: {e}")
