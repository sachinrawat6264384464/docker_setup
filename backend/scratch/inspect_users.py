import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
import django
django.setup()

from django_tenants.utils import schema_context
from accounts.models import User

with schema_context('tenant_demo'):
    for u in User.objects.all():
        print(f"Username: {u.username}, Email: {u.email}, Role: {u.role}")
