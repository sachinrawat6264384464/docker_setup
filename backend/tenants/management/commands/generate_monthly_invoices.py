from django.core.management.base import BaseCommand
from django.utils import timezone
from tenants.models import PlatformInvoice, Client, TenantSubscription
from decimal import Decimal
import datetime


class Command(BaseCommand):
    help = 'Generates pending recurring monthly Platform Invoices for all active subscriptions'

    def handle(self, *args, **options):
        # 1. Query active subscriptions (excluding public schema)
        active_subs = TenantSubscription.objects.filter(
            status='active'
        ).exclude(tenant__schema_name='public').select_related('tenant')

        if not active_subs.exists():
            self.stdout.write(self.style.WARNING("No active tenant subscriptions found."))
            return

        today = timezone.now().date()
        due_date = today + timezone.timedelta(days=7)
        current_year = today.year
        current_month = today.month

        invoice_count = 0
        skipped_count = 0

        for sub in active_subs:
            tenant = sub.tenant
            
            # Skip custom/enterprise plan calculations unless they have a monthly charge set
            # (Enterprise or custom pricing may be flat rate, already handled by sub.monthly_amount)
            amount = sub.monthly_amount
            if amount <= 0:
                self.stdout.write(self.style.WARNING(
                    f"Skipping subscription for '{tenant.name}' as monthly amount is $0.00."
                ))
                skipped_count += 1
                continue

            # 2. Check if an invoice for the platform subscription has already been created this month
            # to avoid double billing.
            already_invoiced = PlatformInvoice.objects.filter(
                tenant=tenant,
                plan_name__startswith="Platform Subscription",
                created_at__year=current_year,
                created_at__month=current_month
            ).exists()

            if already_invoiced:
                self.stdout.write(self.style.NOTICE(
                    f"Platform subscription invoice already generated this month for '{tenant.name}'. Skipping."
                ))
                skipped_count += 1
                continue

            plan_display = (tenant.subscription_plan or 'basic').capitalize()

            # 3. Create the recurring PlatformInvoice
            invoice = PlatformInvoice.objects.create(
                tenant=tenant,
                amount=amount,
                plan_name=f"Platform Subscription - {plan_display}",
                status='pending',
                billing_email=tenant.contact_email or 'billing@hoaconnecthub.com',
                due_date=due_date,
                remarks=f"Recurring monthly invoice for {tenant.name} ({plan_display} Plan). Units limit: {sub.max_units}."
            )

            invoice_count += 1
            self.stdout.write(self.style.SUCCESS(
                f"Generated Invoice {invoice.invoice_number} for '{tenant.name}' amount ${amount:.2f}"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"Successfully processed recurring invoicing: {invoice_count} created, {skipped_count} skipped."
        ))
