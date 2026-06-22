
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from accounts.models import User
from django_tenants.utils import schema_context

print("--- Public Schema Users ---")
with schema_context('public'):
    for user in User.objects.all():
        print(f"Username: {user.username}, Email: {user.email}, Role: {user.role}, IsActive: {user.is_active}")

print("\n--- demo.localhost (tenant_sunrise) Users ---")
from tenants.models import Client
try:
    tenant = Client.objects.get(schema_name='tenant_sunrise')
    with schema_context('tenant_sunrise'):
        for user in User.objects.all():
            print(f"Username: {user.username}, Email: {user.email}, Role: {user.role}, IsActive: {user.is_active}")
except Exception as e:
    print(f"Error: {e}")
