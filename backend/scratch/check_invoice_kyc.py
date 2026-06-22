import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from payments.models import Invoice
from accounts.models import User
from tenants.models import Client, KYC

invoices = Invoice.objects.all()
print(f"Total invoices: {invoices.count()}")

for inv in invoices:
    user = inv.user
    tenant_id = getattr(user, 'tenant_id', None)
    
    kyc_status = 'pending'
    if tenant_id:
        client = Client.objects.filter(schema_name=tenant_id).first()
        if client and hasattr(client, 'kyc'):
            kyc_status = client.kyc.status
            
    print(f"Invoice {inv.invoice_number}:")
    print(f"  User: {user.username} (Role: {user.role}, tenant_id: {tenant_id})")
    print(f"  KYC Status (calculated): {kyc_status}")
    print("-" * 40)
