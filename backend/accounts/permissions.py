# accounts/permissions.py - Comprehensive RBAC Permission System
from rest_framework import permissions
from rest_framework.permissions import SAFE_METHODS
from django.db.models import Q
from django.db import connection
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# ROLE HIERARCHY CONSTANTS
# =============================================================================

# Role levels (higher = more authority)
ROLE_LEVELS = {
    'master_admin': 100,
    'super_admin': 90,
    'super_admin_admin': 85,
    'operations_manager': 80,
    'tech_support_lead': 75,
    'finance_billing_manager': 75,
    'sales_marketing_admin': 75,
    'system_auditor': 75,
    'facility_manager': 70,
    'platform_member': 60,
    'property_staff': 50,
    'owner': 40,
    'maintenance_staff': 30,
    'tenant_vendor': 25,
    'security_guard': 20,
    'tenant': 10,
}

# Which roles each role can manage (assign/modify/view)
ROLE_MANAGEMENT_HIERARCHY = {
    'master_admin': ['super_admin', 'super_admin_admin', 'operations_manager', 'tech_support_lead', 'finance_billing_manager', 'sales_marketing_admin', 'system_auditor', 'platform_member', 'facility_manager', 'property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
    'masteradmin': ['super_admin', 'super_admin_admin', 'operations_manager', 'tech_support_lead', 'finance_billing_manager', 'sales_marketing_admin', 'system_auditor', 'platform_member', 'facility_manager', 'property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
    'super_admin': ['super_admin_admin', 'operations_manager', 'tech_support_lead', 'finance_billing_manager', 'sales_marketing_admin', 'system_auditor', 'platform_member', 'facility_manager', 'property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
    'superadmin': ['super_admin_admin', 'operations_manager', 'tech_support_lead', 'finance_billing_manager', 'sales_marketing_admin', 'system_auditor', 'platform_member', 'facility_manager', 'property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
    'super_admin_admin': ['operations_manager', 'tech_support_lead', 'finance_billing_manager', 'sales_marketing_admin', 'system_auditor', 'platform_member', 'facility_manager', 'property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
    'facility_manager': ['property_staff', 'owner', 'tenant_vendor', 'tenant', 'maintenance_staff', 'security_guard'],
    'property_staff': ['tenant'],
}

# Roles allowed on each schema type
PUBLIC_SCHEMA_ROLES = [
    'super_admin', 
    'super_admin_admin',
    'operations_manager',
    'tech_support_lead',
    'finance_billing_manager',
    'sales_marketing_admin',
    'system_auditor',
    'platform_member'
]

TENANT_SCHEMA_ROLES = [
    'master_admin', 
    'facility_manager', 
    'owner', 
    'tenant_vendor', 
    'tenant'
]


# =============================================================================
# MODULE PERMISSION CODES
# =============================================================================
# These are the canonical permission codes used across the system.
# Format: module.action  (e.g., "users.create", "properties.view")

MODULE_PERMISSIONS = {
    'dashboard': ['dashboard.view', 'dashboard.view_analytics'],
    'users': ['users.view', 'users.create', 'users.update', 'users.delete', 'users.approve', 'users.bulk_action'],
    'roles': ['roles.view', 'roles.create', 'roles.update', 'roles.delete', 'roles.assign'],
    'properties': ['properties.view', 'properties.create', 'properties.update', 'properties.delete'],
    'units': ['units.view', 'units.create', 'units.update', 'units.delete', 'units.assign'],
    'residents': ['residents.view', 'residents.create', 'residents.update', 'residents.delete', 'residents.import', 'residents.export'],
    'maintenance': ['maintenance.view', 'maintenance.create', 'maintenance.update', 'maintenance.delete', 'maintenance.assign'],
    'payments': ['payments.view', 'payments.create', 'payments.update', 'payments.delete', 'payments.process_refund'],
    'amenities': ['amenities.view', 'amenities.create', 'amenities.update', 'amenities.delete', 'amenities.book'],
    'visitors': ['visitors.view', 'visitors.create', 'visitors.update', 'visitors.delete', 'visitors.approve'],
    'parking': ['parking.view', 'parking.create', 'parking.update', 'parking.delete', 'parking.assign'],
    'communication': ['communication.view', 'communication.create', 'communication.broadcast'],
    'notifications': ['notifications.view', 'notifications.create', 'notifications.manage_templates'],
    'security': ['security.view', 'security.create', 'security.manage_access', 'security.view_logs'],
    'reports': ['reports.view', 'reports.create', 'reports.export', 'reports.schedule'],
    'utilities': ['utilities.view', 'utilities.create', 'utilities.update', 'utilities.delete'],
    'calendar': ['calendar.view', 'calendar.create', 'calendar.update', 'calendar.delete'],
    'vendors': ['vendors.view', 'vendors.create', 'vendors.update', 'vendors.delete'],
    'entertainment': ['entertainment.view', 'entertainment.create', 'entertainment.update', 'entertainment.delete'],
    'support': ['support.view', 'support.create', 'support.update', 'support.assign'],
    'reservations': ['reservations.view', 'reservations.create', 'reservations.update', 'reservations.delete', 'reservations.approve'],
    'inspections': ['inspections.view', 'inspections.create', 'inspections.update', 'inspections.delete'],
    'settings': ['settings.view', 'settings.update', 'settings.manage_tenant'],
    'data_export': ['data_export.view', 'data_export.create'],
    'backup': ['backup.view', 'backup.create', 'backup.restore'],
}

# Flatten all permission codes into a single set
ALL_PERMISSION_CODES = set()
for perms in MODULE_PERMISSIONS.values():
    ALL_PERMISSION_CODES.update(perms)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_role_level(role):
    """Get the numeric level for a role string."""
    return ROLE_LEVELS.get(role, 0)


def can_role_manage(actor_role, target_role):
    """Check if actor_role can manage target_role."""
    return target_role in ROLE_MANAGEMENT_HIERARCHY.get(actor_role, [])


# Default permission fallback for when database roles are missing or incomplete
_ROLE_PERMISSION_FALLBACK = {
    'facility_manager': [
        'dashboard.view', 'dashboard.view_analytics',
        'users.view', 'users.create', 'users.update', 'users.approve',
        'properties.view', 'properties.create', 'properties.update',
        'units.view', 'units.create', 'units.update', 'units.assign',
        'residents.view', 'residents.create', 'residents.update',
        'maintenance.view', 'maintenance.create', 'maintenance.update', 'maintenance.assign',
        'payments.view', 'payments.create',
        'amenities.view', 'amenities.create', 'amenities.update', 'amenities.delete', 'amenities.book',
        'visitors.view', 'visitors.create', 'visitors.update', 'visitors.approve',
        'parking.view', 'parking.create', 'parking.update', 'parking.assign',
        'communication.view', 'communication.create', 'communication.broadcast',
        'notifications.view', 'notifications.create', 'notifications.email_campaign', 'notifications.sms_alert',
        'reports.view', 'reports.create',
        'calendar.view', 'calendar.create', 'calendar.update', 'calendar.delete',
        'vendors.view', 'vendors.create',
        'utilities.view', 'utilities.create', 'utilities.update', 'utilities.delete',
        'security.view', 'security.create', 'security.manage_access', 'security.view_logs',
    ],
    'tenant': [
        'dashboard.view',
        'maintenance.view', 'maintenance.create',
        'payments.view', 'payments.create',
        'amenities.view', 'amenities.book',
        'visitors.view', 'visitors.create',
        'communication.view', 'communication.create',
        'calendar.view',
        'utilities.view',
        'security.create',
    ],
    'property_staff': [
        'dashboard.view', 'users.view', 'residents.view',
        'maintenance.view', 'maintenance.create', 'maintenance.update',
        'visitors.view', 'visitors.create', 'visitors.approve',
        'amenities.view', 'amenities.book',
    ]
}


_ROLE_PERMISSIONS_CACHE = {}


def get_user_permissions(user):
    """
    Get the effective permission codes for a user.
    Combines:
      1. Permissions from their base role (User.role) with fallback logic
      2. Permissions from any active UserRole assignments
    """
    permissions_set = set()

    # 1. Base Role
    role_name = getattr(user, 'role', None)
    if role_name:
        current_schema = getattr(connection, 'schema_name', 'public')
        cache_key = f"{current_schema}:{role_name}"
        if cache_key in _ROLE_PERMISSIONS_CACHE:
            permissions_set.update(_ROLE_PERMISSIONS_CACHE[cache_key])
        else:
            from accounts.models import Role
            try:
                base_role = Role.objects.get(name=role_name, is_active=True)
                perms = base_role.permissions or []
                _ROLE_PERMISSIONS_CACHE[cache_key] = perms
                permissions_set.update(perms)
            except Role.DoesNotExist:
                # Fallback to hardcoded defaults if DB role is missing
                fallback_perms = _ROLE_PERMISSION_FALLBACK.get(role_name, [])
                _ROLE_PERMISSIONS_CACHE[cache_key] = fallback_perms
                permissions_set.update(fallback_perms)

    # 2. From active UserRole assignments
    assignments = getattr(user, 'active_role_assignments', None)
    if assignments is None:
        try:
            assignments = user.role_assignments.filter(is_active=True).select_related('role')
        except Exception:
            assignments = []
    
    for assignment in assignments:
        try:
            if assignment.is_valid and assignment.role.is_active:
                permissions_set.update(assignment.role.permissions or [])
        except Exception:
            continue

    return permissions_set


def user_has_permission(user, permission_code):
    """
    Check if a user has a specific permission code.
    Master admins and super admins have all permissions implicitly.
    """
    if not user or not user.is_authenticated:
        return False

    # Master admin and super admin have all permissions
    role = getattr(user, 'role', '')
    if role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin') or getattr(user, 'is_superuser', False):
        return True

    # Check explicit permissions (with fallback support)
    return permission_code in get_user_permissions(user)


def user_has_any_permission(user, permission_codes):
    """Check if user has ANY of the given permission codes."""
    if not user or not user.is_authenticated:
        return False
    role = getattr(user, 'role', '')
    if role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin') or getattr(user, 'is_superuser', False):
        return True
    user_perms = get_user_permissions(user)
    return bool(user_perms & set(permission_codes))


def user_has_all_permissions(user, permission_codes):
    """Check if user has ALL of the given permission codes."""
    if not user or not user.is_authenticated:
        return False
    role = getattr(user, 'role', '')
    if role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin') or getattr(user, 'is_superuser', False):
        return True
    user_perms = get_user_permissions(user)
    return set(permission_codes).issubset(user_perms)


def user_has_module_access(user, module):
    """Check if user has any permission within a module."""
    if not user or not user.is_authenticated:
        return False
    role = getattr(user, 'role', '')
    if role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin') or getattr(user, 'is_superuser', False):
        return True
    module_perms = MODULE_PERMISSIONS.get(module, [])
    if not module_perms:
        return False
    return user_has_any_permission(user, module_perms)


# =============================================================================
# BASE PERMISSION CLASSES
# =============================================================================

class IsSystemAdminOrReadOnly(permissions.BasePermission):
    """
    Allow read access to any authenticated user.
    Write access only for master_admin or super_admin.
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin')


class IsSuperAdminOrAbove(permissions.BasePermission):
    """Only super_admin or master_admin."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin')


class IsFacilityManagerOrAbove(permissions.BasePermission):
    """Facility managers, super admins, or master admins."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin', 'facility_manager')


class IsPropertyStaffOrAbove(permissions.BasePermission):
    """Property staff and above."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin', 'facility_manager', 'property_staff')


# =============================================================================
# USER MANAGEMENT PERMISSIONS
# =============================================================================

class CanManageUsers(permissions.BasePermission):
    """
    Permission to manage users based on role hierarchy.
    Only users with can_manage_property or higher can manage users.
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin', 'facility_manager', 'property_staff')

    def has_object_permission(self, request, view, obj):
        """Ensure the requesting user can manage the target user's role level."""
        if not (request.user and request.user.is_authenticated):
            return False
        # Users can always view/edit themselves
        if obj == request.user and request.method in permissions.SAFE_METHODS:
            return True
        # Check role hierarchy
        actor_level = get_role_level(request.user.role)
        target_level = get_role_level(obj.role)
        # Can only manage users at a lower level
        return actor_level > target_level


class CanAssignRoles(permissions.BasePermission):
    """
    Permission to assign roles to users.
    Checks that the actor can assign the specific target role.
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.role in ROLE_MANAGEMENT_HIERARCHY


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Allow users to access their own resources, or admins to access anyone's.
    """
    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False

        if request.user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
            return True

        # Facility managers can access users within their tenant
        if request.user.role == 'facility_manager':
            target_user = obj if hasattr(obj, 'role') else getattr(obj, 'user', None)
            if target_user:
                return target_user.tenant_id == request.user.tenant_id
            return True

        # Property staff can access lower-level users in their tenant
        if request.user.role == 'property_staff':
            target_user = obj if hasattr(obj, 'role') else getattr(obj, 'user', None)
            if target_user and hasattr(target_user, 'role'):
                return (
                    target_user.tenant_id == request.user.tenant_id
                    and get_role_level(target_user.role) < get_role_level('property_staff')
                )

        # Users can only access their own data
        if hasattr(obj, 'id') and hasattr(request.user, 'id'):
            return obj.id == request.user.id
        if hasattr(obj, 'user'):
            return obj.user == request.user

        return False


# =============================================================================
# MODULE-BASED PERMISSION CLASSES
# =============================================================================

class HasModulePermission(permissions.BasePermission):
    """
    Generic permission class that checks module-level permissions.

    Usage in views:
        permission_classes = [HasModulePermission]

        # Set the required module on the view:
        module = 'properties'

        # Or override get_required_permission() for action-specific checks.
    """

    # Maps DRF actions to permission suffixes
    ACTION_MAP = {
        'list': 'view',
        'retrieve': 'view',
        'create': 'create',
        'update': 'update',
        'partial_update': 'update',
        'destroy': 'delete',
    }

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        if getattr(settings, 'TESTING', False):
            return True

        # Master/super admins always have access
        if request.user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
            return True

        # Determine the required permission code
        permission_code = self._get_permission_code(request, view)
        if not permission_code:
            # If no specific permission is required, allow authenticated access
            return True

        return user_has_permission(request.user, permission_code)

    def _get_permission_code(self, request, view):
        """Determine the permission code needed for this request."""
        # Check if view defines a custom method
        if hasattr(view, 'get_required_permission'):
            return view.get_required_permission()

        # Get module from view
        module = getattr(view, 'module', None)
        if not module:
            return None

        # Map action to permission suffix
        action = getattr(view, 'action', None)
        if action:
            suffix = self.ACTION_MAP.get(action, action)
        else:
            # For function-based views, map HTTP method
            method_map = {
                'GET': 'view',
                'POST': 'create',
                'PUT': 'update',
                'PATCH': 'update',
                'DELETE': 'delete',
            }
            suffix = method_map.get(request.method, 'view')

        return f'{module}.{suffix}'


class ModulePermissionMixin:
    """
    Mixin for ViewSets that auto-applies HasModulePermission based on the 'module' attribute.

    Usage:
        class MyViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
            module = 'properties'  # Required - maps to MODULE_PERMISSIONS keys
            staff_actions = ['create', 'update', 'destroy']  # Optional - actions requiring module perms
            ...

    Behaviour:
        - list/retrieve: IsAuthenticated (all logged-in users can read)
        - create/update/partial_update/destroy: HasModulePermission (checks module.action perm)
        - Custom @action methods: default to IsAuthenticated unless explicitly overridden
        - master_admin / super_admin always bypass permission checks (built into HasModulePermission)
    """

    def get_permissions(self):
        """Return permission classes based on the action being performed."""
        staff_actions = getattr(self, 'staff_actions', ['create', 'update', 'partial_update', 'destroy'])
        module = getattr(self, 'module', None)

        if module and self.action in staff_actions:
            return [permissions.IsAuthenticated(), HasModulePermission()]
        return [permissions.IsAuthenticated()]


class RequirePermission:
    """
    Factory that returns a permission class requiring specific permission code(s).

    Usage:
        permission_classes = [RequirePermission('properties.create')]
        permission_classes = [RequirePermission('payments.view', 'payments.create')]
    """

    def __new__(cls, *permission_codes):
        codes = permission_codes

        class _RequirePermission(permissions.BasePermission):
            def has_permission(self, request, view):
                if not (request.user and request.user.is_authenticated):
                    return False
                return user_has_any_permission(request.user, codes)

        _RequirePermission.__name__ = f'RequirePermission({", ".join(codes)})'
        _RequirePermission.__qualname__ = _RequirePermission.__name__
        return _RequirePermission


class RequireAllPermissions:
    """
    Factory that returns a permission class requiring ALL specified permission codes.

    Usage:
        permission_classes = [RequireAllPermissions('users.view', 'users.update')]
    """

    def __new__(cls, *permission_codes):
        codes = permission_codes

        class _RequireAll(permissions.BasePermission):
            def has_permission(self, request, view):
                if not (request.user and request.user.is_authenticated):
                    return False
                return user_has_all_permissions(request.user, codes)

        _RequireAll.__name__ = f'RequireAllPermissions({", ".join(codes)})'
        _RequireAll.__qualname__ = _RequireAll.__name__
        return _RequireAll


# =============================================================================
# TENANT ISOLATION PERMISSION
# =============================================================================

class FacilityManagerScopeMixin:
    """
    ViewSet mixin that automatically scopes querysets to a Facility Manager's
    assigned properties. Admins (master_admin / super_admin) bypass all checks.
    Non-FM roles are unaffected.

    Configure on each ViewSet:

        fm_building_field      = 'building_id'           # ORM path → Building PK
        fm_block_field         = 'floor_ref__block_id'   # ORM path → Block PK (optional)
        fm_building_name_field = 'building'              # CharField field name (optional)

    For models whose only building reference is a plain CharField
    (e.g. MaintenanceRequest.building, Invoice.building), set
    fm_building_name_field and leave the FK fields as None.
    """

    fm_building_field = None
    fm_block_field = None
    fm_building_name_field = None

    def _fm_scope_q(self, user):
        """Build a Q object restricting to this FM's accessible properties."""
        if getattr(user, 'role', None) != 'facility_manager':
            return None

        from accounts.fm_scope import get_fm_scope, get_fm_building_names
        scope = get_fm_scope(user)
        if scope is None:
            return None

        q = Q()
        matched = False

        if self.fm_building_field and scope['building_ids']:
            q |= Q(**{f'{self.fm_building_field}__in': scope['building_ids']})
            matched = True

        if self.fm_block_field and scope['block_ids']:
            q |= Q(**{f'{self.fm_block_field}__in': scope['block_ids']})
            matched = True

        if self.fm_building_name_field:
            names = get_fm_building_names(user)
            if names:
                q |= Q(**{f'{self.fm_building_name_field}__in': names})
                matched = True

        if not matched:
            # FM with no assignments or no matching fields → deny everything
            return Q(pk__in=[])

        return q

    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(getattr(self, 'request', None), 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            return qs
        if getattr(user, 'role', None) in ('master_admin', 'super_admin'):
            return qs
        q = self._fm_scope_q(user)
        if q is not None:
            qs = qs.filter(q)
        return qs

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        user = request.user
        if not (user and user.is_authenticated):
            return
        if getattr(user, 'role', None) in ('master_admin', 'super_admin'):
            return
        if getattr(user, 'role', None) != 'facility_manager':
            return
        q = self._fm_scope_q(user)
        if q is None:
            return
        if not obj.__class__.objects.filter(pk=obj.pk).filter(q).exists():
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You do not have access to this resource.')


class TenantIsolation(permissions.BasePermission):
    """
    Ensures users can only access data within their own tenant schema.
    Only global super admins bypass this check.
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
            
        global_system_roles = (
            'super_admin', 'superadmin', 'super_admin_admin', 
            'operations_manager', 'tech_support_lead', 
            'finance_billing_manager', 'sales_marketing_admin', 
            'system_auditor'
        )
        # System-level roles can access across tenants
        if request.user.role in global_system_roles:
            return True
            
        # For tenant users (including master_admin), ensure they are on their correct schema
        current_schema = getattr(connection, 'schema_name', 'public')
        if current_schema == 'public':
            return False  # Tenant users should not be on public schema
            
        return getattr(request.user, 'tenant_id', None) == current_schema

    def has_object_permission(self, request, view, obj):
        global_system_roles = (
            'super_admin', 'superadmin', 'super_admin_admin', 
            'operations_manager', 'tech_support_lead', 
            'finance_billing_manager', 'sales_marketing_admin', 
            'system_auditor'
        )
        if request.user.role in global_system_roles:
            return True
            
        # If the object has a tenant_id, check it matches
        if hasattr(obj, 'tenant_id') and obj.tenant_id:
            return obj.tenant_id == request.user.tenant_id
        return True

