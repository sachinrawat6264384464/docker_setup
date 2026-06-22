import os
import django
import sys

# Set up django environment
sys.path.append('d:\\mykhataproject\\hoausa\\hoa_usa\\merge\\hoa_usa-fm-invoices-fix\\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from tenants.models import Client, PlatformInvoice, TenantSubscription

client = Client.objects.filter(schema_name='kon').first()
if client:
    print(f"Client: {client.name}, Plan: {client.subscription_plan}")
    sub = TenantSubscription.objects.filter(tenant=client).first()
    if sub:
        print(f"Subscription max_units: {sub.max_units}, monthly_amount: {sub.monthly_amount}")
    
    invoices = PlatformInvoice.objects.filter(tenant=client).order_by('-created_at')
    for inv in invoices:
        print(f"Invoice: {inv.invoice_number}, Amount: {inv.amount}, Status: {inv.status}, Created: {inv.created_at}, Plan: {inv.plan_name}, Remarks: {inv.remarks}")
else:
    print("Client 'kon' not found")
