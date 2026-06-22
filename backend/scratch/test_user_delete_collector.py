import os
import sys
import django
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models.deletion import Collector

User = get_user_model()
u = User(username='test_dummy_user_123', email='test_dummy_user_123@example.com')
u.id = '00000000-0000-0000-0000-000000000000' # Dummy ID

# Let's inspect the collector logic
from django.conf import settings
collector = Collector(using='default')
print("Collector targets:")

shared_app_labels = set()
for app in settings.SHARED_APPS:
    parts = app.split('.')
    if 'apps' in parts:
        shared_app_labels.add(parts[0])
    else:
        shared_app_labels.add(parts[-1])

opts = User._meta

print("Original get_fields count:", len(opts.get_fields(include_hidden=True)))

shared_app_labels = set()
for app in settings.SHARED_APPS:
    parts = app.split('.')
    if 'apps' in parts:
        shared_app_labels.add(parts[0])
    else:
        shared_app_labels.add(parts[-1])

original_get_fields = opts.get_fields

def patched_get_fields(include_parents=True, include_hidden=False):
    fields = original_get_fields(include_parents=include_parents, include_hidden=include_hidden)
    filtered = []
    for f in fields:
        if f.auto_created and not f.concrete and (f.one_to_one or f.one_to_many):
            if f.related_model and f.related_model._meta.app_label not in shared_app_labels:
                continue
        filtered.append(f)
    return filtered

# Monkeypatch
opts.get_fields = patched_get_fields

try:
    collector.collect([u])
    print("SUCCESS! No errors raised during collect with patched get_fields.")
except Exception as e:
    import traceback
    print("Error raised during collect:")
    traceback.print_exc()
finally:
    opts.get_fields = original_get_fields



