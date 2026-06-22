# properties/signals.py
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import Lease, Unit, Building, Township, Block
from notifications.services import NotificationService
from django.contrib.auth import get_user_model
User = get_user_model()
import logging

logger = logging.getLogger(__name__)

def add_months(sourcedate, months=1):
    import calendar
    import datetime
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)

@receiver(post_save, sender=Lease)
def update_unit_status_on_lease_save(sender, instance, created, **kwargs):
    """
    Update unit status when lease is created or updated
    """
    if instance.status == 'active':
        # Set unit as occupied and assign tenant
        instance.unit.status = 'occupied'
        instance.unit.is_occupied = True
        instance.unit.unit_type = 'tenant_occupied'
        instance.unit.current_resident = instance.tenant.get_full_name() or instance.tenant.email
        instance.unit.save()

        # Sync unit details to tenant user profile
        tenant = instance.tenant
        building_name = instance.unit.building.name if instance.unit.building else ''
        if tenant.unit_number != instance.unit.unit_number or tenant.building_name != building_name:
            tenant.unit_number = instance.unit.unit_number
            tenant.building_name = building_name
            tenant.save(update_fields=['unit_number', 'building_name'])
        
        if created:
            logger.info(f"New lease created: {instance.unit} assigned to {instance.tenant.get_full_name()}")
            
        # Auto-invoice and Recurring Template Setup for Tenant
        from payments.models import Invoice, RecurringInvoice
        from decimal import Decimal
        
        # Check if we already have an active recurring template for this tenant and unit to avoid duplicate billing
        existing_template = RecurringInvoice.objects.filter(
            user=instance.tenant,
            invoice_type='rent',
            building=building_name,
            unit_number=instance.unit.unit_number,
            status='active'
        ).exists()
        
        if not existing_template:
            try:
                # Cancel any existing active templates for this unit
                RecurringInvoice.objects.filter(
                    building=building_name,
                    unit_number=instance.unit.unit_number,
                    status='active'
                ).update(status='cancelled')
                
                # Create initial invoice
                from tenants.models import TenantSettings
                settings = TenantSettings.objects.first()
                tax_percentage = settings.tax_percentage if settings else Decimal('0.00')
                tax_amount = (instance.monthly_rent * tax_percentage) / Decimal('100.00')
                
                Invoice.objects.create(
                    user=instance.tenant,
                    invoice_type='rent',
                    building=building_name,
                    unit_number=instance.unit.unit_number,
                    subtotal=instance.monthly_rent,
                    tax_amount=tax_amount,
                    tax_percentage=tax_percentage,
                    issue_date=instance.start_date,
                    due_date=instance.start_date + timezone.timedelta(days=5),
                    period_start=instance.start_date,
                    period_end=add_months(instance.start_date, 1) - timezone.timedelta(days=1),
                    line_items=[{
                        'description': 'Monthly Rent Charge',
                        'quantity': 1,
                        'unit_price': float(instance.monthly_rent),
                        'amount': float(instance.monthly_rent),
                        'type': 'rent'
                    }],
                    description=f"Initial Rent Invoice for Unit {instance.unit.unit_number}",
                    status='sent',
                    sent_at=timezone.now(),
                    created_by=instance.created_by
                )
                
                # Create recurring invoice template
                RecurringInvoice.objects.create(
                    user=instance.tenant,
                    invoice_type='rent',
                    description=f"Monthly Rent for Unit {instance.unit.unit_number}",
                    building=building_name,
                    unit_number=instance.unit.unit_number,
                    subtotal=instance.monthly_rent,
                    tax_percentage=tax_percentage,
                    frequency='monthly',
                    start_date=instance.start_date,
                    billing_day=instance.start_date.day,
                    next_invoice_date=add_months(instance.start_date, 1),
                    line_items_template=[{
                        'description': 'Monthly Rent Charge',
                        'quantity': 1,
                        'unit_price': float(instance.monthly_rent),
                        'amount': float(instance.monthly_rent),
                        'type': 'rent'
                    }],
                    status='active',
                    created_by=instance.created_by
                )
                logger.info(f"Auto-billing initialized for active lease of unit {instance.unit}")
            except Exception as e:
                logger.error(f"Failed to initialize auto-billing on lease activation: {e}")
    
    elif instance.status in ['terminated', 'expired']:
        # Check if there are other active leases for this unit
        other_active_leases = Lease.objects.filter(
            unit=instance.unit,
            status='active'
        ).exclude(id=instance.id)

        # Clear unit details on tenant user profile if they still point to this unit
        tenant = instance.tenant
        building_name = instance.unit.building.name if instance.unit.building else ''
        if tenant.unit_number == instance.unit.unit_number and tenant.building_name == building_name:
            tenant.unit_number = ''
            tenant.building_name = ''
            tenant.save(update_fields=['unit_number', 'building_name'])
        
        if not other_active_leases.exists():
            # No other active leases, make unit available
            instance.unit.status = 'available'
            instance.unit.is_occupied = False
            instance.unit.current_resident = None
            instance.unit.save()
            
            logger.info(f"Lease ended: {instance.unit} is now available")

@receiver(pre_save, sender=Lease)
def validate_lease_dates(sender, instance, **kwargs):
    """
    Validate lease dates before saving
    """
    if instance.end_date and instance.start_date:
        if instance.end_date <= instance.start_date:
            raise ValueError("Lease end date must be after start date")
    
    # Auto-expire leases that have passed end date
    if instance.status == 'active' and instance.end_date:
        if instance.end_date < timezone.now().date():
            instance.status = 'expired'
            logger.info(f"Lease auto-expired: {instance.unit} - {instance.tenant.get_full_name()}")

@receiver(post_save, sender=Unit)
def log_unit_status_changes(sender, instance, created, **kwargs):
    """
    Log unit status changes
    """
    if created:
        logger.info(f"New unit created: {instance.building.name} - {instance.unit_number}")
    else:
        # Check if status changed (would need to track previous state for full implementation)
        logger.debug(f"Unit updated: {instance.building.name} - {instance.unit_number} ({instance.status})")


@receiver(post_delete, sender=Building)
def orphan_residents_on_building_delete(sender, instance, **kwargs):
    """
    When a Building is deleted, all its Blocks / Floors / Units / Leases are
    cascade-deleted automatically by the DB.  However, the resident User accounts
    store building_name and unit_number as plain CharFields (no FK), so they
    become stale.  This signal clears those fields so no orphan data remains.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    affected = User.objects.filter(building_name__iexact=instance.name)
    count = affected.count()

    if count:
        affected.update(building_name='', unit_number='')
        logger.info(
            f"[Building Deleted] '{instance.name}' — "
            f"cleared building_name & unit_number on {count} resident(s)."
        )
    else:
        logger.info(f"[Building Deleted] '{instance.name}' — no resident accounts needed updating.")


# --- Society Setup Triggers ---

@receiver(post_save, sender=Township)
def notify_new_township(sender, instance, created, **kwargs):
    """Notify Master Admin when a new Colony (Township) is created."""
    if created:
        admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
        for admin_user in admins:
            NotificationService.send(
                user=admin_user,
                title="New Colony Created!",
                message=f"A new colony '{instance.name}' has been successfully created in {instance.city}.",
                notification_type='system',
                priority='medium',
                send_email=True
            )

@receiver(post_delete, sender=Township)
def notify_deleted_township(sender, instance, **kwargs):
    """Notify Master Admin when a Colony (Township) is deleted."""
    admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
    for admin_user in admins:
        NotificationService.send(
            user=admin_user,
            title="Colony Deleted",
            message=f"The colony '{instance.name}' has been successfully deleted.",
            notification_type='system',
            priority='high',
            send_email=True
        )

@receiver(post_save, sender=Block)
def notify_new_block(sender, instance, created, **kwargs):
    """Notify Master Admin when a new Block is added."""
    if created:
        admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
        for admin_user in admins:
            NotificationService.send(
                user=admin_user,
                title="New Block Added",
                message=f"New block '{instance.name}' has been added to {instance.building.name}.",
                notification_type='system',
                priority='low',
                send_email=True
            )

@receiver(post_save, sender=Unit)
def notify_new_unit(sender, instance, created, **kwargs):
    """Notify Master Admin when a new Unit is added."""
    if created:
        admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
        for admin_user in admins:
            NotificationService.send(
                user=admin_user,
                title="New Unit Added",
                message=f"Unit {instance.unit_number} in {instance.building.name} has been added to the system.",
                notification_type='system',
                priority='low',
                send_email=True
            )

@receiver(post_save, sender=Unit)
def handle_owner_occupancy_on_unit_save(sender, instance, created, **kwargs):
    """
    Auto-invoice and setup recurring billing when a unit becomes owner occupied
    """
    if instance.unit_type == 'owner_occupied' and instance.owner_user:
        from payments.models import Invoice, RecurringInvoice
        from decimal import Decimal
        
        # Check if we already have an active recurring template for this owner and unit
        existing_template = RecurringInvoice.objects.filter(
            user=instance.owner_user,
            invoice_type='maintenance_fee',
            building=instance.building.name,
            unit_number=instance.unit_number,
            status='active'
        ).exists()
        
        if not existing_template:
            try:
                # Cancel any existing active templates for this unit
                RecurringInvoice.objects.filter(
                    building=instance.building.name,
                    unit_number=instance.unit_number,
                    status='active'
                ).update(status='cancelled')
                
                subtotal = instance.monthly_maintenance or instance.association_dues or Decimal('100.00')
                from tenants.models import TenantSettings
                settings = TenantSettings.objects.first()
                tax_percentage = settings.tax_percentage if settings else Decimal('0.00')
                tax_amount = (subtotal * tax_percentage) / Decimal('100.00')
                
                today = timezone.now().date()
                
                # Create initial invoice
                Invoice.objects.create(
                    user=instance.owner_user,
                    invoice_type='maintenance_fee',
                    building=instance.building.name,
                    unit_number=instance.unit_number,
                    subtotal=subtotal,
                    tax_amount=tax_amount,
                    tax_percentage=tax_percentage,
                    issue_date=today,
                    due_date=today + timezone.timedelta(days=5),
                    period_start=today,
                    period_end=add_months(today, 1) - timezone.timedelta(days=1),
                    line_items=[{
                        'description': 'Monthly Maintenance Charge',
                        'quantity': 1,
                        'unit_price': float(subtotal),
                        'amount': float(subtotal),
                        'type': 'maintenance_fee'
                    }],
                    description=f"Initial Maintenance Invoice for Unit {instance.unit_number}",
                    status='sent',
                    sent_at=timezone.now()
                )
                
                # Create recurring invoice template
                RecurringInvoice.objects.create(
                    user=instance.owner_user,
                    invoice_type='maintenance_fee',
                    description=f"Monthly Maintenance for Unit {instance.unit_number}",
                    building=instance.building.name,
                    unit_number=instance.unit_number,
                    subtotal=subtotal,
                    tax_percentage=tax_percentage,
                    frequency='monthly',
                    start_date=today,
                    billing_day=today.day,
                    next_invoice_date=add_months(today, 1),
                    line_items_template=[{
                        'description': 'Monthly Maintenance Charge',
                        'quantity': 1,
                        'unit_price': float(subtotal),
                        'amount': float(subtotal),
                        'type': 'maintenance_fee'
                    }],
                    status='active'
                )
                logger.info(f"Auto-billing initialized for owner occupied unit {instance}")
            except Exception as e:
                logger.error(f"Failed to initialize owner auto-billing on unit save: {e}")