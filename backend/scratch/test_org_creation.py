import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from tenants.models import Client, Domain
from django_tenants.utils import schema_context

def test_create():
    try:
        print("Testing organization creation for 'Hoa'...")
        # Try to create client
        schema_name = "tenant_hoa_test"
        tenant = Client.objects.create(
            name="Hoa", 
            schema_name=schema_name,
            subscription_plan="basic",
            is_active=True
        )
        print(f"Successfully created tenant object: {tenant.schema_name}")
        
        Domain.objects.create(domain="hoa.localhost", tenant=tenant, is_primary=True)
        print("Successfully created domain object")
        
    except Exception as e:
        print(f"\n❌ ERROR DETECTED: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_create()
