import os
import sys
import django
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from django.apps import apps
from django.conf import settings

print("Registered Apps and their labels:")
for app_config in apps.get_app_configs():
    print(f"Name: {app_config.name}, Label: {app_config.label}")

print("\nComparing shared apps:")
shared_app_labels = set()
for app in settings.SHARED_APPS:
    parts = app.split('.')
    if 'apps' in parts:
        shared_app_labels.add(parts[0])
    else:
        shared_app_labels.add(parts[-1])

print("Extracted Labels:", shared_app_labels)
registered_labels = {ac.label for ac in apps.get_app_configs()}
for label in shared_app_labels:
    if label not in registered_labels:
        print(f"WARNING: Extracted label '{label}' is not a registered app label!")
