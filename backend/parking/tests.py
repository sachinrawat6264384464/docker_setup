# parking/tests.py
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import date, timedelta
import uuid

from .models import ParkingSlot, Vehicle, ParkingPass, ParkingEntry

User = get_user_model()


class ParkingTestMixin:
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

    def _create_slot(self, **kwargs):
        defaults = {
            'slot_number': f'P-{uuid.uuid4().hex[:4]}',
            'slot_type': 'standard', 'floor': '1', 'section': 'A',
            'status': 'available',
        }
        defaults.update(kwargs)
        return ParkingSlot.objects.create(**defaults)

    def _create_vehicle(self, owner=None, **kwargs):
        if owner is None:
            owner = self._create_user()
        defaults = {
            'owner': owner, 'vehicle_type': 'car', 'make': 'Toyota',
            'model': 'Camry', 'year': 2023, 'color': 'Blue',
            'license_plate': f'ABC-{uuid.uuid4().hex[:4]}',
            'is_active': True,
        }
        defaults.update(kwargs)
        return Vehicle.objects.create(**defaults)

    def _create_pass(self, user=None, vehicle=None, slot=None, **kwargs):
        if user is None:
            user = self._create_user()
        if vehicle is None:
            vehicle = self._create_vehicle(owner=user)
        if slot is None:
            slot = self._create_slot()
        defaults = {
            'pass_number': f'PP-{uuid.uuid4().hex[:6]}',
            'user': user, 'vehicle': vehicle, 'parking_slot': slot,
            'valid_from': date.today(), 'valid_until': date.today() + timedelta(days=365),
            'status': 'active',
        }
        defaults.update(kwargs)
        return ParkingPass.objects.create(**defaults)


class ParkingSlotModelTests(ParkingTestMixin, TestCase):
    def test_create_slot(self):
        s = self._create_slot()
        self.assertEqual(s.status, 'available')

    def test_str(self):
        s = self._create_slot(slot_number='P-001')
        self.assertIn('P-001', str(s))


class VehicleModelTests(ParkingTestMixin, TestCase):
    def test_create_vehicle(self):
        v = self._create_vehicle()
        self.assertTrue(v.is_active)
        self.assertEqual(v.make, 'Toyota')

    def test_vehicle_owner(self):
        user = self._create_user()
        v = self._create_vehicle(owner=user)
        self.assertEqual(v.owner, user)


class ParkingPassModelTests(ParkingTestMixin, TestCase):
    def test_create_pass(self):
        p = self._create_pass()
        self.assertEqual(p.status, 'active')


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ParkingSlotAPITests(ParkingTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_slots(self):
        self._create_slot()
        self._auth(self.admin)
        resp = self.client.get('/api/parking/slots/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_available_action(self):
        self._create_slot(status='available')
        self._auth(self.admin)
        resp = self.client.get('/api/parking/slots/available/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_slot(self):
        self._auth(self.admin)
        data = {'slot_number': 'P-NEW', 'slot_type': 'compact', 'floor': '2', 'section': 'B'}
        resp = self.client.post('/api/parking/slots/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class VehicleAPITests(ParkingTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_vehicles(self):
        self._create_vehicle(owner=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/parking/vehicles/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_vehicle(self):
        self._auth(self.tenant)
        data = {
            'vehicle_type': 'suv', 'make': 'Honda', 'model': 'CRV',
            'year': 2024, 'color': 'White', 'license_plate': 'XYZ-1234',
        }
        resp = self.client.post('/api/parking/vehicles/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ParkingPassAPITests(ParkingTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_passes(self):
        self._auth(self.admin)
        resp = self.client.get('/api/parking/passes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ParkingEntryAPITests(ParkingTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_entries(self):
        self._auth(self.admin)
        resp = self.client.get('/api/parking/entries/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        resp = self.client.get('/api/parking/entries/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
