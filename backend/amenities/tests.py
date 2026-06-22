# amenities/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from decimal import Decimal
from datetime import timedelta, date, time
import uuid

from .models import (
    Amenity, AmenityBooking, AmenityReview,
    AmenityMaintenance, AmenityUsageLog, AmenityRule
)

User = get_user_model()


class AmenitiesTestMixin:
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

    def _create_amenity(self, **kwargs):
        defaults = {
            'name': 'Swimming Pool', 'amenity_type': 'pool',
            'description': 'Olympic size swimming pool',
            'capacity': 50, 'status': 'active', 'is_bookable': True,
            'requires_approval': False, 'is_24_hours': False,
            'max_booking_duration_hours': 2, 'is_paid': True,
            'price_per_hour': Decimal('25.00'),
        }
        defaults.update(kwargs)
        return Amenity.objects.create(**defaults)

    def _create_booking(self, amenity=None, booked_by=None, **kwargs):
        if amenity is None:
            amenity = self._create_amenity()
        if booked_by is None:
            booked_by = self._create_user()
        defaults = {
            'amenity': amenity, 'booked_by': booked_by,
            'booking_date': date.today() + timedelta(days=1),
            'start_time': time(10, 0), 'end_time': time(12, 0),
            'duration_hours': 2, 'number_of_people': 4,
            'purpose': 'Family swim', 'status': 'pending',
        }
        defaults.update(kwargs)
        return AmenityBooking.objects.create(**defaults)


class AmenityModelTests(AmenitiesTestMixin, TestCase):
    def test_create_amenity(self):
        a = self._create_amenity()
        self.assertEqual(a.status, 'active')
        self.assertTrue(a.is_bookable)

    def test_str(self):
        a = self._create_amenity(name='Gym')
        self.assertIn('Gym', str(a))


class AmenityBookingModelTests(AmenitiesTestMixin, TestCase):
    def test_auto_generated_booking_number(self):
        b = self._create_booking()
        self.assertIsNotNone(b.booking_number)
        self.assertTrue(len(b.booking_number) > 0)

    def test_booking_fields(self):
        b = self._create_booking()
        self.assertEqual(b.status, 'pending')
        self.assertEqual(b.number_of_people, 4)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AmenityAPITests(AmenitiesTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_amenities(self):
        self._create_amenity()
        self._auth(self.admin)
        resp = self.client.get('/api/amenities/amenities/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_available_action(self):
        self._create_amenity()
        self._auth(self.tenant)
        resp = self.client.get('/api/amenities/amenities/available/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_amenity_stats(self):
        a = self._create_amenity()
        self._auth(self.admin)
        resp = self.client.get(f'/api/amenities/amenities/{a.id}/stats/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AmenityBookingAPITests(AmenitiesTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.amenity = self._create_amenity()
        self.client = APIClient()

    def test_list_bookings(self):
        self._create_booking(amenity=self.amenity, booked_by=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/amenities/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_my_bookings_action(self):
        self._create_booking(amenity=self.amenity, booked_by=self.tenant)
        self._auth(self.tenant)
        resp = self.client.get('/api/amenities/bookings/my_bookings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_upcoming_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/amenities/bookings/upcoming/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_approve_action(self):
        b = self._create_booking(amenity=self.amenity, booked_by=self.tenant)
        self._auth(self.admin)
        resp = self.client.post(f'/api/amenities/bookings/{b.id}/approve/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_reject_action(self):
        b = self._create_booking(amenity=self.amenity, booked_by=self.tenant)
        self._auth(self.admin)
        data = {'reason': 'Maintenance in progress'}
        resp = self.client.post(f'/api/amenities/bookings/{b.id}/reject/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_cancel_action(self):
        b = self._create_booking(amenity=self.amenity, booked_by=self.tenant, status='approved')
        self._auth(self.tenant)
        resp = self.client.post(f'/api/amenities/bookings/{b.id}/cancel/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AmenityReviewAPITests(AmenitiesTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_reviews(self):
        self._auth(self.admin)
        resp = self.client.get('/api/amenities/reviews/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AmenityMaintenanceAPITests(AmenitiesTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_maintenance(self):
        self._auth(self.admin)
        resp = self.client.get('/api/amenities/maintenance/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AmenityDashboardTests(AmenitiesTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_dashboard(self):
        self._auth(self.admin)
        resp = self.client.get('/api/amenities/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        resp = self.client.get('/api/amenities/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
