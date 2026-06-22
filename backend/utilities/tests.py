# utilities/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from decimal import Decimal
from datetime import timedelta, date
import uuid

from .models import (
    UtilityType, UtilityBill, UtilityMeterReading,
    UtilityProvider, BuildingUtilityConnection,
    InsuranceProvider, BuildingInsurance
)

User = get_user_model()


class UtilitiesTestMixin:

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

    def _create_utility_type(self, **kwargs):
        defaults = {
            'name': 'Electricity',
            'category': 'electric',
            'unit_of_measurement': 'kWh',
            'base_rate': Decimal('0.12'),
            'is_active': True,
        }
        defaults.update(kwargs)
        return UtilityType.objects.create(**defaults)

    def _create_provider(self, **kwargs):
        defaults = {
            'name': 'City Power Corp',
            'utility_category': 'electric',
            'contact_person': 'Bob Smith',
            'contact_email': 'bob@citypower.com',
            'contact_phone': '555-0500',
            'is_active': True,
        }
        defaults.update(kwargs)
        return UtilityProvider.objects.create(**defaults)

    def _create_bill(self, utility_type=None, tenant=None, **kwargs):
        if utility_type is None:
            utility_type = self._create_utility_type()
        if tenant is None:
            tenant = self._create_user()
        defaults = {
            'utility_type': utility_type,
            'tenant': tenant,
            'billing_period_start': date.today() - timedelta(days=30),
            'billing_period_end': date.today(),
            'previous_reading': Decimal('1000.00'),
            'current_reading': Decimal('1200.00'),
            'consumption': Decimal('200.00'),
            'rate_per_unit': Decimal('0.12'),
            'base_amount': Decimal('24.00'),
            'tax_amount': Decimal('2.40'),
            'total_amount': Decimal('26.40'),
            'due_date': date.today() + timedelta(days=15),
            'status': 'pending',
        }
        defaults.update(kwargs)
        return UtilityBill.objects.create(**defaults)


# =============================================================================
# MODEL TESTS
# =============================================================================

class UtilityTypeModelTests(UtilitiesTestMixin, TestCase):

    def test_create_utility_type(self):
        ut = self._create_utility_type()
        self.assertEqual(ut.name, 'Electricity')
        self.assertTrue(ut.is_active)

    def test_str_representation(self):
        ut = self._create_utility_type(name='Water')
        self.assertIn('Water', str(ut))


class UtilityBillModelTests(UtilitiesTestMixin, TestCase):

    def test_auto_generated_bill_number(self):
        bill = self._create_bill()
        self.assertIsNotNone(bill.bill_number)
        self.assertTrue(len(bill.bill_number) > 0)

    def test_bill_fields(self):
        bill = self._create_bill()
        self.assertEqual(bill.status, 'pending')
        self.assertEqual(bill.consumption, Decimal('200.00'))


class UtilityProviderModelTests(UtilitiesTestMixin, TestCase):

    def test_create_provider(self):
        p = self._create_provider()
        self.assertTrue(p.is_active)
        self.assertEqual(p.name, 'City Power Corp')


# =============================================================================
# API TESTS
# =============================================================================

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class UtilityTypeAPITests(UtilitiesTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_types(self):
        self._create_utility_type()
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/types/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_active_types(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/types/active/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_type(self):
        self._auth(self.admin)
        data = {'name': 'Gas', 'category': 'gas', 'unit_of_measurement': 'therms', 'base_rate': '0.50'}
        resp = self.client.post('/api/utilities/types/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class UtilityBillAPITests(UtilitiesTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_bills(self):
        self._create_bill(tenant=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/bills/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mark_paid_action(self):
        bill = self._create_bill(tenant=self.tenant)
        self._auth(self.admin)
        resp = self.client.post(f'/api/utilities/bills/{bill.id}/mark_paid/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_pending_bills(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/bills/pending/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_overdue_bills(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/bills/overdue/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_due_soon_bills(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/bills/due_soon/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class UtilityProviderAPITests(UtilitiesTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_providers(self):
        self._create_provider()
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/providers/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_active_providers(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/providers/active/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class UtilityMeterReadingAPITests(UtilitiesTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_readings(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/readings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_latest_readings(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/readings/latest/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class UtilityDashboardTests(UtilitiesTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_dashboard_stats(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_consumption_report(self):
        self._auth(self.admin)
        resp = self.client.get('/api/utilities/reports/consumption/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        resp = self.client.get('/api/utilities/dashboard/stats/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
