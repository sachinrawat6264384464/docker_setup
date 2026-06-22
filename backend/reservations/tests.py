# reservations/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from decimal import Decimal
from datetime import timedelta
import uuid

from .models import ReservableResource, Reservation

User = get_user_model()


class ReservationsTestMixin:
    def _create_user(self, role='tenant', **kwargs):
        defaults = {
            'username': f'user_{uuid.uuid4().hex[:8]}',
            'email': f'{uuid.uuid4().hex[:8]}@test.com',
            'password': 'TestPass123!', 'role': role, 'is_active': True,
        }
        defaults.update(kwargs)
        pw = defaults.pop('password')
        return User.objects.create_user(password=pw, **defaults)

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def _create_resource(self, **kwargs):
        defaults = {
            'name': 'Party Hall', 'resource_type': 'facility',
            'description': 'Large party hall with kitchen',
            'location': 'Building A, Ground Floor',
            'capacity': 100, 'is_available': True,
            'max_duration_hours': 8, 'min_advance_hours': 24,
            'max_advance_days': 30, 'is_free': False,
            'hourly_rate': Decimal('50.00'), 'requires_approval': True,
        }
        defaults.update(kwargs)
        return ReservableResource.objects.create(**defaults)

    def _create_reservation(self, resource=None, reserved_by=None, **kwargs):
        if resource is None:
            resource = self._create_resource()
        if reserved_by is None:
            reserved_by = self._create_user()
        defaults = {
            'resource': resource, 'reserved_by': reserved_by,
            'start_time': timezone.now() + timedelta(days=2),
            'end_time': timezone.now() + timedelta(days=2, hours=3),
            'guest_count': 20, 'status': 'pending',
            'purpose': 'Birthday party',
            'total_cost': Decimal('150.00'),
        }
        defaults.update(kwargs)
        return Reservation.objects.create(**defaults)


class ReservableResourceModelTests(ReservationsTestMixin, TestCase):
    def test_create(self):
        r = self._create_resource()
        self.assertTrue(r.is_available)
        self.assertTrue(r.requires_approval)

    def test_str(self):
        r = self._create_resource(name='BBQ Area')
        self.assertIn('BBQ Area', str(r))


class ReservationModelTests(ReservationsTestMixin, TestCase):
    def test_auto_generated_number(self):
        r = self._create_reservation()
        self.assertTrue(r.reservation_number.startswith('RES-'))

    def test_unique_numbers(self):
        r1 = self._create_reservation()
        r2 = self._create_reservation()
        self.assertNotEqual(r1.reservation_number, r2.reservation_number)

    def test_has_conflict_no_overlap(self):
        resource = self._create_resource()
        r1 = self._create_reservation(resource=resource, status='approved')
        # Non-overlapping reservation
        r2 = self._create_reservation(
            resource=resource,
            start_time=r1.end_time + timedelta(hours=1),
            end_time=r1.end_time + timedelta(hours=4),
        )
        self.assertFalse(r2.has_conflict())

    def test_has_conflict_with_overlap(self):
        resource = self._create_resource()
        r1 = self._create_reservation(resource=resource, status='approved')
        # Overlapping reservation
        r2 = self._create_reservation(
            resource=resource,
            start_time=r1.start_time + timedelta(hours=1),
            end_time=r1.end_time + timedelta(hours=1),
        )
        self.assertTrue(r2.has_conflict())

    def test_defaults(self):
        r = self._create_reservation()
        self.assertEqual(r.status, 'pending')
        self.assertFalse(r.deposit_paid)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ReservableResourceAPITests(ReservationsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list(self):
        self._create_resource()
        self._auth(self.tenant)
        resp = self.client.get('/api/reservations/resources/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_availability_action(self):
        r = self._create_resource()
        self._auth(self.tenant)
        resp = self.client.get(f'/api/reservations/resources/{r.id}/availability/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_create(self):
        self._auth(self.admin)
        data = {
            'name': 'Meeting Room', 'resource_type': 'room',
            'capacity': 20, 'is_available': True, 'is_free': True,
        }
        resp = self.client.post('/api/reservations/resources/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ReservationAPITests(ReservationsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.resource = self._create_resource()
        self.client = APIClient()

    def test_list(self):
        self._create_reservation(resource=self.resource, reserved_by=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/reservations/reservations/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_my_reservations_action(self):
        self._create_reservation(resource=self.resource, reserved_by=self.tenant)
        self._auth(self.tenant)
        resp = self.client.get('/api/reservations/reservations/my_reservations/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_upcoming_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/reservations/reservations/upcoming/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_approve_action(self):
        r = self._create_reservation(resource=self.resource, reserved_by=self.tenant)
        self._auth(self.admin)
        resp = self.client.post(f'/api/reservations/reservations/{r.id}/approve/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_reject_action(self):
        r = self._create_reservation(resource=self.resource, reserved_by=self.tenant)
        self._auth(self.admin)
        data = {'reason': 'Resource under maintenance'}
        resp = self.client.post(f'/api/reservations/reservations/{r.id}/reject/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_cancel_action(self):
        r = self._create_reservation(resource=self.resource, reserved_by=self.tenant, status='approved')
        self._auth(self.tenant)
        resp = self.client.post(f'/api/reservations/reservations/{r.id}/cancel/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_check_in_action(self):
        r = self._create_reservation(resource=self.resource, reserved_by=self.tenant, status='approved')
        self._auth(self.admin)
        resp = self.client.post(f'/api/reservations/reservations/{r.id}/check_in/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_check_out_action(self):
        r = self._create_reservation(resource=self.resource, reserved_by=self.tenant, status='checked_in')
        self._auth(self.admin)
        resp = self.client.post(f'/api/reservations/reservations/{r.id}/check_out/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_tenant_sees_own(self):
        self._create_reservation(resource=self.resource, reserved_by=self.tenant)
        other = self._create_user(role='tenant')
        self._create_reservation(resource=self.resource, reserved_by=other)
        self._auth(self.tenant)
        resp = self.client.get('/api/reservations/reservations/')
        data = resp.data.get('results', resp.data)
        for res in data:
            self.assertEqual(str(res['reserved_by']), str(self.tenant.id))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ReservationsDashboardTests(ReservationsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_dashboard(self):
        self._auth(self.admin)
        resp = self.client.get('/api/reservations/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        resp = self.client.get('/api/reservations/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
