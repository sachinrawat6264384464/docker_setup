import os
import sys

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
django.setup()

from django.conf import settings
from payments.models import PaymentGateway
from django_tenants.utils import schema_context

print("STRIPE_PLATFORM_SECRET_KEY:", getattr(settings, 'STRIPE_PLATFORM_SECRET_KEY', None))
print("STRIPE_SECRET_KEY:", getattr(settings, 'STRIPE_SECRET_KEY', None))

with schema_context('public'):
    gateway = PaymentGateway.objects.filter(gateway_type='stripe').first()
    if gateway:
        print("Database Stripe Public Secret Key exists:", bool(gateway.secret_key))
        print("Database Stripe Public Secret Key (truncated):", gateway.secret_key[:10] + "..." if gateway.secret_key else "None")
    else:
        print("No stripe gateway in public schema db.")
