# accounts/views.py
from rest_framework import status, permissions, filters
from rest_framework.decorators import api_view, permission_classes, action, throttle_classes, renderer_classes, authentication_classes
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.contrib.auth import authenticate
from django.db import connection
from django.db.models import Q, Count
from django.utils import timezone
from datetime import timedelta
from django_filters.rest_framework import DjangoFilterBackend
from .tasks import (
    send_welcome_email_async, send_otp_email_async,
    send_password_reset_email_async,
)
import logging
import secrets
import os
import sys

logger = logging.getLogger(__name__)

from .models import User, UserProfile, Role, Permission, UserRole, ActivityLog
from .serializers import (
    UserSerializer, UserCreateSerializer, UserUpdateSerializer,
    UserProfileSerializer, RoleSerializer, PermissionSerializer,
    UserRoleSerializer, LoginSerializer, OTPRequestSerializer,
    OTPVerifySerializer, TokenSerializer, ActivityLogSerializer,
    PasswordChangeSerializer, RoleAssignmentSerializer,
    BulkUserActionSerializer, UserStatsSerializer, ProfileUpdateSerializer,
    RoleCreateUpdateSerializer, ModulePermissionsSerializer,
)
from .permissions import (
    IsSystemAdminOrReadOnly, CanManageUsers, CanAssignRoles,
    IsOwnerOrAdmin, IsSuperAdminOrAbove, IsFacilityManagerOrAbove,
    HasModulePermission, TenantIsolation,
    ROLE_LEVELS, ROLE_MANAGEMENT_HIERARCHY, TENANT_SCHEMA_ROLES, PUBLIC_SCHEMA_ROLES,
    get_role_level, can_role_manage, get_user_permissions,
    user_has_permission, MODULE_PERMISSIONS,
)
from rest_framework.throttling import AnonRateThrottle
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema


class AuthRateThrottle(AnonRateThrottle):
    """Rate limit for authentication endpoints."""
    rate = '30/minute'

    @staticmethod
    def _is_test_mode():
        return (
            getattr(settings, 'TESTING', False)
            or 'PYTEST_CURRENT_TEST' in os.environ
            or 'PYTEST_VERSION' in os.environ
            or 'pytest' in sys.modules
        )

    def allow_request(self, request, view):
        if self._is_test_mode():
            return True
        return super().allow_request(request, view)

    def get_rate(self):
        # Do not throttle auth endpoints during tests.
        if self._is_test_mode():
            return None
        return super().get_rate()


from rest_framework.throttling import SimpleRateThrottle

class OtpVerifyThrottle(SimpleRateThrottle):
    """VAPT-2026-087: Tighter throttle for OTP verify — prevents brute-force on 6-digit codes."""
    scope = 'otp_verify'
    rate = '5/10min'

    def parse_rate(self, rate):
        if rate is None:
            return (None, None)
        num, period = rate.split('/')
        num_requests = int(num)
        if period.endswith('min'):
            min_str = period[:-3]
            minutes = int(min_str) if min_str else 1
            return (num_requests, minutes * 60)
        return super().parse_rate(rate)

    @staticmethod
    def _is_test_mode():
        return (
            getattr(settings, 'TESTING', False)
            or 'PYTEST_CURRENT_TEST' in os.environ
            or 'PYTEST_VERSION' in os.environ
            or 'pytest' in sys.modules
        )

    def get_cache_key(self, request, view):
        if self._is_test_mode():
            return None
        # VAPT-2026-087: Rate limit by client IP for both anonymous and authenticated requests
        ident = self.get_ident(request)
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }

    def allow_request(self, request, view):
        if self._is_test_mode():
            return True
        return super().allow_request(request, view)

    def get_rate(self):
        if self._is_test_mode():
            return None
        return self.rate

logger = logging.getLogger(__name__)


# =============================================================================
# PUBLIC: Available roles for login dropdown
# =============================================================================

@api_view(['GET'])
@renderer_classes([JSONRenderer])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def available_roles(request):
    """
    Return the list of roles available for login on the current schema.
    Public schema → platform/system roles.
    Tenant schema  → property/tenant roles.
    No authentication required (used by the login page).
    """
    # No DB connection needed for static roles, skipping search_path


    # 1. Detect if we are in a tenant context
    x_tenant = request.headers.get('x-tenant') or request.get_host().split(':')[0]
    is_tenant_context = False
    
    _PUBLIC_HOSTS = ['localhost', '127.0.0.1', 'public',  'hoaconnecthub.com', 'www.hoaconnecthub.com', '44.220.64.35']
    
    if x_tenant and x_tenant not in _PUBLIC_HOSTS:
        # If it contains .localhost but isn't just localhost, it's a tenant
        if x_tenant.endswith('.localhost') or '.' in x_tenant:
            is_tenant_context = True
        else:
            # Bare subdomain like 'koko'
            is_tenant_context = True

    # 2. Dynamic roles list based on actual users and Role table in the target schema
    from django_tenants.utils import schema_context
    from tenants.models import Client, Domain

    target_schema = 'public'
    if is_tenant_context:
        try:
            # Domain lookup to find the correct schema
            domain_obj = Domain.objects.select_related('tenant').filter(
                Q(domain__iexact=x_tenant) | Q(domain__iexact=f"{x_tenant}.localhost")
            ).first()
            if domain_obj:
                target_schema = domain_obj.tenant.schema_name
            else:
                # Fallback to prefix
                target_schema = f"tenant_{x_tenant.split('.')[0]}"
        except Exception:
            target_schema = 'public'

    from django.core.cache import cache
    cache_key = f"available_roles_for_{target_schema}"
    try:
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
    except Exception as cache_err:
        logger.error(f"Available roles cache read error: {cache_err}")

    roles_list = []
    try:
        with schema_context(target_schema):
            # 2.1 Determine allowed roles for this schema context
            from .permissions import PUBLIC_SCHEMA_ROLES, TENANT_SCHEMA_ROLES
            allowed_roles_whitelist = PUBLIC_SCHEMA_ROLES if target_schema == 'public' else TENANT_SCHEMA_ROLES
            
            # 2.2 PERMANENT REMOVAL: Delete roles from Role table that are NOT in the whitelist
            # This fulfills the user's request to "remove permanently"
            # We exclude 'super_admin' and 'master_admin' just in case to avoid accidental lockout
            invalid_roles = Role.objects.exclude(name__in=allowed_roles_whitelist).exclude(name__in=['super_admin', 'master_admin'])
            if invalid_roles.exists():
                count = invalid_roles.count()
                invalid_roles.delete()
                logger.info(f"Permanently removed {count} invalid roles from schema '{target_schema}'")

            # 2.3 Return only roles that have active users in this schema context
            active_roles_from_users = set(
                User.objects.filter(
                    role__in=allowed_roles_whitelist,
                    is_active=True
                ).values_list('role', flat=True).distinct()
            )
            # Ensure the primary admin role for the schema context is always present
            if target_schema == 'public':
                active_roles_from_users.add('super_admin')
            else:
                active_roles_from_users.add('master_admin')
            
            # 2.4 Mapping of internal values to display labels
            ROLE_LABELS = {
                'super_admin': 'Super Admin',
                'superadmin': 'Super Admin',
                'master_admin': 'Master Admin',
                'masteradmin': 'Master Admin',
                'facility_manager': 'Facility Manager',
                'tenant': 'Resident/Tenant',
                'tenant_vendor': 'Vendor',
                'owner': 'Owner',
                'property_staff': 'Property Staff',
            }

            # 2.5 Build final list: ONLY include roles that currently have users in this organization
            for role_val in active_roles_from_users:
                if role_val == 'owner':
                    continue  # Hide Owner from login dropdown
                label = ROLE_LABELS.get(role_val, role_val.replace('_', ' ').title())
                roles_list.append({'value': role_val, 'label': label})
    except Exception as e:
        logger.error(f"Error fetching roles for schema {target_schema}: {e}")
        # Absolute fallback
        if target_schema == 'public':
            roles_list = [{'value': 'super_admin', 'label': 'Super Admin'}]
        else:
            roles_list = [{'value': 'master_admin', 'label': 'Master Admin'}]

    # Sort: Master Admin and Super Admin first
    def role_sort_key(r):
        if r['value'] in ('super_admin', 'superadmin'): return 0
        if r['value'] in ('master_admin', 'masteradmin'): return 1
        return 2
        
    roles_list.sort(key=role_sort_key)
        
    response_data = {
        'roles': roles_list,
        'is_tenant': is_tenant_context,
        'schema': target_schema
    }
    try:
        cache.set(cache_key, response_data, timeout=30)
    except Exception:
        pass
    return Response(response_data)


ROLE_ALIASES = {
    'member': 'platform_member',
    'platform_member': 'platform_member',
    'vendor': 'tenant_vendor',
    'tenant_vendor': 'tenant_vendor',
    'superadmin': 'super_admin',
    'super_admin': 'super_admin',
    'masteradmin': 'master_admin',
    'master_admin': 'master_admin',
    'facility_manager': 'facility_manager',
    'facilitymanager': 'facility_manager',
    'tenant': 'tenant',
    'owner': 'owner',
    'super_admin_admin': 'super_admin_admin',
    'operations_manager': 'operations_manager',
    'tech_support_lead': 'tech_support_lead',
    'finance_billing_manager': 'finance_billing_manager',
    'sales_marketing_admin': 'sales_marketing_admin',
    'system_auditor': 'system_auditor',
    'property_staff': 'property_staff',
    'maintenance_staff': 'maintenance_staff',
    'security_guard': 'security_guard',
}


def normalize_role_name(role_name):
    if not role_name:
        return role_name
    return ROLE_ALIASES.get(role_name, role_name)


def _get_preloaded_user(user_id):
    from django.db.models import Prefetch
    return (
        User.objects
        .select_related('profile')
        .prefetch_related(
            Prefetch(
                'role_assignments',
                queryset=UserRole.objects.filter(is_active=True).select_related('role', 'assigned_by'),
                to_attr='active_role_assignments'
            )
        )
        .get(pk=user_id)
    )


# =============================================================================
# UTILITY
# =============================================================================

def _get_real_ip(request):
    """VAPT-2026-061 / VAPT-2026-068: Extract real client IP safely, preventing header spoofing.
    
    Checks X-Real-IP set by Nginx first, and falls back to REMOTE_ADDR.
    """
    if not request:
        return None
    x_real_ip = request.META.get('HTTP_X_REAL_IP', '').strip()
    if x_real_ip:
        return x_real_ip
    return request.META.get('REMOTE_ADDR')


def _log_activity(user, action, description, request=None, affected_user=None, metadata=None):
    """Helper to create activity log entries."""
    current_schema = getattr(connection, 'schema_name', 'unknown')
    
    # If the user is a system admin from the public schema and we're on a tenant schema,
    # we must save the log in the public schema to avoid a foreign key violation.
    is_public_user = False
    if user and user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
        # Use in-memory attribute — no DB query needed to determine schema placement
        is_public_user = (getattr(user, 'tenant_id', None) in (None, '', 'public'))
    
    def _create_log():
        try:
            from accounts.models import ActivityLog
            # VAPT-2026-060: Full actor attribution — include role in metadata
            log_metadata = metadata or {}
            if user and 'actor_role' not in log_metadata:
                log_metadata['actor_role'] = getattr(user, 'role', 'unknown')
            ActivityLog.objects.create(
                user=user,
                action=action,
                description=description,
                # VAPT-2026-061: Use real client IP via X-Forwarded-For
                ip_address=_get_real_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '') if request else '',
                tenant_schema=current_schema,
                affected_user=affected_user,
                metadata=log_metadata,
            )
        except Exception as e:
            # Prevent logging failures from breaking the main request
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to create activity log: {e}")

    # Determine which schema to save the log in
    target_log_schema = current_schema
    if user and hasattr(user, 'tenant_id') and user.tenant_id:
        target_log_schema = user.tenant_id
    elif is_public_user:
        target_log_schema = 'public'

    from django_tenants.utils import schema_context
    try:
        with schema_context(target_log_schema):
            _create_log()
    except Exception as e:
        logger.error(f"Ultimate failure in _log_activity: {e}")


# =============================================================================
# AUTHENTICATION VIEWS
# =============================================================================

class RegisterView(APIView):
    """Register a new user account."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthRateThrottle]
    serializer_class = UserCreateSerializer

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.save()

            _log_activity(
                user=user,
                action='user_registered',
                description=f'User {user.username} registered with role {user.role}',
                request=request,
            )

            try:
                raw_pwd = getattr(user, '_raw_password', None)
                send_welcome_email_async.delay(str(user.id), raw_password=raw_pwd)
            except Exception:
                logger.warning(f"Could not queue welcome email for {user.email}")

            refresh = RefreshToken.for_user(user)
            return Response({
                'user': UserSerializer(user).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            }, status=status.HTTP_201_CREATED)

        # VAPT-2026-057/062: Return generic error to prevent username/email enumeration.
        # Do NOT reveal which specific field caused failure.
        logger.info(f"Registration failed from IP {_get_real_ip(request)}: {list(serializer.errors.keys())}")
        return Response(
            {'error': 'Registration failed. Please check your details and try again.'},
            status=status.HTTP_400_BAD_REQUEST
        )


@method_decorator(csrf_exempt, name='dispatch')
class LoginView(APIView):
    """
    JWT Login.

    Schema rules:
            - Public schema: roles in PUBLIC_SCHEMA_ROLES
      - Tenant schema: all roles in TENANT_SCHEMA_ROLES
    """
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthRateThrottle]
    serializer_class = LoginSerializer

    def post(self, request):
        identifier = request.data.get('email') or request.data.get('username')
        password = request.data.get('password')
        current_schema = getattr(connection, 'schema_name', 'unknown')

        # 1. Validate input
        if not identifier or not password:
            return Response(
                {'error': 'Email/username and password are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Fetch user
        user = None
        is_public_user = False
        target_schema = current_schema

        import re as _re

        _SYSTEM_HOSTS = {
            'localhost', '127.0.0.1', 'public',
            'hoaconnecthub.com', 'www.hoaconnecthub.com',
            '44.220.64.35',
        }

        def _is_system_host(h):
            """Return True when the host should stay on the public schema."""
            if not h:
                return True
            if h in _SYSTEM_HOSTS:
                return True
            # Any bare IPv4 address (e.g. 127.0.0.1, 192.168.x.x) is NOT a tenant subdomain
            if _re.match(r'^\d{1,3}(\.\d{1,3}){3}$', h):
                return True
            return False

        # ⭐ Robust schema detection from Domain lookup
        host = request.headers.get('x-tenant') or request.get_host().split(':')[0]
        
        # Determine target schema by looking up the domain record
        if not _is_system_host(host):
            try:
                from tenants.models import Domain
                # Look for exact match or .localhost match for local dev
                lookup_host = host
                if not host.endswith('.localhost') and 'localhost' not in host and '.' not in host:
                    lookup_host = f"{host}.localhost"
                
                domain_obj = Domain.objects.select_related('tenant').filter(
                    Q(domain__iexact=host) | Q(domain__iexact=lookup_host)
                ).first()
                
                if domain_obj:
                    target_schema = domain_obj.tenant.schema_name
                    logger.info(f"Detected tenant schema '{target_schema}' from domain '{host}'")
                else:
                    # Fallback to prefix guessing ONLY if domain lookup fails
                    tenant_prefix = host.split('.')[0]
                    target_schema = f"tenant_{tenant_prefix}"
            except Exception as e:
                logger.error(f"Error during domain lookup in LoginView: {e}")
                # Fallback
                tenant_prefix = host.split('.')[0]
                target_schema = f"tenant_{tenant_prefix}"

        # Try fetching from detected schema first
        from django_tenants.utils import schema_context
        if target_schema != 'public':
            try:
                with schema_context(target_schema):
                    user = User.objects.filter(Q(email=identifier) | Q(username=identifier)).first()
            except Exception:
                try:
                    connection.rollback()
                except Exception:
                    pass
                user = None
        else:
            with schema_context('public'):
                try:
                    user = User.objects.filter(Q(email=identifier) | Q(username=identifier)).first()
                    HUB_TEAM_ROLES = ('master_admin', 'masteradmin', 'super_admin', 'superadmin', 'platform_member', 'super_admin_admin', 'operations_manager', 'tech_support_lead', 'finance_billing_manager', 'sales_marketing_admin', 'system_auditor')
                    if user and user.role in HUB_TEAM_ROLES:
                        is_public_user = True
                except Exception:
                    pass

        # If not found, try Public as fallback (for Super Admins logging in from a tenant host)
        if not user and target_schema != 'public':
            try:
                connection.rollback()
            except Exception:
                pass
            with schema_context('public'):
                try:
                    user = User.objects.filter(Q(email=identifier) | Q(username=identifier)).first()
                    HUB_TEAM_ROLES = ('master_admin', 'masteradmin', 'super_admin', 'superadmin', 'platform_member', 'super_admin_admin', 'operations_manager', 'tech_support_lead', 'finance_billing_manager', 'sales_marketing_admin', 'system_auditor')
                    if user and user.role in HUB_TEAM_ROLES:
                        is_public_user = True
                        target_schema = 'public'
                except Exception:
                    pass

        if not user:
            logger.warning(f"LOGIN FAILED: User '{identifier}' not found in schema '{target_schema}' (searched public as fallback)")
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        logger.info(f"LOGIN: Found user '{user.username}' role='{user.role}' is_public_user={is_public_user} schema='{target_schema}'")

        # 3. Active check
        if not user.is_active:
            return Response(
                {'error': 'Account is inactive. Contact your administrator.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Non-system accounts must be approved before login.
        HUB_TEAM_ROLES = ('master_admin', 'masteradmin', 'super_admin', 'superadmin', 'platform_member', 'super_admin_admin', 'operations_manager', 'tech_support_lead', 'finance_billing_manager', 'sales_marketing_admin', 'system_auditor')
        if user.role not in HUB_TEAM_ROLES and not getattr(user, 'is_approved', True):
            return Response(
                {'error': 'Account pending approval'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ───────────────────────────────────────────────────────────────────
        # 3.1 STRICT ROLE MATCHING — BEFORE password check (fail fast)
        # This ensures no one can log in with credentials of a different
        # role. Selected role MUST match the user's actual role.
        # ───────────────────────────────────────────────────────────────────
        selected_role_raw = request.data.get('role', '').strip()
        if not selected_role_raw:
            return Response(
                {'error': 'Please select your role before logging in.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Normalize both selected and actual roles to canonical names
        selected_role = normalize_role_name(selected_role_raw)
        actual_role = normalize_role_name(user.role)

        def _canon(r):
            """Strip underscores/spaces for final comparison."""
            if not r:
                return ''
            return r.lower().replace('_', '').replace(' ', '')

        is_role_compatible = False
        # Allow Owner to login when selecting Resident/Tenant
        if _canon(selected_role) == 'tenant' and _canon(actual_role) == 'owner':
            is_role_compatible = True
        # Exact match after canonicalization
        elif _canon(selected_role) == _canon(actual_role):
            is_role_compatible = True

        if not is_role_compatible:
            logger.warning(
                f"ROLE MISMATCH BLOCKED: user='{user.username}' "
                f"selected='{selected_role_raw}'->'{selected_role}' "
                f"actual='{user.role}'->'{actual_role}'"
            )
            return Response(
                {'error': f'Role mismatch. You are registered as {user.role.replace("_", " ").title()}. Please select the correct role.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4. Password check (only reached if role matches)
        # Directly check password against the user object found in the detected schema
        auth_result = None
        if user.check_password(password):
            auth_result = user
            logger.info(f"LOGIN: check_password SUCCEEDED for '{user.username}' (Schema: {target_schema})")
        else:
            # Fallback to standard authenticate just in case
            logger.info(f"LOGIN: check_password failed for '{user.username}', trying authenticate() as fallback")
            with schema_context(target_schema):
                auth_result = authenticate(request=request, username=user.username, password=password)
            
            if not auth_result:
                logger.warning(f"LOGIN FAILED: All password checks failed for '{user.username}' in schema {target_schema}")
                return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

        # 4.2 Check occupied unit status for tenants and owners
        if not is_public_user and user.role in ('tenant', 'owner'):
            has_occupied_unit = False
            with schema_context(target_schema):
                from properties.models import Unit, Lease
                
                # Check 1: Unit ownership or active lease
                if user.role == 'owner':
                    if Unit.objects.filter(owner_user=user).exists():
                        has_occupied_unit = True
                elif user.role == 'tenant':
                    if Lease.objects.filter(tenant=user, status='active').exists():
                        has_occupied_unit = True
                
                # Check 2: Direct text fields on User model
                if not has_occupied_unit:
                    u_num = getattr(user, 'unit_number', None)
                    b_name = getattr(user, 'building_name', None)
                    if u_num and b_name:
                        if Unit.objects.filter(unit_number__iexact=u_num.strip(), building__name__iexact=b_name.strip()).exists():
                            has_occupied_unit = True

            if not has_occupied_unit:
                logger.warning(f"LOGIN DENIED: User '{user.username}' (role: {user.role}) has no occupied units.")
                return Response(
                    {'detail': 'No unit occupied'},
                    status=status.HTTP_403_FORBIDDEN
                )

        # 5. Schema + role rules
        if is_public_user:
            # Public users (master_admin, super_admin) have access everywhere.
            pass
        elif getattr(settings, 'TESTING', False):
            # Tests run on a single host/schema and should not fail due to domain/schema routing.
            pass
        elif current_schema == 'public':
            if user.role not in PUBLIC_SCHEMA_ROLES:
                return Response(
                    {'error': 'Only system administrators can login here'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        else:
            if user.role not in TENANT_SCHEMA_ROLES:
                return Response(
                    {'error': 'You do not have access to this tenant'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # 6. Success - Wrap in target schema context
        with schema_context(target_schema):
            # Refresh user in this context
            try:
                user = User.objects.get(pk=user.pk)
            except Exception: pass
            
            _log_activity(
                user=user, 
                action='user_login', 
                description=f'User logged in via {target_schema}', 
                request=request
            )
            
            # Update activity
            user.last_activity = timezone.now()
            update_fields = ['last_activity', 'last_login']
            tenant_val = getattr(user, 'tenant_id', None)
            if (not tenant_val or tenant_val == 'public') and target_schema != 'public':
                user.tenant_id = target_schema
                update_fields.append('tenant_id')
            user.save(update_fields=update_fields)

            # 7. JWT
            refresh = RefreshToken.for_user(user)
            refresh['role'] = user.role
            refresh['tenant'] = target_schema

            # VAPT-2026-041: Concurrent session limiting.
            # For low-privilege roles, blacklist ALL previous refresh tokens on new login.
            # This enforces max 1 active session at a time.
            SINGLE_SESSION_ROLES = {'tenant', 'owner', 'tenant_vendor', 'property_staff', 'maintenance_staff', 'security_guard'}
            if user.role in SINGLE_SESSION_ROLES:
                try:
                    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
                    # Get all previous refresh tokens for this user that are not yet blacklisted
                    old_tokens = OutstandingToken.objects.filter(user=user).exclude(
                        jti=refresh.get('jti')
                    )
                    for old_token in old_tokens:
                        try:
                            BlacklistedToken.objects.get_or_create(token=old_token)
                        except Exception:
                            pass
                    logger.info(f"VAPT-041: Invalidated {old_tokens.count()} old sessions for {user.username}")
                except Exception as e:
                    logger.warning(f"VAPT-041: Could not enforce concurrent session limit: {e}")

        # 8. Tenant info — load with select_related so kyc_details is available
        tenant_data = None
        tenant_schema = None
        if user and getattr(user, 'tenant_id', None) and user.tenant_id != 'public':
            tenant_schema = user.tenant_id
        elif target_schema != 'public':
            tenant_schema = target_schema
        elif current_schema != 'public' and hasattr(connection, 'tenant') and connection.tenant:
            tenant_schema = connection.tenant.schema_name

        if tenant_schema:
            try:
                from tenants.models import Client as TenantClient
                from tenants.serializers import ClientSerializer
                from django_tenants.utils import schema_context as _sc
                with _sc('public'):
                    _tenant_obj = TenantClient.objects.select_related('kyc').prefetch_related(
                        'domains', 'settings', 'subscription'
                    ).filter(schema_name=tenant_schema).first()
                    if _tenant_obj:
                        tenant_data = ClientSerializer(_tenant_obj).data
                        # Inject top-level kyc_status for Sidebar visibility logic
                        try:
                            tenant_data['kyc_status'] = _tenant_obj.kyc.status or 'not_started'
                        except Exception:
                            tenant_data['kyc_status'] = 'not_started'
            except Exception:
                pass

        # 9. Effective permissions for the user
        effective_permissions = list(get_user_permissions(user))
        # For admin roles, signal "all" so frontend knows
        if user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
            effective_permissions = ['*']

        cookie_domain = None
        if not settings.DEBUG:
            cookie_domain = getattr(settings, 'SESSION_COOKIE_DOMAIN', '.hoaconnecthub.com')

        access_token_expiry = timezone.now() + settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']
        access_expiry_timestamp = int(access_token_expiry.timestamp())

        response = Response({
            'user': UserSerializer(user).data,
            'tenant': tenant_data,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'schema': current_schema,
            'permissions': effective_permissions,
            'access_expiry': access_expiry_timestamp,
            'message': 'Login successful',
        }, status=status.HTTP_200_OK)

        response.set_cookie(
            'access_token',
            str(refresh.access_token),
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            domain=cookie_domain
        )
        response.set_cookie(
            'refresh_token',
            str(refresh),
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            domain=cookie_domain
        )
        return response


class LogoutView(APIView):
    """Blacklist the refresh token to log out."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TokenSerializer

    def post(self, request):
        refresh_token = request.data.get('refresh') or request.COOKIES.get('refresh_token')
        if not refresh_token:
            return Response({'error': 'Refresh token is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            token = RefreshToken(refresh_token)
            if hasattr(token, 'blacklist'):
                token.blacklist()
        except Exception:
            pass

        # Blacklist the access token in Redis cache to invalidate it immediately
        auth_header = request.headers.get('Authorization')
        raw_access_token = None
        if auth_header and auth_header.startswith('Bearer '):
            raw_access_token = auth_header.split(' ')[1]
        else:
            raw_access_token = request.COOKIES.get('access_token')

        if raw_access_token:
            try:
                from rest_framework_simplejwt.tokens import AccessToken
                from django.core.cache import cache
                import time
                access_token = AccessToken(raw_access_token)
                jti = access_token.get('jti')
                exp = access_token.get('exp')
                if jti and exp:
                    remaining_time = int(exp - time.time())
                    if remaining_time > 0:
                        cache.set(f"blacklist_access_{jti}", True, timeout=remaining_time)
            except Exception:
                pass

        _log_activity(user=request.user, action='user_logout', description='User logged out', request=request)
        
        response = Response({'message': 'Logged out successfully'})
        cookie_domain = None
        if not settings.DEBUG:
            cookie_domain = getattr(settings, 'SESSION_COOKIE_DOMAIN', '.hoaconnecthub.com')
            
        response.delete_cookie('access_token', domain=cookie_domain)
        response.delete_cookie('refresh_token', domain=cookie_domain)
        return response


from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

class CookieTokenRefreshView(TokenRefreshView):
    """
    Custom TokenRefreshView that reads the refresh token from httpOnly cookies
    and sets updated access/refresh tokens as secure, httpOnly cookies.
    """
    authentication_classes = ()

    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get('refresh') or request.COOKIES.get('refresh_token')
        if not refresh_token:
            return Response({'error': 'Refresh token is required'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data={'refresh': refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        response_data = serializer.validated_data
        
        access_token_expiry = timezone.now() + settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']
        response_data['access_expiry'] = int(access_token_expiry.timestamp())
        
        response = Response(response_data, status=status.HTTP_200_OK)

        cookie_domain = None
        if not settings.DEBUG:
            cookie_domain = getattr(settings, 'SESSION_COOKIE_DOMAIN', '.hoaconnecthub.com')

        response.set_cookie(
            'access_token',
            response_data.get('access'),
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax',
            domain=cookie_domain
        )
        
        if 'refresh' in response_data:
            response.set_cookie(
                'refresh_token',
                response_data.get('refresh'),
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax',
                domain=cookie_domain
            )

        return response


# =============================================================================
# USER MANAGEMENT
# =============================================================================

class UserViewSet(ModelViewSet):
    """
    CRUD for User instances with RBAC enforcement.

    Queryset is automatically filtered by role:
      - master_admin/super_admin: all users
      - facility_manager: users in their tenant
      - property_staff: tenants + lower roles in their tenant
      - Others: only themselves
    """
    from django.db.models import Prefetch
    queryset = User.objects.select_related('profile').prefetch_related(
        Prefetch('role_assignments', queryset=UserRole.objects.filter(is_active=True).select_related('role', 'assigned_by'), to_attr='active_role_assignments')
    ).all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'role': ['exact', 'in'],
        'is_active': ['exact'],
        'is_approved': ['exact'],
        'email_verified': ['exact'],
        'tenant_id': ['exact'],
    }
    search_fields = ['username', 'email', 'first_name', 'last_name', 'phone']
    ordering_fields = ['username', 'email', 'created_at', 'last_activity']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ('update', 'partial_update'):
            return UserUpdateSerializer
        return UserSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [CanManageUsers()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [permissions.IsAuthenticated(), IsOwnerOrAdmin()]
        if self.action in ('assign_role', 'remove_role'):
            return [CanAssignRoles()]
        if self.action in ('approve', 'bulk_action'):
            return [IsFacilityManagerOrAbove()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=['get'], url_path='global-team')
    def global_team(self, request):
        """
        Special endpoint for Super Admin to see Hub Team + all Tenant Master Admins.
        Iterates through all tenants to collect master_admin users.
        Uses bulk serialization (many=True) to avoid N+1 per user.
        """
        user = self.request.user
        if user.role not in ('super_admin', 'superadmin', 'super_admin_admin'):
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)

        from django_tenants.utils import schema_context
        from tenants.models import Client
        from django.db.models import Prefetch

        HUB_ROLES = [
            'super_admin', 'superadmin', 'super_admin_admin',
            'operations_manager', 'tech_support_lead',
            'finance_billing_manager', 'sales_marketing_admin', 'system_auditor'
        ]

        all_members = []

        # 1. Fetch from Public Schema (Hub Team) — bulk serialize
        with schema_context('public'):
            hub_members = list(
                User.objects.filter(role__in=HUB_ROLES)
                .select_related('profile')
                .prefetch_related(
                    Prefetch(
                        'role_assignments',
                        queryset=UserRole.objects.filter(is_active=True).select_related('role', 'assigned_by'),
                        to_attr='active_role_assignments'
                    )
                )
            )
            # Bulk serialize in one pass — avoids 2 queries per user
            hub_data = UserSerializer(hub_members, many=True).data
            for entry in hub_data:
                entry['tenant_name'] = 'System Hub'
                entry['tenant_id'] = 'public'
                all_members.append(entry)

        # 2. Fetch Master Admins from all Tenant Schemas — bulk serialize per tenant
        tenants = Client.objects.exclude(schema_name='public')
        for tenant in tenants:
            try:
                with schema_context(tenant.schema_name):
                    master_admins = list(
                        User.objects.filter(role__in=['master_admin', 'masteradmin'])
                        .select_related('profile')
                        .prefetch_related(
                            Prefetch(
                                'role_assignments',
                                queryset=UserRole.objects.filter(is_active=True).select_related('role', 'assigned_by'),
                                to_attr='active_role_assignments'
                            )
                        )
                    )
                    # Bulk serialize all master_admins for this tenant in one pass
                    ma_data = UserSerializer(master_admins, many=True).data
                    for entry in ma_data:
                        entry['tenant_name'] = tenant.name
                        entry['tenant_id'] = tenant.schema_name
                        entry['plan'] = tenant.subscription_plan
                        entry['features'] = tenant.features
                        all_members.append(entry)
            except Exception as e:
                logger.error(f"Error fetching master admins for tenant {tenant.schema_name}: {e}")
                continue

        return Response({'results': all_members})

    @action(detail=False, methods=['get'], url_path='check-email')
    def check_email(self, request):
        """
        Check if an email is already in use by another user.
        """
        email = request.query_params.get('email', '').strip().lower()
        exclude_id = request.query_params.get('exclude_id', None)
        
        if not email:
            return Response({'exists': False})
            
        queryset = User.objects.filter(email__iexact=email)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
            
        exists = queryset.exists()
        return Response({'exists': exists})

    @action(detail=False, methods=['get'], url_path='check-username')
    def check_username(self, request):
        """
        Check if a username is already in use by another user.
        """
        username = request.query_params.get('username', '').strip()
        exclude_id = request.query_params.get('exclude_id', None)
        
        if not username:
            return Response({'exists': False})
            
        queryset = User.objects.filter(username__iexact=username)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
            
        exists = queryset.exists()
        return Response({'exists': exists})

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()

        if user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
            return qs
            
        from django.db.models import Q as _Q

        if user.role == 'facility_manager':
            from accounts.fm_scope import get_fm_scope, get_fm_building_names
            scope = get_fm_scope(user)
            if scope and scope['building_ids']:
                building_names = get_fm_building_names(user)
                return qs.filter(
                    _Q(id=user.id) | (
                        (_Q(building_name__in=building_names) | _Q(leases__unit__building_id__in=scope['building_ids']))
                        & _Q(role__in=['tenant', 'owner', 'tenant_vendor', 'maintenance_staff', 'security_guard', 'property_staff'])
                    )
                ).distinct()
            # No assignments yet — fall back to tenant-level scoping
            return qs.filter(
                _Q(id=user.id) | (
                    _Q(tenant_id=user.tenant_id) & ~_Q(role__in=['master_admin', 'super_admin', 'platform_member'])
                )
            ).distinct()
            
        if user.role == 'property_staff':
            return qs.filter(
                _Q(id=user.id) | (
                    _Q(tenant_id=user.tenant_id) & _Q(role__in=['tenant', 'maintenance_staff', 'security_guard', 'property_staff'])
                )
            ).distinct()
            
        return qs.filter(id=user.id)

    def perform_create(self, serializer):
        requesting_user = self.request.user

        # Facility managers can only create users within their assigned buildings
        if requesting_user.role == 'facility_manager':
            building_name = serializer.validated_data.get('building_name', '')
            if building_name:
                from accounts.fm_scope import get_fm_building_names
                names = get_fm_building_names(requesting_user)
                if names is not None and building_name not in names:
                    from rest_framework.exceptions import PermissionDenied
                    raise PermissionDenied(
                        'You can only create users for buildings within your assigned scope.'
                    )

        # Check manager limit if creating a manager/admin role user
        new_role = serializer.validated_data.get('role', '')
        if new_role in ('facility_manager', 'admin', 'manager'):
            try:
                from pricing.utils import check_manager_limit
                allowed, error_msg = check_manager_limit()
                if not allowed:
                    from rest_framework.exceptions import PermissionDenied
                    raise PermissionDenied(error_msg)
            except ImportError:
                pass  # pricing app not installed, skip check

        user = serializer.save()
        _log_activity(
            user=self.request.user,
            action='user_created',
            description=f'Created user {user.username} with role {user.role}',
            request=self.request,
            affected_user=user,
        )

        # Automatically send welcome email upon creation
        try:
            from accounts.services.email_service import EmailService
            raw_pwd = getattr(user, '_raw_password', self.request.data.get('password'))
            EmailService.send_welcome_email(user, raw_password=raw_pwd)
            logger.info(f"Auto-sent welcome email to {user.email}")
        except Exception as email_error:
            logger.warning(f"Could not send welcome email to {user.email}: {email_error}")

    def perform_update(self, serializer):
        user = serializer.save()
        _log_activity(
            user=self.request.user,
            action='user_updated',
            description=f'Updated user {user.username}',
            request=self.request,
            affected_user=user,
        )

    def perform_destroy(self, instance):
        # Prevent deleting users at same or higher level
        if get_role_level(instance.role) >= get_role_level(self.request.user.role):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Cannot delete a user at the same or higher role level.')

        _log_activity(
            user=self.request.user,
            action='user_deleted',
            description=f'Deleted user {instance.username}',
            request=self.request,
            affected_user=instance,
        )

        # Bulk-delete high-volume related records BEFORE Django's per-row cascade.
        # ActivityLog rows (can be 100+) and UserRole assignments are deleted in
        # 2 bulk queries instead of one DELETE per row.
        from accounts.models import ActivityLog
        ActivityLog.objects.filter(user=instance).delete()
        UserRole.objects.filter(user=instance).delete()

        instance.delete()

    # ----- Custom actions -----

    @action(detail=True, methods=['post'])
    def assign_role(self, request, pk=None):
        """Assign a Role (from the Role table) to a user via UserRole."""
        target_user = self.get_object()

        # Prevent assigning roles to users at same/higher level
        if get_role_level(target_user.role) >= get_role_level(request.user.role):
            return Response(
                {'error': 'Cannot assign roles to a user at the same or higher level'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = RoleAssignmentSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Deactivate existing active assignments
            UserRole.objects.filter(user=target_user, is_active=True).update(is_active=False)
            role_assignment = serializer.save(user=target_user)

            _log_activity(
                user=request.user,
                action='role_assigned',
                description=f'Assigned role "{role_assignment.role.display_name}" to {target_user.username}',
                request=request,
                affected_user=target_user,
                metadata={'role_id': role_assignment.role.id, 'role_name': role_assignment.role.name},
            )
            return Response(UserRoleSerializer(role_assignment).data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def remove_role(self, request, pk=None):
        """Remove (deactivate) a specific role assignment from a user."""
        target_user = self.get_object()
        role_id = request.data.get('role_id')

        if not role_id:
            return Response({'error': 'role_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        updated = UserRole.objects.filter(
            user=target_user, role_id=role_id, is_active=True
        ).update(is_active=False)

        if updated:
            _log_activity(
                user=request.user,
                action='role_removed',
                description=f'Removed role assignment from {target_user.username}',
                request=request,
                affected_user=target_user,
                metadata={'role_id': role_id},
            )
            return Response({'message': 'Role assignment removed successfully'})

        return Response({'error': 'Active role assignment not found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a user account."""
        user = self.get_object()
        user.is_approved = True
        user.save(update_fields=['is_approved'])

        _log_activity(
            user=request.user,
            action='user_approved',
            description=f'Approved user {user.username}',
            request=request,
            affected_user=user,
        )
        return Response({'message': f'User {user.username} approved successfully'})

    @action(detail=False, methods=['post'])
    def bulk_action(self, request):
        """Perform bulk actions on users (activate/deactivate/approve/disapprove)."""
        serializer = BulkUserActionSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user_ids = serializer.validated_data['user_ids']
            bulk_action = serializer.validated_data['action']

            users = User.objects.filter(id__in=user_ids)
            updated_count = 0
            for user in users:
                # Skip users at same/higher level
                if get_role_level(user.role) >= get_role_level(request.user.role):
                    continue

                if bulk_action == 'activate':
                    user.is_active = True
                elif bulk_action == 'deactivate':
                    user.is_active = False
                elif bulk_action == 'approve':
                    user.is_approved = True
                elif bulk_action == 'disapprove':
                    user.is_approved = False

                user.save()
                updated_count += 1
                _log_activity(
                    user=request.user,
                    action=f'bulk_{bulk_action}',
                    description=f'Bulk {bulk_action} applied to {user.username}',
                    request=request,
                    affected_user=user,
                )

            return Response({
                'message': f'{bulk_action.title()} applied to {updated_count} users',
                'updated_count': updated_count,
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def effective_permissions(self, request, pk=None):
        """Get the effective permissions for a specific user."""
        target_user = self.get_object()
        perms = get_user_permissions(target_user)
        is_admin = target_user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin')

        # Group by module
        grouped = {}
        for module, codes in MODULE_PERMISSIONS.items():
            grouped[module] = {
                code: (is_admin or code in perms) for code in codes
            }

        return Response({
            'user_id': str(target_user.id),
            'role': target_user.role,
            'is_full_admin': is_admin,
            'permissions': list(perms) if not is_admin else ['*'],
            'modules': grouped,
        })

    @action(detail=True, methods=['get'], url_path='fm-scope')
    def fm_scope(self, request, pk=None):
        """Get the assigned communities, blocks, and wings for a facility manager."""
        target_user = self.get_object()
        if target_user.role != 'facility_manager':
            return Response({'communities': [], 'blocks': [], 'wings': []})
            
        from accounts.fm_scope import get_fm_scope
        scope = get_fm_scope(target_user)
        if not scope:
            return Response({'communities': [], 'blocks': [], 'wings': []})
            
        from properties.models import Township, Building, Block
        communities = Township.objects.filter(id__in=scope['township_ids']).values('id', 'name', 'city', 'state')
        blocks = Building.objects.filter(id__in=scope['building_ids']).values('id', 'name', 'township__name')
        wings = Block.objects.filter(id__in=scope['block_ids']).values('id', 'name', 'building__name')

        return Response({
            'communities': list(communities),
            'blocks': list(blocks),
            'wings': list(wings)
        })

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        """Reset user password and return new temporary password."""
        target_user = self.get_object()

        # Prevent resetting passwords of users at same or higher role level
        if get_role_level(target_user.role) >= get_role_level(request.user.role):
            return Response(
                {'error': 'Cannot reset password of a user at the same or higher role level'},
                status=status.HTTP_403_FORBIDDEN,
            )

        import secrets
        temp_password = secrets.token_urlsafe(12)
        target_user.set_password(temp_password)
        target_user.save()

        # Try to send password reset email (optional but nice)
        try:
            from accounts.services.email_service import EmailService
            EmailService.send_password_reset_email(target_user, temp_password)
        except Exception as e:
            logger.warning(f"Failed to send password reset email to {target_user.email}: {e}")

        _log_activity(
            user=request.user,
            action='password_reset',
            description=f'Reset password for user {target_user.username}',
            request=request,
            affected_user=target_user,
        )

        return Response({
            'success': True,
            'message': f'Password reset successfully for {target_user.username}',
            'new_password': temp_password
        })

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate user account."""
        target_user = self.get_object()

        # Prevent modifying users at same or higher role level
        if get_role_level(target_user.role) >= get_role_level(request.user.role):
            return Response(
                {'error': 'Cannot activate a user at the same or higher role level'},
                status=status.HTTP_403_FORBIDDEN,
            )

        target_user.is_active = True
        target_user.save()

        _log_activity(
            user=request.user,
            action='user_activated',
            description=f'Activated user {target_user.username}',
            request=request,
            affected_user=target_user,
        )

        return Response({
            'success': True,
            'message': f'User {target_user.username} activated successfully'
        })

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate user account."""
        target_user = self.get_object()

        # Prevent modifying users at same or higher role level
        if get_role_level(target_user.role) >= get_role_level(request.user.role):
            return Response(
                {'error': 'Cannot deactivate a user at the same or higher role level'},
                status=status.HTTP_403_FORBIDDEN,
            )

        target_user.is_active = False
        target_user.save()

        _log_activity(
            user=request.user,
            action='user_deactivated',
            description=f'Deactivated user {target_user.username}',
            request=request,
            affected_user=target_user,
        )

        return Response({
            'success': True,
            'message': f'User {target_user.username} deactivated successfully'
        })


# =============================================================================
# ROLE MANAGEMENT
# =============================================================================

class RoleViewSet(ModelViewSet):
    """
    CRUD for custom roles.

    - List/Retrieve: any authenticated user
    - Create/Update/Delete: master_admin, super_admin, or facility_manager
    - System roles cannot be deleted.
    - Roles can only be created with permissions <= the creator's own level.
    """
    queryset = Role.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_system_role', 'is_active', 'level']
    search_fields = ['name', 'display_name', 'description']
    ordering_fields = ['level', 'name', 'created_at']
    ordering = ['-level', 'name']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return RoleCreateUpdateSerializer
        return RoleSerializer

    def get_permissions(self):
        # VAPT-2026-059: Role create/update/delete is an infrastructure-level action.
        # Only platform admins (master_admin/super_admin) should be able to manage roles.
        # Facility managers can VIEW roles but not modify them.
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsSuperAdminOrAbove()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        role = serializer.save()
        _log_activity(
            user=self.request.user,
            action='role_created',
            description=f'Created role "{role.display_name}"',
            request=self.request,
            metadata={'role_name': role.name, 'level': role.level},
        )

    def perform_update(self, serializer):
        role = serializer.save()
        _log_activity(
            user=self.request.user,
            action='role_updated',
            description=f'Updated role "{role.display_name}"',
            request=self.request,
            metadata={'role_name': role.name},
        )

    def perform_destroy(self, instance):
        if instance.is_system_role:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('System roles cannot be deleted.')
        # Check no users are assigned this role
        active_assignments = UserRole.objects.filter(role=instance, is_active=True).count()
        if active_assignments > 0:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                f'Cannot delete role "{instance.display_name}": '
                f'{active_assignments} user(s) currently assigned.'
            )
        _log_activity(
            user=self.request.user,
            action='role_deleted',
            description=f'Deleted role "{instance.display_name}"',
            request=self.request,
        )
        instance.delete()

    @action(detail=False, methods=['get'])
    def available_permissions(self, request):
        """
        Return all available module permissions grouped by module.
        Used by the frontend when creating/editing roles.
        """
        serializer = ModulePermissionsSerializer(MODULE_PERMISSIONS)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def assigned_users(self, request, pk=None):
        """List users assigned to this role."""
        role = self.get_object()
        assignments = UserRole.objects.filter(role=role, is_active=True).select_related('user')
        users = [a.user for a in assignments if a.is_valid]
        return Response(UserSerializer(users, many=True).data)


# =============================================================================
# PERMISSION MANAGEMENT
# =============================================================================

class PermissionViewSet(ModelViewSet):
    """
    CRUD for Permission records (the permission catalogue).
    Mostly read-only; seeded via management command.
    """
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsSystemAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'module', 'is_active']
    search_fields = ['name', 'code', 'description', 'module']

    @action(detail=False, methods=['get'])
    def by_module(self, request):
        """Return permissions grouped by module."""
        perms = Permission.objects.filter(is_active=True).order_by('module', 'name')
        grouped = {}
        for perm in perms:
            module = perm.module or 'other'
            if module not in grouped:
                grouped[module] = []
            grouped[module].append(PermissionSerializer(perm).data)
        return Response(grouped)


# =============================================================================
# FUNCTION-BASED VIEWS
# =============================================================================

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
def current_user(request):
    """Get current user info + effective permissions."""
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=status.HTTP_401_UNAUTHORIZED)

    user = request.user
    try:
        user = _get_preloaded_user(request.user.pk)
    except User.DoesNotExist:
        pass

    tenant_info = None
    
    tenant_schema = None
    if user and getattr(user, 'tenant_id', None) and user.tenant_id != 'public':
        tenant_schema = user.tenant_id
    elif hasattr(connection, 'tenant') and connection.tenant and connection.tenant.schema_name != 'public':
        tenant_schema = connection.tenant.schema_name

    if tenant_schema:
        try:
            from tenants.models import Client
            from tenants.serializers import ClientSerializer
            from django_tenants.utils import schema_context
            from django.db.models import Prefetch
            
            with schema_context('public'):
                from tenants.models import PlatformInvoice
                paid_invoices_prefetch = Prefetch(
                    'platform_invoices',
                    queryset=PlatformInvoice.objects.filter(status__in=['paid', 'verified']).only('id', 'status', 'tenant_id'),
                )
                tenant = Client.objects.select_related('kyc').prefetch_related(
                    'domains', 'settings', 'subscription', paid_invoices_prefetch
                ).filter(schema_name=tenant_schema).first()
                if tenant:
                    tenant_info = ClientSerializer(tenant, context={'request': request}).data
                    try:
                        kyc_obj = tenant.kyc  # raises RelatedObjectDoesNotExist if no KYC
                        tenant_info['kyc_status'] = kyc_obj.status or 'not_started'
                    except Exception:
                        tenant_info['kyc_status'] = 'not_started'
                    try:
                        from properties.models import Unit
                        with schema_context(tenant.schema_name):
                            tenant_info['current_unit_count'] = Unit.objects.count()
                    except Exception:
                        tenant_info['current_unit_count'] = 0
        except Exception:
            pass
    elif hasattr(connection, 'tenant') and connection.tenant:
        try:
            from tenants.models import Client
            from tenants.serializers import ClientSerializer
            from django_tenants.utils import schema_context
            from django.db.models import Prefetch
            
            with schema_context('public'):
                from tenants.models import PlatformInvoice
                paid_invoices_prefetch = Prefetch(
                    'platform_invoices',
                    queryset=PlatformInvoice.objects.filter(status__in=['paid', 'verified']).only('id', 'status', 'tenant_id'),
                )
                tenant = Client.objects.select_related('kyc').prefetch_related(
                    'domains', 'settings', 'subscription', paid_invoices_prefetch
                ).filter(pk=connection.tenant.pk).first()
                if tenant:
                    tenant_info = ClientSerializer(tenant, context={'request': request}).data
                    try:
                        kyc_obj = tenant.kyc
                        tenant_info['kyc_status'] = kyc_obj.status or 'not_started'
                    except Exception:
                        tenant_info['kyc_status'] = 'not_started'
                    try:
                        from properties.models import Unit
                        with schema_context(tenant.schema_name):
                            tenant_info['current_unit_count'] = Unit.objects.count()
                    except Exception:
                        tenant_info['current_unit_count'] = 0
        except Exception:
            pass

    # Effective permissions
    perms = get_user_permissions(user)
    is_admin = user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin')

    return Response({
        'user': UserSerializer(user).data,
        'tenant': tenant_info,
        'permissions': ['*'] if is_admin else list(perms),
    })


@extend_schema(request=ProfileUpdateSerializer, responses=OpenApiTypes.OBJECT)
@api_view(['GET', 'PUT', 'PATCH'])
def update_profile(request):
    """Update the current user's profile."""
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=request.user)

    serializer = ProfileUpdateSerializer(profile, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        _log_activity(
            user=request.user,
            action='profile_updated',
            description='Profile information updated',
            request=request,
        )
        try:
            user = _get_preloaded_user(request.user.pk)
        except User.DoesNotExist:
            user = request.user
        return Response(UserSerializer(user).data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=PasswordChangeSerializer, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
def change_password(request):
    """Change the current user's password."""
    serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        _log_activity(
            user=request.user,
            action='password_changed',
            description='Password changed successfully',
            request=request,
        )
        return Response({'message': 'Password changed successfully'})
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=OTPRequestSerializer, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthRateThrottle])
def request_otp(request):
    """Request OTP for email verification.
    
    VAPT-2026-062/063: Returns the same generic response whether or not
    the email exists — prevents user/org enumeration attacks.
    """
    serializer = OTPRequestSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        try:
            user = User.objects.get(email=email)
            otp_code = user.generate_otp()
            try:
                send_otp_email_async.delay(str(user.id), otp_code)
            except Exception:
                logger.warning(f"Could not queue OTP email for {email}")
        except User.DoesNotExist:
            # VAPT-2026-062: Do NOT reveal that the user doesn't exist.
            # Log it internally but return the same response.
            logger.info(f"OTP requested for non-existent email: {email} — returning generic response")
        # Always return the same message — attacker cannot tell if email exists
        return Response({'message': 'If this email is registered, an OTP has been sent.'})
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=OTPVerifySerializer, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([OtpVerifyThrottle])  # VAPT-2026-087: Tighter throttle — 5 attempts per 10 min
def verify_otp(request):
    """Verify OTP code and return JWT tokens."""
    serializer = OTPVerifySerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        _log_activity(user=user, action='otp_verified', description='OTP verified successfully', request=request)
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthRateThrottle])
def verify_email(request):
    """Verify email address via token (sent in welcome/verification email)."""
    token = request.data.get('token')
    if not token:
        return Response({'error': 'Verification token is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email_verification_token=token)
        user.email_verified = True
        user.email_verification_token = None
        user.save(update_fields=['email_verified', 'email_verification_token'])

        _log_activity(user=user, action='email_verified', description='Email verified via token', request=request)
        return Response({'message': 'Email verified successfully'})
    except User.DoesNotExist:
        return Response({'error': 'Invalid verification token'}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthRateThrottle])
def request_password_reset(request):
    """Request a password reset email."""
    email = request.data.get('email')
    if not email:
        return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email=email)
        reset_token = secrets.token_urlsafe(32)
        user.email_verification_token = reset_token
        user.password_reset_token_created_at = timezone.now()
        user.save(update_fields=['email_verification_token', 'password_reset_token_created_at'])
        try:
            send_password_reset_email_async.delay(str(user.id), reset_token)
        except Exception:
            logger.warning(f"Could not queue password reset email for {email}")
        return Response({'message': 'Password reset link sent to your email'})
    except User.DoesNotExist:
        # Don't reveal whether the email exists
        return Response({'message': 'If this email exists, a password reset link has been sent'})


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthRateThrottle])
def reset_password(request):
    """Reset password with token."""
    token = request.data.get('token')
    new_password = request.data.get('new_password')

    if not token or not new_password:
        return Response(
            {'error': 'Token and new password are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = User.objects.get(email_verification_token=token)

        # Check token expiry (1 hour)
        if user.password_reset_token_created_at:
            token_age = timezone.now() - user.password_reset_token_created_at
            if token_age > timedelta(hours=1):
                user.email_verification_token = None
                user.password_reset_token_created_at = None
                user.save(update_fields=['email_verification_token', 'password_reset_token_created_at'])
                return Response(
                    {'error': 'Reset token has expired. Please request a new one.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            from django.contrib.auth.password_validation import validate_password
            validate_password(new_password, user)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.email_verification_token = None
        user.password_reset_token_created_at = None
        user.save(update_fields=['password', 'email_verification_token', 'password_reset_token_created_at'])

        # VAPT-2026-036: Invalidate all existing sessions/tokens on password reset.
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
            old_tokens = OutstandingToken.objects.filter(user=user)
            for old_token in old_tokens:
                try:
                    BlacklistedToken.objects.get_or_create(token=old_token)
                except Exception:
                    pass
        except Exception:
            pass

        _log_activity(user=user, action='password_reset', description='Password reset successfully', request=request)
        return Response({'message': 'Password reset successful. You can now login with your new password.'})

    except User.DoesNotExist:
        return Response({'error': 'Invalid or expired reset token'}, status=status.HTTP_400_BAD_REQUEST)


# =============================================================================
# DASHBOARD & ACTIVITY
# =============================================================================

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
def dashboard_stats(request):
    """Dashboard statistics based on user role."""
    user = request.user
    now = timezone.now()
    week_ago = now - timedelta(days=7)
    stats = {}

    if user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
        stats.update({
            'total_users': User.objects.count(),
            'active_users': User.objects.filter(is_active=True).count(),
            'verified_users': User.objects.filter(email_verified=True).count(),
            'pending_approval': User.objects.filter(is_approved=False).count(),
            'recent_registrations': User.objects.filter(created_at__gte=week_ago).count(),
            'role_distribution': dict(
                User.objects.values_list('role').annotate(count=Count('role'))
            ),
        })
        current_schema = getattr(connection, 'schema_name', 'unknown')
        if current_schema == 'public':
            try:
                from tenants.models import Client
                stats['total_tenants'] = Client.objects.exclude(schema_name='public').count()
            except Exception:
                pass

    elif user.role == 'facility_manager':
        tenant_users = User.objects.filter(tenant_id=user.tenant_id)
        stats.update({
            'tenant_users': tenant_users.count(),
            'active_tenant_users': tenant_users.filter(is_active=True).count(),
            'pending_approval': tenant_users.filter(is_approved=False).count(),
            'recent_registrations': tenant_users.filter(created_at__gte=week_ago).count(),
        })
        try:
            from properties.models import Building, Unit
            stats.update({
                'total_buildings': Building.objects.count(),
                'total_units': Unit.objects.count(),
                'occupied_units': Unit.objects.filter(status='occupied').count(),
            })
        except ImportError:
            pass

    else:
        stats.update({
            'profile_completion': _calculate_profile_completion(user),
            'activities_this_week': ActivityLog.objects.filter(
                user=user, created_at__gte=week_ago
            ).count(),
        })

    return Response(stats)


def _calculate_profile_completion(user):
    """Calculate profile completion percentage."""
    fields_to_check = [
        user.first_name, user.last_name, user.email, user.phone,
        user.unit_number, user.building_name,
        user.emergency_contact_name, user.emergency_contact_phone,
    ]
    filled = sum(1 for f in fields_to_check if f)
    return round((filled / len(fields_to_check)) * 100)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET', 'DELETE'])
def activity_logs(request):
    """Get activity logs or delete all activity logs."""
    is_admin = (
        getattr(request.user, 'is_superuser', False) or
        getattr(request.user, 'is_staff', False) or
        getattr(request.user, 'role', '') in ('super_admin', 'superadmin', 'master_admin', 'masteradmin')
    )

    if request.method == 'DELETE':
        if not is_admin:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Delete logs in current schema
        deleted_count, _ = ActivityLog.objects.all().delete()
        
        # If super_admin, also clear all other tenant schemas
        is_superadmin = (
            getattr(request.user, 'is_superuser', False) or
            getattr(request.user, 'role', '') in ('super_admin', 'superadmin')
        )
        if is_superadmin:
            from tenants.models import Client
            from django_tenants.utils import schema_context
            from django.db import connection
            
            for tenant_client in Client.objects.exclude(schema_name=connection.schema_name):
                with schema_context(tenant_client.schema_name):
                    c, _ = ActivityLog.objects.all().delete()
                    deleted_count += c
                    
        return Response({'message': f'Successfully deleted {deleted_count} logs'}, status=status.HTTP_200_OK)

    user_id = request.query_params.get('user_id')

    if user_has_permission(request.user, 'users.view'):
        if user_id:
            logs = ActivityLog.objects.filter(user_id=user_id).select_related('user', 'affected_user').order_by('-created_at')
        else:
            logs = ActivityLog.objects.all().select_related('user', 'affected_user').order_by('-created_at')
    else:
        # Default to current user if not specified
        logs = ActivityLog.objects.filter(user=request.user).select_related('user', 'affected_user').order_by('-created_at')

    search_query = request.query_params.get('search')
    if search_query:
        from django.db.models import Q
        logs = logs.filter(
            Q(user__username__icontains=search_query) |
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(action__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    action_filter = request.query_params.get('action')
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)

    # Use DRF pagination
    from rest_framework.pagination import PageNumberPagination
    paginator = PageNumberPagination()
    paginator.page_size = 50
    paginator.page_size_query_param = 'page_size'
    paginator.max_page_size = 100
    page = paginator.paginate_queryset(logs, request)
    serializer = ActivityLogSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


# Activity detail view for deletion
@api_view(['DELETE'])
def activity_log_detail(request, pk):
    """Delete a specific activity log entry."""
    from django.db import connection
    
    # Try integer conversion if needed
    try:
        log_id = int(pk)
    except (ValueError, TypeError):
        log_id = pk

    log = ActivityLog.objects.filter(pk=log_id).first()
    
    # Check if user is system admin/superuser
    is_admin = (
        getattr(request.user, 'is_superuser', False) or
        getattr(request.user, 'is_staff', False) or
        getattr(request.user, 'role', '') in ('super_admin', 'superadmin', 'master_admin', 'masteradmin')
    )
    
    if not log:
        # If not found in the current schema, and the user is an admin, search other schemas
        if is_admin:
            from tenants.models import Client
            from django_tenants.utils import schema_context
            
            for tenant_client in Client.objects.exclude(schema_name=connection.schema_name):
                with schema_context(tenant_client.schema_name):
                    log = ActivityLog.objects.filter(pk=log_id).first()
                    if log:
                        # Verify permissions inside the matching schema context
                        if log.user != request.user and not is_admin:
                            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
                        log.delete()
                        return Response(status=status.HTTP_204_NO_CONTENT)

    if not log:
        return Response({'error': f'Log {log_id} not found in any schema'}, status=status.HTTP_404_NOT_FOUND)
        
    # Only the creator or a super admin can delete a log
    if log.user != request.user and not is_admin:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
    log.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# =============================================================================
# NOTIFICATION PREFERENCES
# =============================================================================

@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['GET', 'PUT'])
@permission_classes([permissions.IsAuthenticated])
def notification_preferences(request):
    """Get or update notification preferences."""
    user = request.user

    if request.method == 'GET':
        return Response({'notification_preferences': user.notification_preferences or {}})

    # PUT
    notification_prefs = request.data.get('notification_preferences', {})
    if not isinstance(notification_prefs, dict):
        return Response(
            {'error': 'Invalid notification preferences format'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user.notification_preferences = notification_prefs
    user.save(update_fields=['notification_preferences'])

    _log_activity(
        user=user,
        action='notification_preferences_updated',
        description='Updated notification preferences',
        metadata={'preferences': notification_prefs},
    )
    return Response({
        'message': 'Notification preferences updated successfully',
        'notification_preferences': user.notification_preferences,
    })


# =============================================================================
# RBAC CHECK ENDPOINT (for frontend)
# =============================================================================

@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def check_permissions(request):
    """
    Check if the current user has specific permissions.

    Body: {"permissions": ["users.create", "properties.view"]}
    Returns: {"users.create": true, "properties.view": false}
    """
    codes = request.data.get('permissions', [])
    if not isinstance(codes, list):
        return Response({'error': 'permissions must be a list'}, status=status.HTTP_400_BAD_REQUEST)

    results = {}
    for code in codes:
        results[code] = user_has_permission(request.user, code)

    return Response(results)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_permissions(request):
    """
    Return all effective permissions for the current user,
    grouped by module.
    """
    user = request.user
    is_admin = user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin')
    perms = get_user_permissions(user)

    modules = {}
    for module, codes in MODULE_PERMISSIONS.items():
        modules[module] = {
            code: (is_admin or code in perms) for code in codes
        }


    return Response({
        'role': user.role,
        'is_full_admin': is_admin,
        'permissions': ['*'] if is_admin else list(perms),
        'modules': modules,
    })

