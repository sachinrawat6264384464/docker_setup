import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

try:
    from tenants.views_connect import _get_stripe_api_key
    key = _get_stripe_api_key()
    print("Success: views_connect imported cleanly.")
    print("Resolved Stripe API Key exists:", bool(key))
    if key:
        print("Resolved Stripe API Key (truncated):", key[:10] + "...")
except Exception as e:
    print("Error during import/verification:", e)
