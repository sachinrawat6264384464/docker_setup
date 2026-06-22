import os
import sys
import django

# Set up Django environment
sys.path.append(r'D:\mykhataproject\nextj2s\nextjs\test\backend1\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from tenants.models import Client
from accounts.models import User
from django_tenants.utils import schema_context

clients = Client.objects.all().order_by('-id')[:10]
print("--- Recent Organizations ---")
for c in clients:
    print(f"ID: {c.id} | Name: {c.name} | Schema: {c.schema_name}")
    
    # Check for Master Admin in this schema
    with schema_context(c.schema_name):
        admins = User.objects.filter(role='master_admin')
        for admin in admins:
            print(f"  -> Admin Found: {admin.username} ({admin.email}) | Role: {admin.role}")

print("\n--- Done ---")
