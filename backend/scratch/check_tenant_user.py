# Run this inside python manage.py shell
from accounts.models import User
from django_tenants.utils import schema_context
from tenants.models import Client

def check_tenant_user(schema_name, identifier):
    print(f"Checking user '{identifier}' in schema '{schema_name}'...")
    with schema_context(schema_name):
        user = User.objects.filter(email=identifier).first() or User.objects.filter(username=identifier).first()
        if user:
            print(f"✅ User found!")
            print(f"Username: {user.username}")
            print(f"Email: {user.email}")
            print(f"Role: {user.role}")
            print(f"Is Active: {user.is_active}")
            print(f"Is Approved: {user.is_approved}")
            # We can't see the password, but we can test it
            test_pass = "Propra@123"
            if user.check_password(test_pass):
                print(f"✅ Password 'Propra@123' is CORRECT.")
            else:
                print(f"❌ Password 'Propra@123' is INCORRECT.")
        else:
            print(f"❌ User NOT found in this schema.")

# Replace with your actual tenant schema and email/username
check_tenant_user('tenant_aparna', 'aparna@example.com') # Change this to the real email you used
