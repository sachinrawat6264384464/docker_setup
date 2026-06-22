import os
import sys
import django

# Set up Django
sys.path.append(r'D:\mykhataproject\nextj2s\nextjs\test\backend1\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from tenants.models import Client, Domain
from accounts.models import User
from django_tenants.utils import schema_context

results = []
results.append("--- Detailed Tenant & User Audit ---")

clients = Client.objects.all().order_by('-id')
for c in clients:
    results.append(f"\nOrganization: {c.name} | Schema: {c.schema_name}")
    domains = Domain.objects.filter(tenant=c)
    for d in domains:
        results.append(f"  Domain: {d.domain}")
        
    with schema_context(c.schema_name):
        users = User.objects.all()
        for u in users:
            results.append(f"  User: {u.username} | Role: {u.role} | Active: {u.is_active}")

with open('scratch/audit_results.txt', 'w', encoding='utf-8') as f:
    f.write("\n".join(results))
