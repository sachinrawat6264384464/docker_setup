import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from tenants.models import Client
from accounts.models import User
from django_tenants.utils import schema_context

# Get latest created organization
latest_org = Client.objects.exclude(schema_name='public').order_by('-created_on').first()

if latest_org:
    print(f"\n--- DEBUGGING LATEST ORG: {latest_org.name} ---")
    print(f"Schema: {latest_org.schema_name}")
    
    with schema_context(latest_org.schema_name):
        users = User.objects.all()
        print(f"Users in this schema:")
        for u in users:
            print(f"- Username: {u.username} | Email: {u.email} | Role: {u.role}")
else:
    print("No organizations found.")
