import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from tenants.models import Client, PlatformInvoice

print("\n--- ORGANIZATIONS ---")
orgs = Client.objects.all()
for org in orgs:
    print(f"- {org.name} (Schema: {org.schema_name})")

print("\n--- PLATFORM INVOICES ---")
invoices = PlatformInvoice.objects.all()
for inv in invoices:
    print(f"- {inv.invoice_number} | {inv.tenant.name} | {inv.status}")

if not invoices:
    print("No invoices found in public schema.")
