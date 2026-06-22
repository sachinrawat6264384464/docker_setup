# payments/management/commands/migrate_to_connect.py
import stripe
from django.core.management.base import BaseCommand
from django.conf import settings
from django_tenants.utils import schema_context
from tenants.models import Client
from payments.models import PaymentGateway

class Command(BaseCommand):
    help = "Migrates existing Stripe BYOK gateways to Stripe Connect Express accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run the migration without creating Stripe accounts or writing to DB.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        stripe.api_key = settings.STRIPE_PLATFORM_SECRET_KEY

        if not stripe.api_key:
            self.stdout.write(self.style.ERROR("STRIPE_PLATFORM_SECRET_KEY is not configured in settings."))
            return

        tenants = Client.objects.exclude(schema_name='public')
        self.stdout.write(self.style.SUCCESS(f"Found {tenants.count()} organizations to inspect for migration."))

        migrated_count = 0
        skipped_count = 0

        for tenant in tenants:
            schema_name = tenant.schema_name
            with schema_context(schema_name):
                gateway = PaymentGateway.objects.filter(gateway_type='stripe').first()
                if not gateway:
                    self.stdout.write(f"Organization '{tenant.name}' ({schema_name}) has no Stripe gateway configured. Skipping.")
                    skipped_count += 1
                    continue

                if gateway.stripe_connected_account_id:
                    self.stdout.write(f"Organization '{tenant.name}' ({schema_name}) already has Connect Account ID: {gateway.stripe_connected_account_id}. Skipping.")
                    skipped_count += 1
                    continue

                # To migrate, we need a secret key or email context
                email = tenant.contact_email or "billing@hoaconnecthub.com"
                
                self.stdout.write(self.style.WARNING(f"Migrating organization '{tenant.name}' ({schema_name}) with email '{email}'..."))

                if dry_run:
                    self.stdout.write(f"[DRY-RUN] Would create Stripe Express Account for '{tenant.name}'")
                    migrated_count += 1
                    continue

                try:
                    account = stripe.Account.create(
                        type='express',
                        country='US',
                        email=email,
                        capabilities={
                            'card_payments': {'requested': True},
                            'transfers':     {'requested': True},
                        },
                        metadata={
                            'org_id': str(tenant.id),
                            'tenant_schema': schema_name,
                        }
                    )
                    gateway.stripe_connected_account_id = account.id
                    gateway.payment_status = 'PENDING'
                    gateway.save(update_fields=['stripe_connected_account_id', 'payment_status'])
                    self.stdout.write(self.style.SUCCESS(f"Successfully migrated '{tenant.name}' to Connect Account ID: {account.id}"))
                    migrated_count += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Failed to migrate '{tenant.name}': {str(e)}"))

        self.stdout.write(self.style.SUCCESS(
            f"Migration completed. Migrated: {migrated_count}, Skipped/Already Connected: {skipped_count} (Dry Run: {dry_run})"
        ))
