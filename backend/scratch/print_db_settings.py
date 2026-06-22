import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from django.conf import settings
print("DATABASES:", settings.DATABASES)
