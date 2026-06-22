import os, sys, django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from django.contrib.auth import get_user_model
from django_tenants.utils import schema_context
from tenants.models import Client
from properties.models import Unit, Lease

User = get_user_model()

print("Available schemas:")
for c in Client.objects.all():
    print(f"- {c.schema_name}")
    with schema_context(c.schema_name):
        print("  Tenants:")
        for u in User.objects.filter(role='tenant'):
            print(f"    Tenant: ID={u.id}, Email={u.email}, Unit={u.unit_number}, Bldg={u.building_name}")
        print("  Units:")
        for unit in Unit.objects.all():
            print(f"    Unit: ID={unit.id}, Number={unit.unit_number}, Type={unit.unit_type}, Status={unit.status}, Resident={unit.current_resident}")
        print("  Leases:")
        for lease in Lease.objects.all():
            print(f"    Lease: ID={lease.id}, Tenant={lease.tenant.email}, Unit={lease.unit.unit_number}, Status={lease.status}")
