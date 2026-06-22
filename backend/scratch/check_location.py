import os
import sys
import django

# Set up Django
sys.path.append(r'D:\mykhataproject\nextj2s\nextjs\test\backend1\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from location_master.models import State, District, City
from django.db import connection

print(f"Current Schema: {connection.schema_name}")
print(f"Total States: {State.objects.count()}")
print(f"Total Districts: {District.objects.count()}")
print(f"Total Cities: {City.objects.count()}")
