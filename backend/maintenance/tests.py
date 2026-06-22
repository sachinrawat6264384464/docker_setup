# maintenance/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import timedelta, date
from decimal import Decimal
import uuid

from .models import MaintenanceRequest, MaintenanceSchedule, Vendor

User = get_user_model()


class MaintenanceTestMixin:
    """Shared helpers for maintenance tests."""

    def _create_user(self, role='tenant', **kwargs):
        defaults = {
            'username': f'user_{uuid.uuid4().hex[:8]}',
            'email': f'{uuid.uuid4().hex[:8]}@test.com',
            'password': 'TestPass123!',
            'role': role,
            'is_active': True,
        }
        defaults.update(kwargs)
        pw = defaults.pop('password')
        return User.objects.create_user(password=pw, **defaults)

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def _create_request(self, requested_by=None, **kwargs):
        if requested_by is None:
            requested_by = self._create_user()
        defaults = {
            'category': 'plumbing',
            'priority': 'medium',
            'title': 'Leaking faucet',
            'description': 'Kitchen faucet is leaking',
            'requested_by': requested_by,
            'status': 'pending',
        }
        defaults.update(kwargs)
        return MaintenanceRequest.objects.create(**defaults)

    def _create_schedule(self, **kwargs):
        defaults = {
            'title': 'HVAC Filter Change',
            'description': 'Monthly HVAC filter replacement',
            'category': 'hvac',
            'frequency': 'monthly',
            'next_due_date': date.today() + timedelta(days=30),
            'is_active': True,
        }
        defaults.update(kwargs)
        return MaintenanceSchedule.objects.create(**defaults)

    def _create_vendor(self, **kwargs):
        defaults = {
            'name': 'ABC Plumbing',
            'service_type': 'plumbing',
            'contact_person': 'John Doe',
            'phone': '555-0100',
            'email': 'john@abcplumbing.com',
            'is_active': True,
        }
        defaults.update(kwargs)
        return Vendor.objects.create(**defaults)


# =============================================================================
# MODEL TESTS
# =============================================================================

class MaintenanceRequestModelTests(MaintenanceTestMixin, TestCase):

    def test_auto_generated_request_number(self):
        req = self._create_request()
        self.assertTrue(req.request_number.startswith('MR-'))

    def test_unique_request_numbers(self):
        r1 = self._create_request()
        r2 = self._create_request()
        self.assertNotEqual(r1.request_number, r2.request_number)

    def test_default_status(self):
        req = self._create_request()
        self.assertEqual(req.status, 'pending')

    def test_str_representation(self):
        req = self._create_request(title='Fix door')
        self.assertIn('Fix door', str(req))

    def test_cost_fields_default(self):
        req = self._create_request()
        self.assertEqual(req.parts_cost, Decimal('0.00'))
        self.assertEqual(req.labor_cost, Decimal('0.00'))
        self.assertEqual(req.total_cost, Decimal('0.00'))


class MaintenanceScheduleModelTests(MaintenanceTestMixin, TestCase):

    def test_create_schedule(self):
        sch = self._create_schedule()
        self.assertEqual(sch.frequency, 'monthly')
        self.assertTrue(sch.is_active)

    def test_str_representation(self):
        sch = self._create_schedule(title='Pool cleaning')
        self.assertIn('Pool cleaning', str(sch))


class VendorModelTests(MaintenanceTestMixin, TestCase):

    def test_create_vendor(self):
        v = self._create_vendor()
        self.assertTrue(v.is_active)
        self.assertEqual(v.total_jobs, 0)

    def test_str_representation(self):
        v = self._create_vendor(name='Quick Fix')
        self.assertIn('Quick Fix', str(v))


# =============================================================================
# API TESTS
# =============================================================================

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class MaintenanceRequestAPITests(MaintenanceTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.staff = self._create_user(role='maintenance_staff')
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_requests(self):
        self._create_request(requested_by=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/maintenance/requests/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_request(self):
        self._auth(self.tenant)
        data = {
            'category': 'electrical',
            'priority': 'high',
            'title': 'Power outage',
            'description': 'No power in unit 301',
        }
        resp = self.client.post('/api/maintenance/requests/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_retrieve_request(self):
        req = self._create_request(requested_by=self.tenant)
        self._auth(self.admin)
        resp = self.client.get(f'/api/maintenance/requests/{req.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_my_requests_action(self):
        self._create_request(requested_by=self.tenant)
        self._auth(self.tenant)
        resp = self.client.get('/api/maintenance/requests/my-requests/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_update_status_action(self):
        req = self._create_request(requested_by=self.tenant)
        self._auth(self.admin)
        data = {'status': 'in_progress'}
        resp = self.client.patch(f'/api/maintenance/requests/{req.id}/update-status/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_unauthenticated_access(self):
        resp = self.client.get('/api/maintenance/requests/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class MaintenanceScheduleAPITests(MaintenanceTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_schedules(self):
        self._create_schedule()
        self._auth(self.admin)
        resp = self.client.get('/api/maintenance/schedules/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_schedule(self):
        self._auth(self.admin)
        data = {
            'title': 'Elevator check',
            'category': 'elevator',
            'frequency': 'weekly',
            'next_due_date': str(date.today() + timedelta(days=7)),
            'is_active': True,
        }
        resp = self.client.post('/api/maintenance/schedules/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class VendorAPITests(MaintenanceTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_vendors(self):
        self._create_vendor()
        self._auth(self.admin)
        resp = self.client.get('/api/maintenance/vendors/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_vendor(self):
        self._auth(self.admin)
        data = {
            'name': 'Elite Electric',
            'service_type': 'electrical',
            'contact_person': 'Jane',
            'phone': '555-0200',
            'email': 'jane@elite.com',
        }
        resp = self.client.post('/api/maintenance/vendors/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_retrieve_vendor(self):
        v = self._create_vendor()
        self._auth(self.admin)
        resp = self.client.get(f'/api/maintenance/vendors/{v.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
