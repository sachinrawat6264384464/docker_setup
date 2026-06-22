import os
import django
import sys
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
sys.path.append(os.getcwd())
django.setup()

from tenants.models import Client
from django.contrib.auth import get_user_model
from properties.models import Unit

def inspect():
    User = get_user_model()
    try:
        client = Client.objects.get(schema_name='tenant_jhjhh')
    except Client.DoesNotExist:
        print("Schema tenant_jhjhh does not exist.")
        return
        
    connection.set_tenant(client)
    print("=== UNITS ===")
    for u in Unit.objects.all():
        print(f"Unit: {u.unit_number}, Building: {u.building.name if u.building else 'None'}, Status: {u.status}, UnitType: {u.unit_type}")
        print(f"  Owner Details: {u.owner_first_name} {u.owner_last_name}, Phone: {u.owner_phone}, Email: {u.owner_email}")
        print(f"  Linked Owner User: {u.owner_user.username if u.owner_user else 'None'} ({u.owner_user.get_full_name() if u.owner_user else ''})")
        
    print("\n=== USERS (role=owner) ===")
    for user in User.objects.filter(role='owner'):
        print(f"User: {user.username}, Name: {user.get_full_name()}, Phone: {user.phone}, Email: {user.email}, Unit: {user.unit_number}, Bldg: {user.building_name}")

if __name__ == "__main__":
    inspect()
