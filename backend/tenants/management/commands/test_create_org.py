from django.core.management.base import BaseCommand
from tenants.models import Client, Domain
from django.utils import timezone
import traceback

class Command(BaseCommand):
    help = 'Test organization creation and capture errors'

    def handle(self, *args, **options):
        try:
            self.stdout.write("Testing organization creation for 'Hoa'...")
            schema_name = f"tenant_hoa_test_{int(timezone.now().timestamp())}"
            
            # 1. Create Tenant
            tenant = Client.objects.create(
                name="Hoa Test Full", 
                schema_name=schema_name,
                subscription_plan="basic",
                is_active=True,
                contact_email="test@hoa.com"
            )
            self.stdout.write(self.style.SUCCESS(f"Step 1: Created tenant {tenant.schema_name}"))
            
            # 2. Create Domain
            Domain.objects.create(domain=f"{schema_name}.localhost", tenant=tenant, is_primary=True)
            self.stdout.write(self.style.SUCCESS("Step 2: Created domain"))
            
            # 3. Create Admin User (Inside Schema)
            from django_tenants.utils import schema_context
            from accounts.models import User
            with schema_context(tenant.schema_name):
                user = User.objects.create_user(
                    username="hoadmin",
                    email="test@hoa.com",
                    password="Propra@123",
                    role='master_admin',
                    is_active=True,
                    is_approved=True,
                    tenant_id=tenant.schema_name
                )
                self.stdout.write(self.style.SUCCESS(f"Step 3: Created admin user {user.username} in schema"))

            # 4. Create Platform Invoice (Outside Schema)
            from tenants.models import PlatformInvoice
            from decimal import Decimal
            invoice = PlatformInvoice.objects.create(
                tenant=tenant,
                amount=Decimal("999.00"),
                plan_name='basic',
                status='pending',
                billing_email="test@hoa.com",
                due_date=timezone.now().date() + timezone.timedelta(days=7),
                remarks='Test Activation Invoice'
            )
            self.stdout.write(self.style.SUCCESS(f"Step 4: Created platform invoice {invoice.invoice_number}"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌ ERROR DETECTED: {str(e)}"))
            traceback.print_exc()
