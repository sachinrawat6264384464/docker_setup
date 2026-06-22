import logging
from django.db import connection
from django.conf import settings
from django.http import JsonResponse, Http404
from django_tenants.utils import get_tenant_model, get_tenant_domain_model, get_public_schema_name

logger = logging.getLogger(__name__)

class UnifiedTenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django_tenants.utils import schema_context
        connection.set_schema_to_public()
        TenantModel = get_tenant_model()
        DomainModel = get_tenant_domain_model()
        public_schema_name = get_public_schema_name()
        
        tenant_slug = None
        lookup_domain = None



        # ── 1. DETECTION LOGIC ───────────────────────────────────────────────
        
        # Priority 1: X-Tenant Header
        x_tenant_raw = request.headers.get('X-Tenant', '').strip().split(':')[0]
        if x_tenant_raw:
            parts = x_tenant_raw.split('.')
            if len(parts) >= 2 and parts[-1] == 'localhost':
                tenant_slug = parts[0]
                lookup_domain = x_tenant_raw
            elif x_tenant_raw not in ('localhost', '127.0.0.1', 'public', 'www', ''):
                # If it contains dots, assume it's a full domain. Otherwise, it's a slug.
                if '.' in x_tenant_raw:
                    lookup_domain = x_tenant_raw
                    tenant_slug = x_tenant_raw.split('.')[0]
                else:
                    tenant_slug = x_tenant_raw
                    lookup_domain = f"{tenant_slug}.localhost"

        # Priority 2: Host Header (Subdomains)
        if not tenant_slug:
            host_no_port = request.get_host().split(':')[0]
            parts = host_no_port.split('.')
            if len(parts) >= 2:
                main_domains = ['localhost', 'hoaconnecthub.com', 'www.hoaconnecthub.com', 'api.hoaconnecthub.com', '127.0.0.1', '44.220.64.35', 'public']
                if host_no_port not in main_domains:
                    tenant_slug = parts[0]
                    lookup_domain = host_no_port



        # ── 2. SCHEMA SWITCHING LOGIC ────────────────────────────────────────
        
        tenant = None
        if tenant_slug and lookup_domain:
            logger.info(f"UnifiedTenantMiddleware: Attempting lookup for Slug='{tenant_slug}', Domain='{lookup_domain}'")
            try:
                # Try finding by domain (Standard django-tenants way)
                domain_obj = DomainModel.objects.select_related('tenant').get(domain=lookup_domain)
                tenant = domain_obj.tenant
                logger.info(f"UnifiedTenantMiddleware: FOUND Domain object '{lookup_domain}' linked to tenant '{tenant.schema_name}'")
            except DomainModel.DoesNotExist:
                logger.debug(f"UnifiedTenantMiddleware: Domain '{lookup_domain}' not found. checking schema_name fallback for localhost.")
                
                # FALLBACK for Local Development:
                # If we are on localhost and domain isn't found, try finding by schema_name
                # This helps when the organization exists but the domain record might be missing/different.
                if settings.DEBUG and (lookup_domain.endswith('.localhost') or lookup_domain == 'localhost'):
                    tenant = TenantModel.objects.filter(schema_name=tenant_slug).first()
                    if tenant:
                        logger.debug(f"UnifiedTenantMiddleware: Found tenant via schema_name fallback: {tenant_slug}")
                
                if not tenant:
                    return JsonResponse({
                        'error': "Organization not found",
                        'detail': "The requested organization could not be resolved."
                    }, status=404)

        # Fallback to Public Tenant
        if not tenant:
            tenant = TenantModel.objects.get(schema_name=public_schema_name)


        # Set tenant on connection and request
        logger.info(f"UnifiedTenantMiddleware: Switching to tenant '{tenant.schema_name}' (Domain: {lookup_domain})")
        connection.set_tenant(tenant)
        request.tenant = tenant


        # Set URLCONF
        if tenant.schema_name == public_schema_name:
            request.urlconf = settings.PUBLIC_SCHEMA_URLCONF
        else:
            request.urlconf = settings.ROOT_URLCONF

        # Set search_path
        try:
            with connection.cursor() as cursor:
                if tenant.schema_name == public_schema_name:
                    cursor.execute('SET search_path TO public')
                else:
                    cursor.execute(f"SET search_path TO {tenant.schema_name}, public")
        except Exception as e:
            logger.debug(f"UnifiedTenantMiddleware search_path error: {e}")

        # --- DEBUG LIVE URL ROUTING ---
        try:
            from django.urls import resolve, Resolver404
            resolved_match = resolve(request.path_info, urlconf=request.urlconf)
            logger.info(f"[ROUTE DEBUG] Successfully resolved path '{request.path_info}' using urlconf '{request.urlconf}' to: {resolved_match}")
        except Resolver404 as e:
            logger.warning(f"[ROUTE DEBUG] Path '{request.path_info}' not found (404) using urlconf '{request.urlconf}'")
        except Exception as e:
            logger.error(f"[ROUTE DEBUG] Failed to resolve path '{request.path_info}' using urlconf '{request.urlconf}': {e}")

        return self.get_response(request)

from django.http import HttpResponseServerError

class TenantActiveMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, 'tenant') and request.tenant and request.tenant.schema_name != 'public':
            if not getattr(request.tenant, 'is_active', True):
                return HttpResponseServerError(
                    "500 Internal Server Error: This organization has been suspended."
                )
        return self.get_response(request)

class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        return self.get_response(request)
