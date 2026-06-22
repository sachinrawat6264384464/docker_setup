import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from tenants.models import Client, Domain

def fix_public_domains():
    public_tenant = Client.objects.get(schema_name='public')
    
    domains_to_add = ['localhost', '127.0.0.1']
    
    for d in domains_to_add:
        domain, created = Domain.objects.get_or_create(
            domain=d,
            tenant=public_tenant,
            defaults={'is_primary': False}
        )
        if created:
            print(f"✅ Added {d} to public domains.")
        else:
            print(f"ℹ️ {d} already exists in public domains.")

if __name__ == "__main__":
    fix_public_domains()
