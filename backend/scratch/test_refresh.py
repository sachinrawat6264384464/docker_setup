import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')
import django
django.setup()

from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory
from accounts.views import LoginView, CookieTokenRefreshView
from django.contrib.auth import get_user_model

User = get_user_model()

print("--- Step 1: Logging in user '9977885566' on schema 'tenant_demo' ---")
factory = APIRequestFactory()

# We need to simulate the login POST request
# LoginView expects identifier and password. We know password for sachin is probably something standard,
# or we can manually set it to 'Password123!' or retrieve a token directly by manually creating a RefreshToken for the user.
# Let's directly generate a RefreshToken for the user and then call CookieTokenRefreshView to see if it refreshes successfully!
from rest_framework_simplejwt.tokens import RefreshToken

with schema_context('tenant_demo'):
    user = User.objects.get(username='9977885566')
    refresh = RefreshToken.for_user(user)
    refresh['role'] = user.role
    refresh['tenant'] = 'tenant_demo'
    refresh_token_str = str(refresh)
    print(f"Generated Refresh Token: {refresh_token_str[:40]}...")

    print("\n--- Step 2: Calling CookieTokenRefreshView.post() ---")
    # Simulate a POST request with the refresh token in the request body
    request = factory.post('/api/auth/token/refresh/', {'refresh': refresh_token_str}, format='json')
    # Set headers like X-Tenant to mimic middleware
    request.headers = {'X-Tenant': 'demo.hoaconnecthub.com'}
    
    view = CookieTokenRefreshView.as_view()
    response = view(request)
    print(f"Response Status Code: {response.status_code}")
    print(f"Response Data: {response.data if hasattr(response, 'data') else response.content}")
