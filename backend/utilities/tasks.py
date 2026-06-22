# utilities/tasks.py
from celery import shared_task
from django.utils import timezone
from django.db import connection
from datetime import timedelta
import logging
from .models import UtilityType, UtilityBill, UtilityMeterReading
from properties.models import Unit

logger = logging.getLogger(__name__)

@shared_task(name='utilities.tasks.run_utility_billing_for_all_tenants')
def run_utility_billing_for_all_tenants():
    """
    Master task to trigger utility billing for all organizations (tenants).
    """
    from tenants.models import Client
    tenants = Client.objects.exclude(schema_name='public')
    
    for tenant in tenants:
        try:
            generate_monthly_utility_bills.delay(schema_name=tenant.schema_name)
        except Exception as e:
            logger.error(f"Error triggering utility billing for tenant {tenant.schema_name}: {e}")

@shared_task(bind=True)
def generate_monthly_utility_bills(self, schema_name=None):
    """
    Automatically generate utility bills for all occupied units.
    """
    if schema_name:
        connection.set_schema(schema_name)
        
    today = timezone.now().date()
    # Billing for previous month
    first_of_this_month = today.replace(day=1)
    last_of_prev_month = first_of_this_month - timedelta(days=1)
    first_of_prev_month = last_of_prev_month.replace(day=1)
    
    # Due date: 5th of current month
    due_date = first_of_this_month.replace(day=5)
    
    active_utilities = UtilityType.objects.filter(is_active=True)
    occupied_units = Unit.objects.filter(status='occupied')
    
    generated_count = 0
    
    for utility_type in active_utilities:
        for unit in occupied_units:
            active_lease = unit.leases.filter(status='active').first()
            if not active_lease:
                continue
                
            # Check if bill already exists
            existing = UtilityBill.objects.filter(
                utility_type=utility_type,
                unit=unit,
                billing_period_start=first_of_prev_month,
                billing_period_end=last_of_prev_month
            ).exists()
            
            if existing:
                continue
                
            try:
                # Get latest reading
                latest_reading = UtilityMeterReading.objects.filter(
                    utility_type=utility_type,
                    unit=unit
                ).order_by('-reading_date').first()
                
                current_reading = latest_reading.reading_value if latest_reading else 0
                
                # Get previous reading from last bill
                previous_bill = UtilityBill.objects.filter(
                    utility_type=utility_type,
                    unit=unit
                ).order_by('-billing_period_end').first()
                
                previous_reading = previous_bill.current_reading if previous_bill else 0
                
                # Create the bill
                bill = UtilityBill.objects.create(
                    utility_type=utility_type,
                    unit=unit,
                    tenant=active_lease.tenant,
                    billing_period_start=first_of_prev_month,
                    billing_period_end=last_of_prev_month,
                    previous_reading=previous_reading,
                    current_reading=current_reading,
                    rate_per_unit=utility_type.base_rate,
                    due_date=due_date,
                    status='pending'
                )
                
                # Also generate an Invoice in the Payments app
                from payments.models import Invoice
                Invoice.objects.create(
                    user=active_lease.tenant,
                    invoice_type='utility',
                    building=unit.building.name,
                    unit_number=unit.unit_number,
                    subtotal=bill.total_amount,
                    total_amount=bill.total_amount,
                    amount_due=bill.total_amount,
                    issue_date=today,
                    due_date=due_date,
                    status='sent',
                    description=f"{utility_type.name} bill for {first_of_prev_month.strftime('%B %Y')}",
                    notes=f"Linked to Utility Bill: {bill.bill_number}"
                )
                
                generated_count += 1
            except Exception as e:
                logger.error(f"Failed to generate {utility_type.name} bill for unit {unit.unit_number}: {e}")
                
    return f"Generated {generated_count} utility bills for schema {schema_name}"
