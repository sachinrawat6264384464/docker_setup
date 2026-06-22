import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from django_tenants.utils import schema_context
from tenants.models import Client
from django.contrib.auth import get_user_model

User = get_user_model()

print("=== ALL USER SCHEMAS AND USERS ===")
clients = Client.objects.all()
for c in clients:
    print(f"\nSchema: {c.schema_name} (Tenant: {c.name})")
    with schema_context(c.schema_name):
        users = User.objects.all()
        print(f"  Total Users: {users.count()}")
        for u in users:
            print(f"    - ID: {u.id}, Email: {u.email}, Role: {u.role}, Tenant_ID field: {getattr(u, 'tenant_id', None)}")

print("\n=== PUBLIC SCHEMA USERS ===")
with schema_context('public'):
    users = User.objects.all()
    print(f"  Total Users: {users.count()}")
    for u in users:
        print(f"    - ID: {u.id}, Email: {u.email}, Role: {u.role}, Tenant_ID field: {getattr(u, 'tenant_id', None)}")
