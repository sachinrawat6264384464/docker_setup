# properties/tasks.py
from celery import shared_task
from django.utils import timezone
from django.db import connection
from datetime import timedelta
import logging
from .models import Lease
from notifications.services import NotificationService

logger = logging.getLogger(__name__)

@shared_task(name='properties.tasks.run_lease_checks_for_all_tenants')
def run_lease_checks_for_all_tenants():
    """
    Master task to run lease checks for all organizations.
    """
    from tenants.models import Client
    tenants = Client.objects.exclude(schema_name='public')
    
    for tenant in tenants:
        try:
            check_lease_expiries.delay(schema_name=tenant.schema_name)
        except Exception as e:
            logger.error(f"Error triggering lease checks for tenant {tenant.schema_name}: {e}")

@shared_task(bind=True)
def check_lease_expiries(self, schema_name=None):
    """
    Check for leases expiring in 30 and 60 days and notify relevant parties.
    """
    if schema_name:
        connection.set_schema(schema_name)
        
    today = timezone.now().date()
    
    # Check for 30 and 60 day expiries
    for days in [30, 60]:
        expiry_date = today + timedelta(days=days)
        expiring_leases = Lease.objects.filter(
            status='active',
            end_date=expiry_date
        ).select_related('tenant', 'unit', 'unit__building')
        
        for lease in expiring_leases:
            try:
                # Notify Tenant
                NotificationService.send(
                    user=lease.tenant,
                    title='Lease Expiring Soon',
                    message=f'Your lease for unit {lease.unit.unit_number} in {lease.unit.building.name} will expire in {days} days on {lease.end_date}.',
                    notification_type='system',
                    priority='high',
                    send_email=True,
                    send_push=True
                )
                
                # Notify Admin/Manager if assigned
                if lease.unit.building.managed_by:
                    NotificationService.send(
                        user=lease.unit.building.managed_by,
                        title='Lease Expiry Alert',
                        message=f'Lease for tenant {lease.tenant.get_full_name()} (Unit {lease.unit.unit_number}) expires in {days} days.',
                        notification_type='system',
                        priority='medium',
                        send_email=True
                    )
                    
                logger.info(f"Sent {days}-day expiry alert for lease {lease.id}")
            except Exception as e:
                logger.error(f"Error sending lease expiry notification: {e}")
                
    return f"Processed lease checks for schema {schema_name}"
