from django.core.management.base import BaseCommand
from tenants.models import Client, PlatformInvoice
from decimal import Decimal
from django.utils import timezone

class Command(BaseCommand):
    help = 'Generate missing invoices for all existing organizations'

    def handle(self, *args, **options):
        tenants = Client.objects.exclude(schema_name='public')
        self.stdout.write(f"Checking {tenants.count()} organizations...")
        
        created_count = 0
        for tenant in tenants:
            # Check if invoice already exists
            if not PlatformInvoice.objects.filter(tenant=tenant).exists():
                self.stdout.write(f"Generating invoice for {tenant.name}...")
                
                PlatformInvoice.objects.create(
                    tenant=tenant,
                    amount=Decimal("999.00"),
                    plan_name=tenant.subscription_plan or 'basic',
                    status='pending',
                    billing_email=tenant.contact_email or "billing@hoaconnecthub.com",
                    due_date=timezone.now().date() + timezone.timedelta(days=7),
                    remarks=f'Auto-generated missing invoice for {tenant.name}'
                )
                created_count += 1
        
        self.stdout.write(self.style.SUCCESS(f"Successfully created {created_count} missing invoices."))
