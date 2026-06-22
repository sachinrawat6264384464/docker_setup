# notifications/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import timedelta
import uuid

from .models import Notification, NotificationPreference, Announcement

User = get_user_model()


class NotificationsTestMixin:
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

    def _create_notification(self, recipient=None, **kwargs):
        if recipient is None:
            recipient = self._create_user()
        defaults = {
            'recipient': recipient, 'notification_type': 'maintenance',
            'priority': 'medium', 'title': 'Maintenance scheduled',
            'message': 'Unit maintenance scheduled for tomorrow', 'is_read': False,
        }
        defaults.update(kwargs)
        return Notification.objects.create(**defaults)

    def _create_announcement(self, created_by=None, **kwargs):
        if created_by is None:
            created_by = self._create_user(role='master_admin', is_staff=True)
        defaults = {
            'title': 'Community BBQ', 'content': 'Annual community BBQ',
            'audience_type': 'all', 'send_email': True, 'is_published': False,
            'created_by': created_by,
        }
        defaults.update(kwargs)
        return Announcement.objects.create(**defaults)


class NotificationModelTests(NotificationsTestMixin, TestCase):
    def test_create(self):
        n = self._create_notification()
        self.assertFalse(n.is_read)

    def test_mark_as_read(self):
        n = self._create_notification()
        n.mark_as_read()
        n.refresh_from_db()
        self.assertTrue(n.is_read)
        self.assertIsNotNone(n.read_at)

    def test_str(self):
        n = self._create_notification(title='Test')
        self.assertIn('Test', str(n))


class NotificationPreferenceModelTests(NotificationsTestMixin, TestCase):
    def test_create(self):
        user = self._create_user()
        pref = NotificationPreference.objects.create(user=user)
        self.assertTrue(pref.email_enabled)


class AnnouncementModelTests(NotificationsTestMixin, TestCase):
    def test_create(self):
        ann = self._create_announcement()
        self.assertFalse(ann.is_published)

    def test_str(self):
        ann = self._create_announcement(title='Holiday')
        self.assertIn('Holiday', str(ann))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class NotificationAPITests(NotificationsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list(self):
        self._create_notification(recipient=self.tenant)
        self._auth(self.tenant)
        resp = self.client.get('/api/notifications/notifications/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mark_read(self):
        n = self._create_notification(recipient=self.tenant)
        self._auth(self.tenant)
        resp = self.client.post(f'/api/notifications/notifications/{n.id}/mark_read/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mark_all_read(self):
        self._create_notification(recipient=self.tenant)
        self._auth(self.tenant)
        resp = self.client.post('/api/notifications/notifications/mark_all_read/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unread_count(self):
        self._create_notification(recipient=self.tenant)
        self._auth(self.tenant)
        resp = self.client.get('/api/notifications/notifications/unread_count/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        resp = self.client.get('/api/notifications/notifications/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class NotificationPreferenceAPITests(NotificationsTestMixin, APITestCase):
    def setUp(self):
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list(self):
        self._auth(self.tenant)
        resp = self.client.get('/api/notifications/preferences/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AnnouncementAPITests(NotificationsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list(self):
        self._auth(self.admin)
        resp = self.client.get('/api/notifications/announcements/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_publish(self):
        ann = self._create_announcement(created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.post(f'/api/notifications/announcements/{ann.id}/publish/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])
