# calendar_alerts/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import timedelta
import uuid

from .models import CalendarAlert, AlertRecipient

User = get_user_model()


class CalendarAlertsTestMixin:
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

    def _create_alert(self, created_by=None, **kwargs):
        if created_by is None:
            created_by = self._create_user(role='master_admin', is_staff=True)
        defaults = {
            'title': 'Water shutdown', 'description': 'Planned water maintenance',
            'alert_type': 'maintenance', 'priority': 'high', 'status': 'upcoming',
            'start_datetime': timezone.now() + timedelta(hours=2),
            'end_datetime': timezone.now() + timedelta(hours=6),
            'notify_tenants': True, 'created_by': created_by,
        }
        defaults.update(kwargs)
        return CalendarAlert.objects.create(**defaults)


class CalendarAlertModelTests(CalendarAlertsTestMixin, TestCase):
    def test_create_alert(self):
        a = self._create_alert()
        self.assertEqual(a.alert_type, 'maintenance')
        self.assertEqual(a.priority, 'high')

    def test_str(self):
        a = self._create_alert(title='Power outage')
        self.assertIn('Power outage', str(a))


class AlertRecipientModelTests(CalendarAlertsTestMixin, TestCase):
    def test_create_recipient(self):
        alert = self._create_alert()
        user = self._create_user()
        r = AlertRecipient.objects.create(alert=alert, user=user)
        self.assertFalse(r.is_read)
        self.assertFalse(r.notification_sent)

    def test_unique_constraint(self):
        alert = self._create_alert()
        user = self._create_user()
        AlertRecipient.objects.create(alert=alert, user=user)
        with self.assertRaises(Exception):
            AlertRecipient.objects.create(alert=alert, user=user)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CalendarAlertAPITests(CalendarAlertsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_alerts(self):
        self._create_alert(created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.get('/api/calendar-alerts/alerts/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_today_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/calendar-alerts/alerts/today/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_upcoming_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/calendar-alerts/alerts/upcoming/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_active_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/calendar-alerts/alerts/active/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mark_completed_action(self):
        alert = self._create_alert(created_by=self.admin, status='active')
        self._auth(self.admin)
        resp = self.client.post(f'/api/calendar-alerts/alerts/{alert.id}/mark_completed/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_cancel_action(self):
        alert = self._create_alert(created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.post(f'/api/calendar-alerts/alerts/{alert.id}/cancel/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AlertRecipientAPITests(CalendarAlertsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_recipients(self):
        self._auth(self.admin)
        resp = self.client.get('/api/calendar-alerts/recipients/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mark_read_action(self):
        alert = self._create_alert(created_by=self.admin)
        r = AlertRecipient.objects.create(alert=alert, user=self.tenant)
        self._auth(self.tenant)
        resp = self.client.post(f'/api/calendar-alerts/recipients/{r.id}/mark_read/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_unread_action(self):
        self._auth(self.tenant)
        resp = self.client.get('/api/calendar-alerts/recipients/unread/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mark_all_read_action(self):
        self._auth(self.tenant)
        resp = self.client.post('/api/calendar-alerts/recipients/mark_all_read/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CalendarDashboardTests(CalendarAlertsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_dashboard(self):
        self._auth(self.admin)
        resp = self.client.get('/api/calendar-alerts/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
