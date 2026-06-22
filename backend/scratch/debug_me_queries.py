import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
import django
django.setup()

from django.db import connection
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory
from accounts.views import current_user
from django.contrib.auth import get_user_model
from tenants.models import Client

User = get_user_model()

# Find first tenant
tenant = Client.objects.exclude(schema_name='public').first()
if not tenant:
    print("No tenants found!")
    exit(1)

print(f"Using tenant: {tenant.schema_name}")

# Switch context to tenant
connection.set_tenant(tenant)

with schema_context(tenant.schema_name):
    # Find a user in this tenant
    user = User.objects.first()
    if not user:
        print(f"No users found in tenant {tenant.schema_name}!")
        exit(1)
    
    print(f"Using user: {user.username} with role: {user.role}")

    # Build mock request
    factory = APIRequestFactory()
    request = factory.get('/api/auth/me/')
    request.user = user

    # Clear query log
    connection.queries_log.clear()
    
    # Run the view
    from django.test import utils
    utils.setup_test_environment()
    
    # Enable query logging
    from django.conf import settings
    settings.DEBUG = True
    
    response = current_user(request)
    
    print(f"Response status: {response.status_code}")
    print(f"Total queries made: {len(connection.queries)}")
    for i, q in enumerate(connection.queries, 1):
        print(f"\n[{i}] SQL: {q['sql']}\nTime: {q['time']}")
