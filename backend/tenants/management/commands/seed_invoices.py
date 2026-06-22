from django.core.management.base import BaseCommand
from django.utils import timezone
from tenants.models import PlatformInvoice, Client
import random
from decimal import Decimal

class Command(BaseCommand):
    help = 'Seeds Platform Invoices for testing'

    def handle(self, *args, **options):
        tenants = Client.objects.exclude(schema_name='public')
        if not tenants.exists():
            self.stdout.write(self.style.WARNING("No tenants found to create invoices for."))
            return

        statuses = ['pending', 'sent', 'awaiting_payment', 'paid', 'verified', 'expired']
        plans = [
            {'name': 'Basic', 'price': 2499},
            {'name': 'Premium', 'price': 5999},
            {'name': 'Enterprise', 'price': 14999}
        ]
        
        count = 0
        for tenant in tenants:
            plan = random.choice(plans)
            status = random.choice(statuses)
            
            # Create a mock invoice if one doesn't exist for this tenant recently
            invoice, created = PlatformInvoice.objects.get_or_create(
                tenant=tenant,
                status=status,
                defaults={
                    'invoice_number': f'HOA-2026-{random.randint(1000, 9999)}',
                    'plan_name': plan['name'],
                    'amount': Decimal(plan['price']),
                    'due_date': timezone.now() + timezone.timedelta(hours=random.randint(1, 48)),
                    'created_at': timezone.now() - timezone.timedelta(days=random.randint(0, 5))
                }
            )
            
            if created:
                count += 1
                self.stdout.write(self.style.SUCCESS(f"Created Invoice {invoice.invoice_number} for {tenant.name} -> {status}"))
            else:
                invoice.status = status
                invoice.save()
                self.stdout.write(self.style.SUCCESS(f"Updated Invoice {invoice.invoice_number} for {tenant.name} -> {status}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} platform invoices."))
