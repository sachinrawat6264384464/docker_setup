# accounts/tests.py
"""
Comprehensive tests for the Accounts app covering:
  - Authentication (login, register, JWT, OTP, password reset)
  - RBAC (permissions, role hierarchy, module access)
  - User management (CRUD, bulk actions, approval)
  - Role management (create, update, delete, assign)
  - Permission helper functions
  - Serializers
  - Signals

Run with:
  python manage.py test accounts.tests --verbosity=2
  python manage.py test accounts.tests.PermissionHelperTests  # single class
"""
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock

from accounts.models import UserProfile, Role, Permission, UserRole, ActivityLog
from accounts.permissions import (
    get_role_level, can_role_manage, get_user_permissions,
    user_has_permission, user_has_any_permission, user_has_all_permissions,
    user_has_module_access, ROLE_LEVELS, ROLE_MANAGEMENT_HIERARCHY,
    MODULE_PERMISSIONS, ALL_PERMISSION_CODES, PUBLIC_SCHEMA_ROLES, TENANT_SCHEMA_ROLES,
)
from accounts.serializers import (
    RoleCreateUpdateSerializer, PermissionSerializer, RoleSerializer,
    UserSerializer, UserCreateSerializer,
)

User = get_user_model()


# =============================================================================
# MIXIN: creates users + roles for reuse across test classes
# =============================================================================

class AccountsTestMixin:
    """Provides helper methods and common setup for accounts tests."""

    @classmethod
    def _create_test_role(cls, name, display_name, level, permissions=None, is_system=False):
        return Role.objects.create(
            name=name,
            display_name=display_name,
            description=f'Test role: {display_name}',
            level=level,
            permissions=permissions or [],
            is_system_role=is_system,
            is_active=True,
        )

    @classmethod
    def _create_test_user(cls, username, email, role='tenant', password='TestPass123!', **kwargs):
        defaults = {
            'is_active': True,
            'is_approved': True,
        }
        defaults.update(kwargs)
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=role,
            **defaults,
        )
        return user


# =============================================================================
# 1. PERMISSION HELPER FUNCTION TESTS (unit tests, no DB for most)
# =============================================================================

class PermissionConstantTests(TestCase):
    """Test permission constants and module definitions."""

    def test_role_levels_all_present(self):
        expected_roles = {'master_admin', 'super_admin', 'facility_manager',
                          'platform_member', 'property_staff', 'owner', 'tenant_vendor',
                          'maintenance_staff', 'security_guard', 'tenant'}
        self.assertEqual(set(ROLE_LEVELS.keys()), expected_roles)

    def test_role_levels_hierarchy(self):
        self.assertGreater(ROLE_LEVELS['master_admin'], ROLE_LEVELS['super_admin'])
        self.assertGreater(ROLE_LEVELS['super_admin'], ROLE_LEVELS['facility_manager'])
        self.assertGreater(ROLE_LEVELS['facility_manager'], ROLE_LEVELS['platform_member'])
        self.assertGreater(ROLE_LEVELS['platform_member'], ROLE_LEVELS['property_staff'])
        self.assertGreater(ROLE_LEVELS['property_staff'], ROLE_LEVELS['owner'])
        self.assertGreater(ROLE_LEVELS['owner'], ROLE_LEVELS['maintenance_staff'])
        self.assertGreater(ROLE_LEVELS['facility_manager'], ROLE_LEVELS['property_staff'])
        self.assertGreater(ROLE_LEVELS['property_staff'], ROLE_LEVELS['maintenance_staff'])
        self.assertGreater(ROLE_LEVELS['maintenance_staff'], ROLE_LEVELS['tenant_vendor'])
        self.assertGreater(ROLE_LEVELS['tenant_vendor'], ROLE_LEVELS['security_guard'])
        self.assertGreater(ROLE_LEVELS['maintenance_staff'], ROLE_LEVELS['security_guard'])
        self.assertGreater(ROLE_LEVELS['security_guard'], ROLE_LEVELS['tenant'])

    def test_schema_role_sets_include_new_roles(self):
        self.assertIn('platform_member', PUBLIC_SCHEMA_ROLES)
        self.assertIn('tenant_vendor', TENANT_SCHEMA_ROLES)

    def test_module_permissions_not_empty(self):
        self.assertGreater(len(MODULE_PERMISSIONS), 0)
        for module, codes in MODULE_PERMISSIONS.items():
            self.assertIsInstance(codes, list)
            self.assertGreater(len(codes), 0, f"Module '{module}' has no permissions")

    def test_all_permission_codes_populated(self):
        self.assertGreater(len(ALL_PERMISSION_CODES), 50)

    def test_permission_code_format(self):
        for code in ALL_PERMISSION_CODES:
            parts = code.split('.')
            self.assertEqual(len(parts), 2, f"Invalid permission code format: {code}")


class PermissionHelperTests(TestCase, AccountsTestMixin):
    """Test permission helper functions."""

    def setUp(self):
        self.master = self._create_test_user('master', 'master@test.com', role='master_admin')
        self.super_user = self._create_test_user('superuser', 'super@test.com', role='super_admin')
        self.manager = self._create_test_user('manager', 'manager@test.com', role='facility_manager')
        self.staff = self._create_test_user('staff', 'staff@test.com', role='property_staff')
        self.resident = self._create_test_user('resident', 'resident@test.com', role='tenant')

        # Create a role with specific permissions and assign it to staff
        self.custom_role = self._create_test_role(
            'test_custom', 'Test Custom', level=40,
            permissions=['properties.view', 'properties.create', 'maintenance.view'],
        )
        UserRole.objects.create(
            user=self.staff, role=self.custom_role,
            assigned_by=self.master, is_active=True,
        )

    def test_get_role_level(self):
        self.assertEqual(get_role_level('master_admin'), 100)
        self.assertEqual(get_role_level('tenant'), 10)
        self.assertEqual(get_role_level('nonexistent'), 0)

    def test_can_role_manage(self):
        self.assertTrue(can_role_manage('master_admin', 'super_admin'))
        self.assertTrue(can_role_manage('super_admin', 'facility_manager'))
        self.assertTrue(can_role_manage('super_admin', 'platform_member'))
        self.assertTrue(can_role_manage('facility_manager', 'tenant'))
        self.assertTrue(can_role_manage('facility_manager', 'tenant_vendor'))
        self.assertFalse(can_role_manage('tenant', 'master_admin'))
        self.assertFalse(can_role_manage('property_staff', 'facility_manager'))

    def test_get_user_permissions_from_role_assignment(self):
        perms = get_user_permissions(self.staff)
        self.assertIn('properties.view', perms)
        self.assertIn('properties.create', perms)
        self.assertIn('maintenance.view', perms)
        self.assertNotIn('payments.create', perms)

    def test_get_user_permissions_empty_for_no_assignments(self):
        perms = get_user_permissions(self.resident)
        self.assertEqual(len(perms), 0)

    def test_user_has_permission_admin_always_true(self):
        self.assertTrue(user_has_permission(self.master, 'anything.at_all'))
        self.assertTrue(user_has_permission(self.super_user, 'payments.delete'))

    def test_user_has_permission_checks_assignments(self):
        self.assertTrue(user_has_permission(self.staff, 'properties.view'))
        self.assertFalse(user_has_permission(self.staff, 'payments.create'))

    def test_user_has_permission_unauthenticated(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(user_has_permission(AnonymousUser(), 'anything'))
        self.assertFalse(user_has_permission(None, 'anything'))

    def test_user_has_any_permission(self):
        self.assertTrue(user_has_any_permission(self.staff, ['properties.view', 'payments.delete']))
        self.assertFalse(user_has_any_permission(self.staff, ['payments.delete', 'reports.view']))

    def test_user_has_all_permissions(self):
        self.assertTrue(user_has_all_permissions(self.staff, ['properties.view', 'properties.create']))
        self.assertFalse(user_has_all_permissions(self.staff, ['properties.view', 'payments.delete']))

    def test_user_has_module_access(self):
        self.assertTrue(user_has_module_access(self.staff, 'properties'))
        self.assertTrue(user_has_module_access(self.staff, 'maintenance'))
        self.assertFalse(user_has_module_access(self.staff, 'payments'))
        self.assertTrue(user_has_module_access(self.master, 'payments'))  # admin

    def test_inactive_role_assignment_ignored(self):
        UserRole.objects.filter(user=self.staff).update(is_active=False)
        perms = get_user_permissions(self.staff)
        self.assertEqual(len(perms), 0)


# =============================================================================
# 2. MODEL TESTS
# =============================================================================

class UserModelTests(TestCase, AccountsTestMixin):
    """Test User model methods and properties."""

    def setUp(self):
        self.user = self._create_test_user('testuser', 'test@test.com', role='facility_manager')

    def test_user_creation(self):
        self.assertEqual(self.user.username, 'testuser')
        self.assertEqual(self.user.email, 'test@test.com')
        self.assertEqual(self.user.role, 'facility_manager')

    def test_role_properties(self):
        self.assertTrue(self.user.is_facility_manager)
        self.assertFalse(self.user.is_master_admin)
        self.assertFalse(self.user.is_super_admin)
        self.assertFalse(self.user.is_tenant)

    def test_can_assign_role_hierarchy(self):
        master = self._create_test_user('m', 'm@t.com', role='master_admin')
        self.assertTrue(master.can_assign_role('super_admin'))
        self.assertTrue(master.can_assign_role('platform_member'))
        self.assertTrue(master.can_assign_role('tenant_vendor'))
        self.assertTrue(master.can_assign_role('tenant'))
        self.assertTrue(self.user.can_assign_role('tenant_vendor'))
        self.assertTrue(self.user.can_assign_role('tenant'))
        self.assertFalse(self.user.can_assign_role('master_admin'))

    def test_generate_otp(self):
        otp = self.user.generate_otp()
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())
        self.user.refresh_from_db()
        self.assertEqual(self.user.otp_code, otp)

    def test_verify_otp_success(self):
        otp = self.user.generate_otp()
        success, message = self.user.verify_otp(otp)
        self.assertTrue(success)

    def test_verify_otp_wrong_code(self):
        self.user.generate_otp()
        success, message = self.user.verify_otp('000000')
        self.assertFalse(success)

    def test_profile_auto_created(self):
        """Signal should auto-create UserProfile."""
        new_user = self._create_test_user('newuser', 'new@test.com')
        self.assertTrue(UserProfile.objects.filter(user=new_user).exists())

    def test_notification_preferences_default(self):
        self.assertEqual(self.user.notification_preferences, {})


class RoleModelTests(TestCase, AccountsTestMixin):
    """Test Role model methods."""

    def setUp(self):
        self.role = self._create_test_role(
            'test_role', 'Test Role', level=40,
            permissions=['properties.view', 'maintenance.view'],
        )

    def test_has_permission(self):
        self.assertTrue(self.role.has_permission('properties.view'))
        self.assertFalse(self.role.has_permission('payments.view'))

    def test_add_permission(self):
        self.role.add_permission('payments.view')
        self.assertIn('payments.view', self.role.permissions)

    def test_add_permission_no_duplicates(self):
        self.role.add_permission('properties.view')
        count = self.role.permissions.count('properties.view')
        self.assertEqual(count, 1)

    def test_remove_permission(self):
        self.role.remove_permission('properties.view')
        self.assertNotIn('properties.view', self.role.permissions)

    def test_set_permissions(self):
        self.role.set_permissions(['a.b', 'c.d', 'a.b'])
        self.assertEqual(set(self.role.permissions), {'a.b', 'c.d'})


class UserRoleModelTests(TestCase, AccountsTestMixin):
    """Test UserRole assignment model."""

    def setUp(self):
        self.user = self._create_test_user('u1', 'u1@test.com', role='tenant')
        self.assigner = self._create_test_user('admin', 'admin@test.com', role='master_admin')
        self.role = self._create_test_role('custom', 'Custom', level=30, permissions=['dashboard.view'])

    def test_assignment_is_valid(self):
        assignment = UserRole.objects.create(
            user=self.user, role=self.role, assigned_by=self.assigner, is_active=True,
        )
        self.assertTrue(assignment.is_valid)

    def test_assignment_inactive_not_valid(self):
        assignment = UserRole.objects.create(
            user=self.user, role=self.role, assigned_by=self.assigner, is_active=False,
        )
        self.assertFalse(assignment.is_valid)

    def test_assignment_expired(self):
        from django.utils import timezone
        from datetime import timedelta
        assignment = UserRole.objects.create(
            user=self.user, role=self.role, assigned_by=self.assigner,
            is_active=True,
            valid_until=timezone.now() - timedelta(days=1),
        )
        self.assertFalse(assignment.is_valid)


class ActivityLogModelTests(TestCase, AccountsTestMixin):
    """Test ActivityLog model."""

    def test_activity_log_creation(self):
        user = self._create_test_user('logger', 'logger@test.com')
        log = ActivityLog.objects.create(
            user=user,
            action='test_action',
            description='Test description',
            ip_address='127.0.0.1',
            tenant_schema='test_schema',
        )
        self.assertEqual(log.action, 'test_action')
        self.assertEqual(log.user, user)


# =============================================================================
# 3. AUTHENTICATION API TESTS
# =============================================================================

@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class AuthenticationAPITests(APITestCase, AccountsTestMixin):
    """Test authentication endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = self._create_test_user(
            'loginuser', 'login@test.com',
            role='facility_manager', password='TestPass123!',
        )

    def test_login_with_email(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'login@test.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertIn('user', response.data)
        self.assertIn('permissions', response.data)

    def test_login_with_username(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'loginuser',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_wrong_password(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'login@test.com',
            'password': 'WrongPassword!',
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_missing_fields(self):
        response = self.client.post('/api/auth/login/', {'email': 'login@test.com'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_nonexistent_user(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'nobody@test.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post('/api/auth/login/', {
            'email': 'login@test.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_login_unapproved_user(self):
        self.user.is_approved = False
        self.user.save()
        response = self.client.post('/api/auth/login/', {
            'email': 'login@test.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_login_role_match_success(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'login@test.com',
            'password': 'TestPass123!',
            'role': 'facility_manager'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_role_mismatch_fails(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'login@test.com',
            'password': 'TestPass123!',
            'role': 'master_admin'
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Role mismatch', response.data['error'])

    def test_login_tenant_no_occupied_unit(self):
        tenant_user = self._create_test_user(
            'tenant_test', 'tenant@test.com',
            role='tenant', password='TestPass123!',
        )
        response = self.client.post('/api/auth/login/', {
            'email': 'tenant@test.com',
            'password': 'TestPass123!',
            'role': 'tenant',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'No unit occupied')

    def test_login_owner_no_occupied_unit(self):
        owner_user = self._create_test_user(
            'owner_test', 'owner@test.com',
            role='owner', password='TestPass123!',
        )
        response = self.client.post('/api/auth/login/', {
            'email': 'owner@test.com',
            'password': 'TestPass123!',
            'role': 'owner',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'No unit occupied')

    @patch('accounts.views.send_welcome_email_async')
    def test_register(self, mock_email):
        mock_email.delay = MagicMock()
        response = self.client.post('/api/auth/register/', {
            'username': 'newuser',
            'email': 'newuser@test.com',
            'password': 'StrongPass123!',
            'password_confirm': 'StrongPass123!',
            'first_name': 'New',
            'last_name': 'User',
            'role': 'tenant',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.data)

    def test_register_cannot_self_assign_admin_role(self):
        response = self.client.post('/api/auth/register/', {
            'username': 'badadmin',
            'email': 'badadmin@test.com',
            'password': 'StrongPass123!',
            'password_confirm': 'StrongPass123!',
            'role': 'master_admin',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_password_mismatch(self):
        response = self.client.post('/api/auth/register/', {
            'username': 'mismatch',
            'email': 'mismatch@test.com',
            'password': 'StrongPass123!',
            'password_confirm': 'DifferentPass123!',
            'role': 'tenant',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_email(self):
        response = self.client.post('/api/auth/register/', {
            'username': 'dup',
            'email': 'login@test.com',
            'password': 'StrongPass123!',
            'password_confirm': 'StrongPass123!',
            'role': 'tenant',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def _authenticate(self, user=None):
        user = user or self.user
        response = self.client.post('/api/auth/login/', {
            'email': user.email,
            'password': 'TestPass123!',
        })
        if response.status_code == 200:
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {response.data["access"]}')
        return response

    def test_current_user(self):
        self._authenticate()
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['username'], 'loginuser')
        self.assertIn('permissions', response.data)

    def test_current_user_unauthenticated(self):
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_change_password(self):
        self._authenticate()
        response = self.client.post('/api/auth/change-password/', {
            'old_password': 'TestPass123!',
            'new_password': 'NewStrongPass123!',
            'new_password_confirm': 'NewStrongPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_change_password_wrong_old(self):
        self._authenticate()
        response = self.client.post('/api/auth/change-password/', {
            'old_password': 'WrongOldPass!',
            'new_password': 'NewStrongPass123!',
            'new_password_confirm': 'NewStrongPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_token_refresh(self):
        login_resp = self.client.post('/api/auth/login/', {
            'email': 'login@test.com',
            'password': 'TestPass123!',
        })
        refresh = login_resp.data['refresh']
        response = self.client.post('/api/auth/token/refresh/', {'refresh': refresh})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    @patch('accounts.views.send_password_reset_email_async')
    def test_request_password_reset(self, mock_email):
        mock_email.delay = MagicMock()
        response = self.client.post('/api/auth/request-password-reset/', {
            'email': 'login@test.com',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_request_password_reset_nonexistent_email(self):
        response = self.client.post('/api/auth/request-password-reset/', {
            'email': 'nobody@test.com',
        })
        # Should not reveal that email doesn't exist
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# =============================================================================
# 4. USER MANAGEMENT API TESTS
# =============================================================================

@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class UserManagementAPITests(APITestCase, AccountsTestMixin):
    """Test user CRUD and management endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.admin = self._create_test_user(
            'admin', 'admin@test.com', role='master_admin', password='TestPass123!',
        )
        self.manager = self._create_test_user(
            'manager', 'manager@test.com', role='facility_manager',
            password='TestPass123!', tenant_id='test_schema',
        )
        self.staff = self._create_test_user(
            'staff', 'staff@test.com', role='property_staff',
            password='TestPass123!', tenant_id='test_schema',
        )
        self.resident = self._create_test_user(
            'resident', 'resident@test.com', role='tenant',
            password='TestPass123!', tenant_id='test_schema',
        )

    def _auth(self, user):
        resp = self.client.post('/api/auth/login/', {
            'email': user.email, 'password': 'TestPass123!',
        })
        if resp.status_code == 200:
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def test_admin_can_list_all_users(self):
        self._auth(self.admin)
        response = self.client.get('/api/auth/users/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_resident_sees_only_self(self):
        self._auth(self.resident)
        response = self.client.get('/api/auth/users/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user_ids = [u['id'] for u in response.data['results']]
        self.assertEqual(len(user_ids), 1)
        self.assertEqual(user_ids[0], str(self.resident.id))

    def test_admin_can_create_user(self):
        self._auth(self.admin)
        response = self.client.post('/api/auth/users/', {
            'username': 'newstaff',
            'email': 'newstaff@test.com',
            'password': 'StrongPass123!',
            'password_confirm': 'StrongPass123!',
            'role': 'property_staff',
            'first_name': 'New',
            'last_name': 'Staff',
        })
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_resident_cannot_create_user(self):
        self._auth(self.resident)
        response = self.client.post('/api/auth/users/', {
            'username': 'hacker',
            'email': 'hacker@test.com',
            'password': 'StrongPass123!',
            'password_confirm': 'StrongPass123!',
            'role': 'tenant',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_approve_user(self):
        self.resident.is_approved = False
        self.resident.save()
        self._auth(self.admin)
        response = self.client.post(f'/api/auth/users/{self.resident.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.resident.refresh_from_db()
        self.assertTrue(self.resident.is_approved)

    def test_bulk_action_activate(self):
        self.resident.is_active = False
        self.resident.save()
        self._auth(self.admin)
        response = self.client.post('/api/auth/users/bulk_action/', {
            'user_ids': [str(self.resident.id)],
            'action': 'activate',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.resident.refresh_from_db()
        self.assertTrue(self.resident.is_active)

    def test_bulk_action_skips_same_level(self):
        """Admin cannot deactivate another admin."""
        other_admin = self._create_test_user('admin2', 'admin2@test.com', role='master_admin')
        self._auth(self.admin)
        response = self.client.post('/api/auth/users/bulk_action/', {
            'user_ids': [str(other_admin.id)],
            'action': 'deactivate',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['updated_count'], 0)

    def test_delete_user_hierarchy(self):
        """Admin can delete lower-level user."""
        self._auth(self.admin)
        response = self.client.delete(f'/api/auth/users/{self.resident.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_cannot_delete_same_level(self):
        """Admin cannot delete another admin."""
        other_admin = self._create_test_user('admin3', 'admin3@test.com', role='master_admin')
        self._auth(self.admin)
        response = self.client.delete(f'/api/auth/users/{other_admin.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_effective_permissions_endpoint(self):
        self._auth(self.admin)
        response = self.client.get(f'/api/auth/users/{self.staff.id}/effective_permissions/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('modules', response.data)
        self.assertIn('role', response.data)


# =============================================================================
# 5. ROLE MANAGEMENT API TESTS
# =============================================================================

@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class RoleManagementAPITests(APITestCase, AccountsTestMixin):
    """Test role CRUD and assignment endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.admin = self._create_test_user(
            'roleadmin', 'roleadmin@test.com', role='master_admin', password='TestPass123!',
        )
        self.manager = self._create_test_user(
            'rolemgr', 'rolemgr@test.com', role='facility_manager', password='TestPass123!',
        )
        self.resident = self._create_test_user(
            'roleresident', 'roleresident@test.com', role='tenant', password='TestPass123!',
        )

    def _auth(self, user):
        resp = self.client.post('/api/auth/login/', {
            'email': user.email, 'password': 'TestPass123!',
        })
        if resp.status_code == 200:
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def test_list_roles(self):
        self._auth(self.resident)
        response = self.client.get('/api/auth/roles/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_custom_role(self):
        self._auth(self.admin)
        response = self.client.post('/api/auth/roles/', {
            'name': 'custom_viewer',
            'display_name': 'Custom Viewer',
            'description': 'Can only view properties',
            'level': 15,
            'permissions': ['properties.view', 'dashboard.view'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'custom_viewer')

    def test_create_role_invalid_permissions(self):
        self._auth(self.admin)
        response = self.client.post('/api/auth/roles/', {
            'name': 'bad_role',
            'display_name': 'Bad Role',
            'level': 15,
            'permissions': ['fake.permission', 'also.fake'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_role_level_too_high(self):
        """Manager (level 70) cannot create role at level 70+."""
        self._auth(self.manager)
        response = self.client.post('/api/auth/roles/', {
            'name': 'too_high',
            'display_name': 'Too High',
            'level': 75,
            'permissions': ['dashboard.view'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resident_cannot_create_role(self):
        self._auth(self.resident)
        response = self.client.post('/api/auth/roles/', {
            'name': 'nope',
            'display_name': 'Nope',
            'level': 5,
            'permissions': [],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_system_role_forbidden(self):
        sys_role = self._create_test_role(
            'sys_test', 'System Test', level=50, is_system=True,
        )
        self._auth(self.admin)
        response = self.client.delete(f'/api/auth/roles/{sys_role.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_role_with_users_fails(self):
        role = self._create_test_role('assigned', 'Assigned Role', level=20, permissions=['dashboard.view'])
        UserRole.objects.create(
            user=self.resident, role=role, assigned_by=self.admin, is_active=True,
        )
        self._auth(self.admin)
        response = self.client.delete(f'/api/auth/roles/{role.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_role_to_user(self):
        role = self._create_test_role(
            'assignable', 'Assignable', level=15,
            permissions=['properties.view', 'maintenance.view'],
        )
        self._auth(self.admin)
        response = self.client.post(f'/api/auth/users/{self.resident.id}/assign_role/', {
            'role': role.id,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(UserRole.objects.filter(user=self.resident, role=role, is_active=True).exists())

    def test_assign_role_hierarchy_enforced(self):
        """Cannot assign roles to same-level users."""
        role = self._create_test_role('mgr_role', 'Manager Role', level=60, permissions=[])
        other_admin = self._create_test_user('admin2r', 'a2r@test.com', role='master_admin')
        self._auth(self.admin)
        response = self.client.post(f'/api/auth/users/{other_admin.id}/assign_role/', {
            'role': role.id,
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_remove_role_from_user(self):
        role = self._create_test_role('removable', 'Removable', level=15, permissions=[])
        assignment = UserRole.objects.create(
            user=self.resident, role=role, assigned_by=self.admin, is_active=True,
        )
        self._auth(self.admin)
        response = self.client.post(f'/api/auth/users/{self.resident.id}/remove_role/', {
            'role_id': role.id,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assignment.refresh_from_db()
        self.assertFalse(assignment.is_active)

    def test_available_permissions_endpoint(self):
        self._auth(self.admin)
        response = self.client.get('/api/auth/roles/available_permissions/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('properties', response.data)
        self.assertIn('payments', response.data)

    def test_assigned_users_endpoint(self):
        role = self._create_test_role('with_users', 'With Users', level=20, permissions=[])
        UserRole.objects.create(user=self.resident, role=role, assigned_by=self.admin, is_active=True)
        self._auth(self.admin)
        response = self.client.get(f'/api/auth/roles/{role.id}/assigned_users/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_update_role_permissions(self):
        role = self._create_test_role(
            'updatable', 'Updatable', level=20,
            permissions=['dashboard.view'],
        )
        self._auth(self.admin)
        response = self.client.patch(f'/api/auth/roles/{role.id}/', {
            'permissions': ['dashboard.view', 'properties.view', 'maintenance.create'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        role.refresh_from_db()
        self.assertIn('properties.view', role.permissions)
        self.assertIn('maintenance.create', role.permissions)


# =============================================================================
# 6. RBAC CHECK ENDPOINT TESTS
# =============================================================================

@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class RBACEndpointTests(APITestCase, AccountsTestMixin):
    """Test RBAC-specific endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.admin = self._create_test_user(
            'rbacadmin', 'rbac@test.com', role='master_admin', password='TestPass123!',
        )
        self.user = self._create_test_user(
            'rbacuser', 'rbacuser@test.com', role='property_staff', password='TestPass123!',
        )
        self.role = self._create_test_role(
            'rbac_test', 'RBAC Test', level=30,
            permissions=['properties.view', 'maintenance.view', 'maintenance.create'],
        )
        UserRole.objects.create(
            user=self.user, role=self.role, assigned_by=self.admin, is_active=True,
        )

    def _auth(self, user):
        resp = self.client.post('/api/auth/login/', {
            'email': user.email, 'password': 'TestPass123!',
        })
        if resp.status_code == 200:
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def test_my_permissions(self):
        self._auth(self.user)
        response = self.client.get('/api/auth/my-permissions/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['role'], 'property_staff')
        self.assertFalse(response.data['is_full_admin'])
        self.assertIn('properties.view', response.data['permissions'])
        self.assertIn('modules', response.data)

    def test_my_permissions_admin_gets_wildcard(self):
        self._auth(self.admin)
        response = self.client.get('/api/auth/my-permissions/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_full_admin'])
        self.assertIn('*', response.data['permissions'])

    def test_check_permissions(self):
        self._auth(self.user)
        response = self.client.post('/api/auth/check-permissions/', {
            'permissions': ['properties.view', 'payments.delete', 'maintenance.create'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['properties.view'])
        self.assertFalse(response.data['payments.delete'])
        self.assertTrue(response.data['maintenance.create'])

    def test_check_permissions_admin_all_true(self):
        self._auth(self.admin)
        response = self.client.post('/api/auth/check-permissions/', {
            'permissions': ['anything.at_all', 'fake.permission'],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['anything.at_all'])

    def test_login_returns_permissions(self):
        response = self.client.post('/api/auth/login/', {
            'email': self.user.email,
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('permissions', response.data)
        self.assertIn('properties.view', response.data['permissions'])


# =============================================================================
# 7. SERIALIZER TESTS
# =============================================================================

class RoleCreateUpdateSerializerTests(TestCase, AccountsTestMixin):
    """Test RoleCreateUpdateSerializer validation."""

    def setUp(self):
        self.admin = self._create_test_user('seradmin', 'seradmin@test.com', role='master_admin')
        self.manager = self._create_test_user('sermgr', 'sermgr@test.com', role='facility_manager')

    def _context(self, user):
        request = MagicMock()
        request.user = user
        return {'request': request}

    def test_valid_role_creation(self):
        data = {
            'name': 'valid_role',
            'display_name': 'Valid Role',
            'level': 20,
            'permissions': ['dashboard.view', 'properties.view'],
        }
        serializer = RoleCreateUpdateSerializer(data=data, context=self._context(self.admin))
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_invalid_name_format(self):
        data = {'name': 'Invalid Name', 'display_name': 'X', 'level': 20, 'permissions': []}
        serializer = RoleCreateUpdateSerializer(data=data, context=self._context(self.admin))
        self.assertFalse(serializer.is_valid())
        self.assertIn('name', serializer.errors)

    def test_level_too_high_for_creator(self):
        data = {'name': 'high', 'display_name': 'High', 'level': 75, 'permissions': []}
        serializer = RoleCreateUpdateSerializer(data=data, context=self._context(self.manager))
        self.assertFalse(serializer.is_valid())
        self.assertIn('level', serializer.errors)

    def test_invalid_permission_codes(self):
        data = {
            'name': 'bad_perms', 'display_name': 'Bad', 'level': 20,
            'permissions': ['nonexistent.perm'],
        }
        serializer = RoleCreateUpdateSerializer(data=data, context=self._context(self.admin))
        self.assertFalse(serializer.is_valid())
        self.assertIn('permissions', serializer.errors)

    def test_deduplicates_permissions(self):
        data = {
            'name': 'dedup', 'display_name': 'Dedup', 'level': 20,
            'permissions': ['dashboard.view', 'dashboard.view', 'properties.view'],
        }
        serializer = RoleCreateUpdateSerializer(data=data, context=self._context(self.admin))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(len(serializer.validated_data['permissions']), 2)


# =============================================================================
# 8. NOTIFICATION PREFERENCES TESTS
# =============================================================================

@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class NotificationPreferencesTests(APITestCase, AccountsTestMixin):
    """Test notification preferences endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = self._create_test_user(
            'notifuser', 'notif@test.com', role='tenant', password='TestPass123!',
        )

    def _auth(self):
        resp = self.client.post('/api/auth/login/', {
            'email': self.user.email, 'password': 'TestPass123!',
        })
        if resp.status_code == 200:
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def test_get_preferences(self):
        self._auth()
        response = self.client.get('/api/auth/notification-preferences/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('notification_preferences', response.data)

    def test_update_preferences(self):
        self._auth()
        prefs = {'email': {'enabled': True}, 'sms': {'enabled': False}}
        response = self.client.put('/api/auth/notification-preferences/', {
            'notification_preferences': prefs,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.notification_preferences['email']['enabled'], True)


# =============================================================================
# 9. ACTIVITY LOG TESTS
# =============================================================================

@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class ActivityLogTests(APITestCase, AccountsTestMixin):
    """Test activity log endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.admin = self._create_test_user(
            'logadmin', 'logadmin@test.com', role='master_admin', password='TestPass123!',
        )
        self.user = self._create_test_user(
            'loguser', 'loguser@test.com', role='tenant', password='TestPass123!',
        )

    def _auth(self, user):
        resp = self.client.post('/api/auth/login/', {
            'email': user.email, 'password': 'TestPass123!',
        })
        if resp.status_code == 200:
            self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def test_login_creates_activity_log(self):
        self.client.post('/api/auth/login/', {
            'email': self.admin.email, 'password': 'TestPass123!',
        })
        self.assertTrue(ActivityLog.objects.filter(user=self.admin, action='user_login').exists())

    def test_user_sees_own_logs(self):
        self._auth(self.user)
        response = self.client.get('/api/auth/activity/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_can_filter_by_action(self):
        self._auth(self.admin)
        response = self.client.get('/api/auth/activity/?action=login')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# =============================================================================
# 10. MANAGEMENT COMMAND TEST
# =============================================================================

class SeedPermissionsCommandTests(TestCase):
    """Test the seed_permissions management command."""

    def test_seed_creates_permissions(self):
        from django.core.management import call_command
        call_command('seed_permissions', '--perms')
        self.assertGreater(Permission.objects.count(), 50)

    def test_seed_creates_roles(self):
        from django.core.management import call_command
        call_command('seed_permissions', '--roles')
        self.assertGreater(Role.objects.count(), 5)
        self.assertTrue(Role.objects.filter(name='master_admin').exists())
        self.assertTrue(Role.objects.filter(name='facility_manager').exists())
        self.assertTrue(Role.objects.filter(name='tenant_resident').exists())

    def test_seed_idempotent(self):
        from django.core.management import call_command
        call_command('seed_permissions')
        count1 = Permission.objects.count()
        call_command('seed_permissions')
        count2 = Permission.objects.count()
        self.assertEqual(count1, count2)

    def test_seed_reset(self):
        from django.core.management import call_command
        call_command('seed_permissions')
        call_command('seed_permissions', '--reset')
        self.assertGreater(Permission.objects.count(), 0)

    def test_seeded_roles_have_permissions(self):
        from django.core.management import call_command
        call_command('seed_permissions')
        fm_role = Role.objects.get(name='facility_manager')
        self.assertIn('properties.view', fm_role.permissions)
        self.assertIn('maintenance.assign', fm_role.permissions)

    def test_tenant_resident_limited_permissions(self):
        from django.core.management import call_command
        call_command('seed_permissions')
        resident_role = Role.objects.get(name='tenant_resident')
        self.assertIn('maintenance.create', resident_role.permissions)
        self.assertNotIn('users.delete', resident_role.permissions)
        self.assertNotIn('roles.create', resident_role.permissions)
