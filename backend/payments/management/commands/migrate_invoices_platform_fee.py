from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from tenants.models import Client
from payments.models import Invoice
from decimal import Decimal

class Command(BaseCommand):
    help = "Migrates existing unpaid invoices by removing platform fee from their line items and total_amount."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Run without making changes')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        clients = Client.objects.exclude(schema_name='public')
        
        migrated_count = 0
        skipped_count = 0

        self.stdout.write(f"Starting invoice migration (Dry Run: {dry_run})...")

        for client in clients:
            with schema_context(client.schema_name):
                invoices = Invoice.objects.filter(status__in=['draft', 'sent', 'viewed'])
                for invoice in invoices:
                    if not invoice.line_items:
                        skipped_count += 1
                        continue

                    new_line_items = []
                    fee_removed = Decimal('0.00')
                    modified = False

                    for item in invoice.line_items:
                        desc_lower = str(item.get('description', item.get('name', ''))).lower()
                        type_lower = str(item.get('type', '')).lower()

                        if type_lower == 'platform_fee' or 'association charge' in desc_lower or 'platform fee' in desc_lower:
                            qty = Decimal(str(item.get('quantity', 1)))
                            unit_price = Decimal(str(item.get('unit_price', item.get('rate', 0))))
                            item_amt = Decimal(str(item.get('amount', item.get('total', float(qty) * float(unit_price)))))
                            fee_removed += item_amt
                            modified = True
                        else:
                            new_line_items.append(item)

                    if modified:
                        if not dry_run:
                            invoice.line_items = new_line_items
                            invoice.total_amount -= fee_removed
                            invoice.amount_due -= fee_removed
                            invoice.save(update_fields=['line_items', 'total_amount', 'amount_due'])
                        migrated_count += 1
                        self.stdout.write(self.style.SUCCESS(f"Migrated invoice {invoice.id} in {client.schema_name} (Removed: ${fee_removed})"))
                    else:
                        skipped_count += 1

        self.stdout.write(self.style.SUCCESS(f"Done. Migrated: {migrated_count}, Skipped: {skipped_count}"))
