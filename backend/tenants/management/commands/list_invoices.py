from django.core.management.base import BaseCommand
from tenants.models import PlatformInvoice

class Command(BaseCommand):
    help = 'List all platform invoices'

    def handle(self, *args, **options):
        invoices = PlatformInvoice.objects.all()
        if not invoices:
            self.stdout.write(self.style.WARNING("No invoices found in database."))
            return

        self.stdout.write(self.style.SUCCESS(f"Found {invoices.count()} invoices:"))
        for inv in invoices:
            self.stdout.write(f"- {inv.invoice_number} | {inv.tenant.name} | {inv.amount} | {inv.status}")
