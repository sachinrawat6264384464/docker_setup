import os
import sys
import django
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from django.test import RequestFactory
from accounts.views import UserViewSet
from django.db import connection, reset_queries

# Create a mock request
factory = RequestFactory()
request = factory.get('/api/auth/users/global-team/')

# Mock a super_admin user
from django.contrib.auth import get_user_model
User = get_user_model()
admin_user = User.objects.filter(role__in=('super_admin', 'superadmin', 'super_admin_admin')).first()

if not admin_user:
    print("No admin user found to run test!")
    sys.exit(0)

request.user = admin_user

reset_queries()
view = UserViewSet.as_view({'get': 'global_team'})
response = view(request)

print("Status code:", response.status_code)
print("Total members returned:", len(response.data.get('results', [])))
print("Number of queries made:", len(connection.queries))

# Print first 20 queries to inspect
print("\nFirst 20 queries:")
for q in connection.queries[:20]:
    print(q['sql'][:150])
