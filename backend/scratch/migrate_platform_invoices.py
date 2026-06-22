# Run this inside python manage.py shell
from tenants.models import Client, PlatformInvoice
from django.db import connection

def migrate_invoices():
    print("Starting invoice migration...")
    
    with connection.cursor() as cursor:
        try:
            # Look for invoices in the public schema payments_invoice table
            cursor.execute("SELECT building, total_amount, status, due_date, created_at FROM payments_invoice")
            old_invoices = cursor.fetchall()
            print(f"Found {len(old_invoices)} old invoices in public schema.")
        except Exception as e:
            print(f"No old invoices found or table doesn't exist: {e}")
            return

    count = 0
    for building_name, total_amount, status, due_date, created_at in old_invoices:
        tenant = Client.objects.filter(name=building_name).first()
        if not tenant:
            print(f"Skipping: Organization '{building_name}' not found.")
            continue
            
        if PlatformInvoice.objects.filter(tenant=tenant).exists():
            print(f"Skipping: Invoice for '{building_name}' already exists in new table.")
            continue
            
        PlatformInvoice.objects.create(
            tenant=tenant,
            amount=total_amount,
            plan_name=tenant.subscription_plan or 'basic',
            status='verified' if status == 'verified' else 'pending',
            billing_email=tenant.contact_email or "admin@example.com",
            due_date=due_date or (created_at.date() if created_at else None),
            remarks=f"Migrated from old system. Original status: {status}"
        )
        count += 1
        print(f"Migrated invoice for: {building_name}")

    print(f"Successfully migrated {count} invoices.")

migrate_invoices()
