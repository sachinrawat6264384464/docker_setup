from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from rest_framework.permissions import IsAdminUser

from propflow.health import health_check_detailed, health_check_simple, admin_health_check
from tenants.views import current_tenant, stripe_platform_webhook
from accounts.views import LoginView

# API V1 Patterns
api_v1_patterns = [
    path('auth/', include('accounts.urls')),
    path('system/auth/', include('accounts.urls')),
    path('system/tenants/', include('tenants.urls_system')),
    path('notifications/', include('notifications.urls')),
    # path('profiles/', include('user_profiles.urls')),
    path('support/', include('support.urls')),
    # path('master-data/', include('master_data.urls')),
    path('reports/', include('reports.urls')),
    path('data_export/', include('data_export.urls')),
    path('data-export/', include('data_export.urls')),
    path('export/', include('data_export.urls')),
    path('location/', include('location_master.urls')),  # India address master
    path('calendar-alerts/', include('calendar_alerts.urls')),
    path('backups/', include('backups.urls')),
]

urlpatterns = [
    # --- Auth & Roles (VVIP - MUST BE AT TOP) ---
    path('api/v1/auth/login/', LoginView.as_view(), name='public_login_direct'),
    path('api/v1/auth/login', LoginView.as_view(), name='public_login_direct_no_slash'),
    path('api/v1/auth/', include('accounts.urls')),

    # --- System Management ---
    path('api/v1/system/tenants/', include('tenants.urls')),
    path('api/v1/system/tenants/current/', current_tenant),
    path('api/v1/tenants/', include('tenants.urls')),

    # --- Versioned API (v1) ---
    path('api/v1/', include(api_v1_patterns)),

    # Admin interface
    path('admin/', admin.site.urls),

    # --- Backward compatibility (Legacy - will be deprecated) ---
    path('api/auth/login/', LoginView.as_view()),
    path('api/system/auth/login/', LoginView.as_view()),
    path('api/auth/', include('accounts.urls')),
    path('api/system/tenants/', include('tenants.urls')),
    path('api/system/tenants/current/', current_tenant),
    path('api/location/', include('location_master.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/pricing/', include('pricing.urls')),
    path('api/analytics/', include('analytics.urls')),
    path('api/system-reports/', include('reports.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/calendar-alerts/', include('calendar_alerts.urls')),
    # path('api/website/', include('website.urls')),
    path('api/blog/', include('blog.urls')),
    path('api/data_export/', include('data_export.urls')),
    path('api/data-export/', include('data_export.urls')),
    path('api/export/', include('data_export.urls')),
    path('api/webhooks/platform-stripe/', stripe_platform_webhook, name='platform-stripe-webhook'),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[]), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[]), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema', permission_classes=[]), name='redoc'),

    # Health check
    path('api/health/', health_check_detailed, name='health'),
    path('api/health/live/', health_check_simple, name='health-liveness'),
    path('api/admin/health/', admin_health_check, name='health-admin'),
    path('', lambda r: JsonResponse({'message': 'Welcome to HOA Connect Hub System API'}), name='homepage'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    # Debug toolbar
    if 'debug_toolbar' in settings.INSTALLED_APPS:
        import debug_toolbar
        urlpatterns = [
            path('__debug__/', include(debug_toolbar.urls)),
        ] + urlpatterns

# Customize admin
admin.site.site_header = "PropFlow System Administration"
admin.site.site_title = "System Admin"
admin.site.index_title = "Manage Property Companies & System Settings"

# VAPT-2026-064 & VAPT-2026-066: Safe custom error handlers to prevent verbose pages leak
from django.http import HttpResponse

def custom_handler404(request, exception=None):
    if request.path.startswith('/api/'):
        return JsonResponse({'error': 'Not Found', 'detail': 'The requested resource was not found.'}, status=404)
    return HttpResponse('<h1>404 Not Found</h1>', status=404, content_type='text/html')

import logging
logger = logging.getLogger('propflow.api')

def custom_handler500(request):
    import sys
    import traceback
    exc_type, exc_value, exc_traceback = sys.exc_info()
    if exc_value:
        logger.error("Unhandled Exception: %s", exc_value, exc_info=sys.exc_info())
    if request.path.startswith('/api/'):
        return JsonResponse({'error': 'Internal Server Error', 'detail': str(exc_value) if settings.DEBUG else 'An unexpected error occurred on the server.'}, status=500)
    return HttpResponse('<h1>500 Internal Server Error</h1>', status=500, content_type='text/html')

handler404 = custom_handler404
handler500 = custom_handler500