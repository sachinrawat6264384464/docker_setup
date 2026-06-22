# tenants/urls.py - PUBLIC SCHEMA TENANT MANAGEMENT API
# Included at: /api/system/tenants/ from urls_public.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ClientViewSet, DomainViewSet, TenantSettingsViewSet,
    TenantFeatureViewSet, TenantSubscriptionViewSet, KYCViewSet, PlatformInvoiceViewSet,
    system_stats, current_tenant, tenant_health_check,
    activate_tenant, deactivate_tenant,
    global_stripe_settings, master_admin_invoices, test_global_stripe_connection,
    clear_system_cache, purge_analytics_events, test_email_connection
)
from . import views_connect

router = DefaultRouter()
router.register(r'clients', ClientViewSet, basename='client')
router.register(r'domains', DomainViewSet, basename='domain')
router.register(r'settings', TenantSettingsViewSet, basename='tenant-settings')
router.register(r'features', TenantFeatureViewSet, basename='tenant-feature')
router.register(r'subscriptions', TenantSubscriptionViewSet, basename='tenant-subscription')
router.register(r'kyc', KYCViewSet, basename='kyc')
router.register(r'platform-invoices', PlatformInvoiceViewSet, basename='platform-invoice')

urlpatterns = [
    path('', include(router.urls)),
    path('system/stats/', system_stats, name='system-stats'),
    path('current/', current_tenant, name='current-tenant'),
    path('<int:tenant_id>/health/', tenant_health_check, name='tenant-health'),
    path('<int:tenant_id>/activate/', activate_tenant, name='activate-tenant'),
    path('<int:tenant_id>/deactivate/', deactivate_tenant, name='deactivate-tenant'),
    path('global-stripe-settings/', global_stripe_settings, name='global-stripe-settings'),
    path('test-global-stripe/', test_global_stripe_connection, name='test-global-stripe'),
    path('test-email/', test_email_connection, name='test-email'),
    path('my-invoices/', master_admin_invoices, name='master-admin-invoices'),
    path('system/clear-cache/', clear_system_cache, name='system-clear-cache'),
    path('system/purge-events/', purge_analytics_events, name='system-purge-events'),
    
    # Stripe Connect Endpoints
    path('connect/create-account/', views_connect.create_connected_account, name='create_connected_account'),
    path('connect/account-link/', views_connect.get_onboarding_link, name='get_onboarding_link'),
    path('connect/status/<int:org_id>/', views_connect.get_connect_status, name='get_connect_status'),
    path('connect/webhooks/stripe/connect/', views_connect.stripe_connect_webhook, name='stripe_connect_webhook'),
    
    # Owner Stripe Connect Endpoints
    path('connect/owner/create-account/', views_connect.owner_create_connected_account, name='owner_create_connected_account'),
    path('connect/owner/account-link/', views_connect.owner_get_onboarding_link, name='owner_get_onboarding_link'),
    path('connect/owner/status/', views_connect.owner_get_connect_status, name='owner_get_connect_status'),
    path('connect/owner/return/', views_connect.owner_stripe_return, name='owner_stripe_return'),
    path('connect/owner/refresh/', views_connect.owner_stripe_refresh, name='owner_stripe_refresh'),
    path('owner-connect/profile/', views_connect.owner_get_stripe_profile, name='owner_get_stripe_profile'),
]
