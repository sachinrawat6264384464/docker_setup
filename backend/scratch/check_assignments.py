
import os
import django
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from maintenance.models import MaintenanceRequest
from accounts.models import User

# Switch to tenant schema
schema_name = 'tenant_koko'
connection.set_schema(schema_name)

print(f"--- DIAGNOSTIC FOR SCHEMA: {schema_name} ---")

total_requests = MaintenanceRequest.objects.count()
print(f"Total Maintenance Requests: {total_requests}")

users = User.objects.filter(role='tenant_vendor')
print(f"Vendor Users in this schema: {users.count()}")
for u in users:
    assigned_count = MaintenanceRequest.objects.filter(assigned_to=u).count()
    print(f"User: {u.username} (ID: {u.id}) - Assigned Requests: {assigned_count}")

# List first 5 requests and their assignments
print("\nRecent Requests:")
for r in MaintenanceRequest.objects.all().order_by('-created_at')[:5]:
    assigned_name = r.assigned_to.username if r.assigned_to else "UNASSIGNED"
    print(f"ID: {r.id} | Title: {r.title} | Status: {r.status} | Assigned to: {assigned_name}")
