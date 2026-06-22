from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ClientViewSet, DomainViewSet, TenantSettingsViewSet, 
    TenantFeatureViewSet, TenantSubscriptionViewSet, KYCViewSet,
    PlatformInvoiceViewSet, PlatformPaymentMethodViewSet, PlatformAutopayViewSet,
    current_tenant, system_stats, tenant_health_check,
    activate_tenant, deactivate_tenant, available_features,
    tenant_usage_report, clear_system_cache, purge_analytics_events,
    sync_schemas_view, check_domain_health_view, rotate_api_keys_view,
    enforce_2fa_system_wide, master_admin_invoices,
    # Discovery
    discovery_cities, discovery_orgs,
    api_hub_discovery,
)
from propflow.health import admin_health_check
from . import views_connect

# Use a router for ViewSets
router = DefaultRouter()
router.register(r'clients', ClientViewSet, basename='client')
router.register(r'domains', DomainViewSet, basename='domain')
router.register(r'settings', TenantSettingsViewSet, basename='tenant-settings')
router.register(r'features', TenantFeatureViewSet, basename='tenant-feature')
router.register(r'subscriptions', TenantSubscriptionViewSet, basename='tenant-subscription')
router.register(r'kyc', KYCViewSet, basename='kyc')
router.register(r'platform-invoices', PlatformInvoiceViewSet, basename='platform-invoice')
router.register(r'platform-payment-methods', PlatformPaymentMethodViewSet, basename='platform-payment-method')
router.register(r'platform-autopay', PlatformAutopayViewSet, basename='platform-autopay')

urlpatterns = [
    # Router endpoints (clients/, domains/, etc.)
    path('', include(router.urls)),
    
    # Function-based endpoints
    path('current/', current_tenant, name='current-tenant'),
    path('system/stats/', system_stats, name='system-stats'),
    path('system/health/', admin_health_check, name='system-health'),
    path('features/available/', available_features, name='available-features'),
    path('my-invoices/', master_admin_invoices, name='master-admin-invoices'),
    
    # Specific tenant management
    path('<int:tenant_id>/health/', tenant_health_check, name='tenant-health'),
    path('<int:tenant_id>/activate/', activate_tenant, name='activate-tenant'),
    path('<int:tenant_id>/deactivate/', deactivate_tenant, name='deactivate-tenant'),
    path('<int:tenant_id>/usage-report/', tenant_usage_report, name='tenant-usage-report'),

    # Infrastructure & Danger Zone
    path('infrastructure/clear-cache/', clear_system_cache, name='clear-cache'),
    path('infrastructure/sync-schemas/', sync_schemas_view, name='sync-schemas'),
    path('infrastructure/domain-health/', check_domain_health_view, name='domain-health'),
    path('infrastructure/rotate-keys/', rotate_api_keys_view, name='rotate-keys'),
    path('infrastructure/enforce-2fa/', enforce_2fa_system_wide, name='enforce-2fa'),
    path('system/purge-events/', purge_analytics_events, name='purge-events'),

    # Public org discovery (no auth required — used by mobile app login)
    path('discovery/cities/', discovery_cities, name='discovery-cities'),
    path('discovery/', discovery_orgs, name='discovery-orgs'),

    # API Hub — authenticated URL introspection for super admins
    path('api-hub/discovery/', api_hub_discovery, name='api-hub-discovery'),

    # Stripe Connect Endpoints
    path('connect/create-account/', views_connect.create_connected_account, name='get_connected_account'),
    path('connect/account-link/', views_connect.get_onboarding_link, name='get_onboarding_link'),
    path('connect/status/<int:org_id>/', views_connect.get_connect_status, name='get_connect_status'),
    path('connect/stripe-profile/', views_connect.get_stripe_profile, name='get_stripe_profile'),
    path('connect/webhooks/stripe/connect/', views_connect.stripe_connect_webhook, name='stripe_connect_webhook'),
]
