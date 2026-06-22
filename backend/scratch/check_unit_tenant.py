import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from django.contrib.auth import get_user_model
from properties.models import Unit, Lease, Building

User = get_user_model()

print("--- USERS (Tenants) ---")
for u in User.objects.filter(role='tenant'):
    print(f"ID: {u.id}, Name: {u.get_full_name()}, Email: {u.email}, Unit: {u.unit_number}, Building: {u.building_name}")

print("\n--- UNITS ---")
for unit in Unit.objects.all():
    print(f"ID: {unit.id}, Number: {unit.unit_number}, Type: {unit.unit_type}, Building: {unit.building.name if unit.building else None}")

print("\n--- LEASES ---")
for lease in Lease.objects.all():
    print(f"ID: {lease.id}, Tenant: {lease.tenant.email}, Unit: {lease.unit.unit_number}, Status: {lease.status}")
