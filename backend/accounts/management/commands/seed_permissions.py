# accounts/management/commands/seed_permissions.py
"""
Management command to seed all default permissions, roles, and default role assignments.

Usage:
    python manage.py seed_permissions             # Seed permissions + roles
    python manage.py seed_permissions --roles     # Only seed roles
    python manage.py seed_permissions --perms     # Only seed permissions
    python manage.py seed_permissions --reset     # Reset and re-create everything
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import Permission, Role
from accounts.permissions import MODULE_PERMISSIONS


# =============================================================================
# DEFAULT PERMISSIONS REGISTRY
# =============================================================================

DEFAULT_PERMISSIONS = []

# Build permissions from MODULE_PERMISSIONS in permissions.py
_MODULE_CATEGORY_MAP = {
    'dashboard': 'system',
    'users': 'user',
    'roles': 'user',
    'properties': 'property',
    'units': 'property',
    'residents': 'user',
    'maintenance': 'maintenance',
    'payments': 'payment',
    'amenities': 'amenity',
    'visitors': 'visitor',
    'parking': 'parking',
    'communication': 'communication',
    'notifications': 'notification',
    'security': 'security',
    'reports': 'report',
    'utilities': 'utility',
    'calendar': 'calendar',
    'vendors': 'vendor',
    'entertainment': 'entertainment',
    'support': 'support',
    'settings': 'settings',
}

_ACTION_NAMES = {
    'view': 'View',
    'create': 'Create',
    'update': 'Update',
    'delete': 'Delete',
    'assign': 'Assign',
    'approve': 'Approve',
    'bulk_action': 'Bulk Action',
    'import': 'Import',
    'export': 'Export',
    'process_refund': 'Process Refund',
    'book': 'Book',
    'broadcast': 'Broadcast',
    'manage_templates': 'Manage Templates',
    'manage_access': 'Manage Access',
    'view_logs': 'View Logs',
    'schedule': 'Schedule',
    'manage_tenant': 'Manage Tenant',
    'view_analytics': 'View Analytics',
}

for module, codes in MODULE_PERMISSIONS.items():
    category = _MODULE_CATEGORY_MAP.get(module, 'system')
    module_display = module.replace('_', ' ').title()

    for code in codes:
        # Extract action from code (e.g., "users.create" -> "create")
        action = code.split('.')[-1]
        action_display = _ACTION_NAMES.get(action, action.replace('_', ' ').title())

        DEFAULT_PERMISSIONS.append({
            'code': code,
            'name': f'{action_display} {module_display}',
            'description': f'Permission to {action_display.lower()} {module_display.lower()}',
            'module': module,
            'category': category,
        })


# =============================================================================
# DEFAULT ROLES
# =============================================================================

DEFAULT_ROLES = [
    {
        'name': 'master_admin',
        'display_name': 'Master Admin',
        'description': 'Full system access. Can manage all tenants, users, roles, and system settings.',
        'level': 100,
        'is_system_role': True,
        'permissions': list(set(code for codes in MODULE_PERMISSIONS.values() for code in codes)),
    },
    {
        'name': 'super_admin',
        'display_name': 'Super Admin',
        'description': 'Organization admin. Full access to all modules within their organization.',
        'level': 90,
        'is_system_role': True,
        'permissions': list(set(code for codes in MODULE_PERMISSIONS.values() for code in codes)),
    },
    {
        'name': 'platform_member',
        'display_name': 'Platform Member',
        'description': 'Platform-side member with limited public-schema access and no tenant admin powers.',
        'level': 60,
        'is_system_role': True,
        'permissions': [
            'dashboard.view',
            'users.view',
            'roles.view',
            'reports.view',
            'support.view', 'support.create',
            'notifications.view',
        ],
    },
    {
        'name': 'facility_manager',
        'display_name': 'Facility Manager',
        'description': 'Manages properties, residents, maintenance, and day-to-day operations.',
        'level': 70,
        'is_system_role': False,
        'permissions': [
            # Dashboard
            'dashboard.view', 'dashboard.view_analytics',
            # Users (limited)
            'users.view', 'users.create', 'users.update', 'users.approve', 'users.bulk_action',
            # Roles (view only)
            'roles.view', 'roles.assign',
            # Properties
            'properties.view', 'properties.create', 'properties.update', 'properties.delete',
            'units.view', 'units.create', 'units.update', 'units.assign',
            # Residents
            'residents.view', 'residents.create', 'residents.update', 'residents.delete', 'residents.import', 'residents.export',
            # Maintenance
            'maintenance.view', 'maintenance.create', 'maintenance.update', 'maintenance.delete', 'maintenance.assign',
            # Payments
            'payments.view', 'payments.create', 'payments.update',
            # Amenities
            'amenities.view', 'amenities.create', 'amenities.update', 'amenities.delete', 'amenities.book',
            # Visitors
            'visitors.view', 'visitors.create', 'visitors.update', 'visitors.delete', 'visitors.approve',
            # Parking
            'parking.view', 'parking.create', 'parking.update', 'parking.delete', 'parking.assign',
            # Communication
            'communication.view', 'communication.create', 'communication.broadcast',
            # Notifications
            'notifications.view', 'notifications.create', 'notifications.manage_templates',
            # Security
            'security.view', 'security.create', 'security.manage_access', 'security.view_logs',
            # Reports
            'reports.view', 'reports.create', 'reports.export', 'reports.schedule',
            # Utilities
            'utilities.view', 'utilities.create', 'utilities.update', 'utilities.delete',
            # Calendar
            'calendar.view', 'calendar.create', 'calendar.update', 'calendar.delete',
            # Vendors
            'vendors.view', 'vendors.create', 'vendors.update', 'vendors.delete',
            # Entertainment
            'entertainment.view', 'entertainment.create', 'entertainment.update', 'entertainment.delete',
            # Support
            'support.view', 'support.create', 'support.update', 'support.assign',
            # Settings
            'settings.view', 'settings.update',
        ],
    },
    {
        'name': 'property_staff',
        'display_name': 'Property Staff',
        'description': 'Handles day-to-day property tasks: resident queries, visitor management, etc.',
        'level': 50,
        'is_system_role': False,
        'permissions': [
            'dashboard.view',
            'users.view',
            'residents.view', 'residents.create', 'residents.update',
            'properties.view',
            'units.view',
            'maintenance.view', 'maintenance.create', 'maintenance.update',
            'visitors.view', 'visitors.create', 'visitors.update', 'visitors.approve',
            'parking.view', 'parking.assign',
            'communication.view', 'communication.create',
            'notifications.view',
            'security.view', 'security.view_logs',
            'amenities.view', 'amenities.book',
            'calendar.view',
            'support.view', 'support.create', 'support.update',
            'utilities.view',
        ],
    },
    {
        'name': 'owner',
        'display_name': 'Property Owner',
        'description': 'Property owner with access to owned unit details, payments, and resident services.',
        'level': 40,
        'is_system_role': False,
        'permissions': [
            'dashboard.view',
            'properties.view',
            'units.view',
            'payments.view', 'payments.create',
            'maintenance.view', 'maintenance.create',
            'amenities.view', 'amenities.book',
            'visitors.view', 'visitors.create',
            'parking.view',
            'communication.view', 'communication.create',
            'notifications.view',
            'reports.view',
            'support.view', 'support.create',
            'utilities.view',
            'calendar.view',
        ],
    },
    {
        'name': 'maintenance_staff',
        'display_name': 'Maintenance Staff',
        'description': 'Handles maintenance requests, inspections, and repairs.',
        'level': 30,
        'is_system_role': False,
        'permissions': [
            'dashboard.view',
            'maintenance.view', 'maintenance.update',
            'properties.view',
            'units.view',
            'communication.view', 'communication.create',
            'notifications.view',
            'support.view', 'support.create',
        ],
    },
    {
        'name': 'tenant_vendor',
        'display_name': 'Tenant Vendor',
        'description': 'Tenant-side vendor/service provider with access to assigned service workflows.',
        'level': 25,
        'is_system_role': False,
        'permissions': [
            'dashboard.view',
            'vendors.view',
            'maintenance.view', 'maintenance.update',
            'support.view', 'support.update',
            'communication.view',
            'notifications.view',
        ],
    },
    {
        'name': 'security_guard',
        'display_name': 'Security Guard',
        'description': 'Manages gate access, visitor approvals, and security logs.',
        'level': 20,
        'is_system_role': False,
        'permissions': [
            'dashboard.view',
            'visitors.view', 'visitors.create', 'visitors.update', 'visitors.approve',
            'security.view', 'security.create', 'security.view_logs',
            'parking.view',
            'communication.view',
            'notifications.view',
        ],
    },
    {
        'name': 'tenant',
        'display_name': 'Tenant/Resident',
        'description': 'Resident of the property. Can view their own data, raise requests, and book amenities.',
        'level': 10,
        'is_system_role': False,
        'permissions': [
            'dashboard.view',
            'maintenance.view', 'maintenance.create',
            'payments.view', 'payments.create',
            'amenities.view', 'amenities.book',
            'visitors.view', 'visitors.create',
            'parking.view',
            'communication.view', 'communication.create',
            'notifications.view',
            'calendar.view',
            'entertainment.view',
            'support.view', 'support.create',
            'utilities.view',
        ],
    },
    {
        'name': 'tenant_resident',
        'display_name': 'Tenant/Resident',
        'description': 'Backward-compatible resident role used by legacy tests and integrations.',
        'level': 10,
        'is_system_role': False,
        'permissions': [
            'dashboard.view',
            'maintenance.view', 'maintenance.create',
            'payments.view', 'payments.create',
            'amenities.view', 'amenities.book',
            'visitors.view', 'visitors.create',
            'parking.view',
            'communication.view', 'communication.create',
            'notifications.view',
            'calendar.view',
            'entertainment.view',
            'support.view', 'support.create',
            'utilities.view',
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed default permissions and roles for the RBAC system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--roles',
            action='store_true',
            help='Only seed/update roles',
        )
        parser.add_argument(
            '--perms',
            action='store_true',
            help='Only seed/update permissions',
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Delete existing permissions/roles and re-create from scratch',
        )

    def handle(self, *args, **options):
        seed_roles = options.get('roles', False)
        seed_perms = options.get('perms', False)
        reset = options.get('reset', False)

        # If neither flag is set, do both
        if not seed_roles and not seed_perms:
            seed_roles = True
            seed_perms = True

        if reset:
            self.stdout.write(self.style.WARNING('Resetting all permissions and roles...'))

        with transaction.atomic():
            if seed_perms:
                self._seed_permissions(reset)
            if seed_roles:
                self._seed_roles(reset)

        self.stdout.write(self.style.SUCCESS('RBAC seed completed successfully.'))

    def _seed_permissions(self, reset=False):
        if reset:
            deleted_count, _ = Permission.objects.all().delete()
            self.stdout.write(f'  Deleted {deleted_count} existing permissions.')

        created = 0
        updated = 0

        for perm_data in DEFAULT_PERMISSIONS:
            obj, was_created = Permission.objects.update_or_create(
                code=perm_data['code'],
                defaults={
                    'name': perm_data['name'],
                    'description': perm_data['description'],
                    'module': perm_data['module'],
                    'category': perm_data['category'],
                    'is_active': True,
                }
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f'  Permissions: {created} created, {updated} updated. '
                               f'Total: {Permission.objects.count()}')
        )

    def _seed_roles(self, reset=False):
        if reset:
            deleted_count, _ = Role.objects.filter(is_system_role=True).delete()
            self.stdout.write(f'  Deleted {deleted_count} existing system roles.')

        created = 0
        updated = 0

        for role_data in DEFAULT_ROLES:
            obj, was_created = Role.objects.update_or_create(
                name=role_data['name'],
                defaults={
                    'display_name': role_data['display_name'],
                    'description': role_data['description'],
                    'level': role_data['level'],
                    'is_system_role': role_data.get('is_system_role', False),
                    'permissions': role_data['permissions'],
                    'is_active': True,
                }
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f'  Roles: {created} created, {updated} updated. '
                               f'Total: {Role.objects.count()}')
        )
