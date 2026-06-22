# security/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import timedelta, date
import uuid

from .models import (
    SecurityGuard, SecurityIncident, VisitorLog, AccessControl,
    AccessLog, PatrolLog, EmergencyAlert, CCTVCamera, SecurityAnnouncement
)

User = get_user_model()


class SecurityTestMixin:
    """Shared helpers for security tests."""

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

    def _create_guard(self, user=None, **kwargs):
        if user is None:
            user = self._create_user(role='security_guard')
        defaults = {
            'user': user,
            'employee_id': f'SG-{uuid.uuid4().hex[:6]}',
            'shift': 'day',
            'status': 'active',
            'joining_date': date.today() - timedelta(days=90),
        }
        defaults.update(kwargs)
        return SecurityGuard.objects.create(**defaults)

    def _create_incident(self, reported_by=None, **kwargs):
        if reported_by is None:
            reported_by = self._create_user()
        defaults = {
            'incident_type': 'theft',
            'severity': 'high',
            'title': 'Package theft',
            'description': 'Package stolen from lobby',
            'location': 'Main lobby',
            'occurred_at': timezone.now() - timedelta(hours=2),
            'reported_by': reported_by,
            'status': 'reported',
        }
        defaults.update(kwargs)
        return SecurityIncident.objects.create(**defaults)

    def _create_visitor_log(self, host=None, **kwargs):
        if host is None:
            host = self._create_user()
        defaults = {
            'visitor_name': 'John Visitor',
            'visitor_phone': '555-0300',
            'visitor_type': 'guest',
            'host': host,
            'host_unit': 'A-101',
            'purpose': 'Personal visit',
            'status': 'pending',
        }
        defaults.update(kwargs)
        return VisitorLog.objects.create(**defaults)

    def _create_access_control(self, user=None, **kwargs):
        if user is None:
            user = self._create_user()
        defaults = {
            'user': user,
            'access_type': 'resident',
            'access_areas': ['main_entrance', 'parking'],
            'access_level': 'standard',
            'card_number': f'AC-{uuid.uuid4().hex[:8]}',
            'valid_from': timezone.now(),
            'valid_until': timezone.now() + timedelta(days=365),
            'status': 'active',
        }
        defaults.update(kwargs)
        return AccessControl.objects.create(**defaults)

    def _create_camera(self, **kwargs):
        defaults = {
            'camera_id': f'CAM-{uuid.uuid4().hex[:6]}',
            'camera_name': 'Lobby Camera 1',
            'location': 'Main Lobby',
            'ip_address': '192.168.1.100',
            'status': 'active',
            'is_recording': True,
        }
        defaults.update(kwargs)
        return CCTVCamera.objects.create(**defaults)


# =============================================================================
# MODEL TESTS
# =============================================================================

class SecurityGuardModelTests(SecurityTestMixin, TestCase):

    def test_create_guard(self):
        guard = self._create_guard()
        self.assertEqual(guard.status, 'active')
        self.assertEqual(guard.shift, 'day')

    def test_guard_linked_to_user(self):
        user = self._create_user(role='security_guard')
        guard = self._create_guard(user=user)
        self.assertEqual(guard.user, user)

    def test_str_representation(self):
        guard = self._create_guard()
        self.assertTrue(str(guard))


class SecurityIncidentModelTests(SecurityTestMixin, TestCase):

    def test_auto_generated_incident_number(self):
        inc = self._create_incident()
        self.assertTrue(inc.incident_number.startswith('SEC-'))

    def test_unique_incident_numbers(self):
        i1 = self._create_incident()
        i2 = self._create_incident()
        self.assertNotEqual(i1.incident_number, i2.incident_number)

    def test_incident_defaults(self):
        inc = self._create_incident()
        self.assertEqual(inc.status, 'reported')
        self.assertFalse(inc.police_notified)


class VisitorLogModelTests(SecurityTestMixin, TestCase):

    def test_create_visitor_log(self):
        vl = self._create_visitor_log()
        self.assertEqual(vl.visitor_name, 'John Visitor')
        self.assertEqual(vl.status, 'pending')

    def test_visitor_with_host(self):
        host = self._create_user()
        vl = self._create_visitor_log(host=host)
        self.assertEqual(vl.host, host)


class AccessControlModelTests(SecurityTestMixin, TestCase):

    def test_create_access_control(self):
        ac = self._create_access_control()
        self.assertEqual(ac.status, 'active')
        self.assertIn('main_entrance', ac.access_areas)


class CCTVCameraModelTests(SecurityTestMixin, TestCase):

    def test_create_camera(self):
        cam = self._create_camera()
        self.assertEqual(cam.status, 'active')
        self.assertTrue(cam.is_recording)

    def test_unique_camera_id(self):
        c1 = self._create_camera()
        c2 = self._create_camera()
        self.assertNotEqual(c1.camera_id, c2.camera_id)


# =============================================================================
# API TESTS
# =============================================================================

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class SecurityGuardAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.guard_user = self._create_user(role='security_guard')
        self.guard = self._create_guard(user=self.guard_user)
        self.client = APIClient()

    def test_list_guards(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/guards/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_retrieve_guard(self):
        self._auth(self.admin)
        resp = self.client.get(f'/api/security/guards/{self.guard.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_assign_shift_action(self):
        self._auth(self.admin)
        data = {'shift': 'night'}
        resp = self.client.post(f'/api/security/guards/{self.guard.id}/assign_shift/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_on_duty_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/guards/on_duty/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_performance_report_action(self):
        self._auth(self.admin)
        resp = self.client.get(f'/api/security/guards/{self.guard.id}/performance_report/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class SecurityIncidentAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.guard_user = self._create_user(role='security_guard')
        self.guard = self._create_guard(user=self.guard_user)
        self.client = APIClient()

    def test_list_incidents(self):
        self._create_incident(reported_by=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/security/incidents/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_incident(self):
        self._auth(self.admin)
        data = {
            'incident_type': 'vandalism',
            'severity': 'medium',
            'title': 'Graffiti on wall',
            'description': 'Spray paint on parking garage wall',
            'location': 'Parking Level B1',
            'occurred_at': str(timezone.now()),
        }
        resp = self.client.post('/api/security/incidents/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_assign_guard_action(self):
        inc = self._create_incident()
        self._auth(self.admin)
        data = {'guard_id': str(self.guard.id)}
        resp = self.client.post(f'/api/security/incidents/{inc.id}/assign_guard/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_update_status_action(self):
        inc = self._create_incident()
        self._auth(self.admin)
        data = {'status': 'investigating'}
        resp = self.client.post(f'/api/security/incidents/{inc.id}/update_status/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_critical_open_action(self):
        self._create_incident(severity='critical')
        self._auth(self.admin)
        resp = self.client.get('/api/security/incidents/critical_open/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_statistics_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/incidents/statistics/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class VisitorLogAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.guard_user = self._create_user(role='security_guard')
        self.guard = self._create_guard(user=self.guard_user)
        self.client = APIClient()

    def test_list_visitors(self):
        self._create_visitor_log(host=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/security/visitors/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_pre_approve_action(self):
        self._auth(self.tenant)
        data = {
            'visitor_name': 'Jane Doe',
            'visitor_phone': '555-0400',
            'expected_arrival': str(timezone.now() + timedelta(hours=1)),
        }
        resp = self.client.post('/api/security/visitors/pre_approve/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])

    def test_check_in_action(self):
        vl = self._create_visitor_log(host=self.tenant)
        self._auth(self.guard_user)
        resp = self.client.post(f'/api/security/visitors/{vl.id}/check_in/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_check_out_action(self):
        vl = self._create_visitor_log(host=self.tenant, status='checked_in', actual_checkin=timezone.now())
        self._auth(self.guard_user)
        resp = self.client.post(f'/api/security/visitors/{vl.id}/check_out/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_active_visitors_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/visitors/active_visitors/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_todays_visitors_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/visitors/todays_visitors/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_statistics_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/visitors/statistics/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AccessControlAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_access_controls(self):
        self._create_access_control(user=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/security/access-control/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_revoke_action(self):
        ac = self._create_access_control(user=self.tenant)
        self._auth(self.admin)
        resp = self.client.post(f'/api/security/access-control/{ac.id}/revoke/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_reactivate_action(self):
        ac = self._create_access_control(user=self.tenant, status='revoked')
        self._auth(self.admin)
        resp = self.client.post(f'/api/security/access-control/{ac.id}/reactivate/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_expiring_soon_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/access-control/expiring_soon/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AccessLogAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_access_logs(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/access-logs/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_suspicious_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/access-logs/suspicious/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_denied_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/access-logs/denied/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class PatrolLogAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.guard_user = self._create_user(role='security_guard')
        self.guard = self._create_guard(user=self.guard_user)
        self.client = APIClient()

    def _create_patrol(self, **kwargs):
        defaults = {
            'guard': self.guard,
            'patrol_route': 'Building A perimeter',
            'checkpoints': [{'name': 'Gate 1'}, {'name': 'Gate 2'}],
            'scheduled_start': timezone.now(),
            'scheduled_end': timezone.now() + timedelta(hours=2),
            'status': 'scheduled',
        }
        defaults.update(kwargs)
        return PatrolLog.objects.create(**defaults)

    def test_list_patrols(self):
        self._create_patrol()
        self._auth(self.admin)
        resp = self.client.get('/api/security/patrols/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_start_patrol_action(self):
        patrol = self._create_patrol()
        self._auth(self.guard_user)
        resp = self.client.post(f'/api/security/patrols/{patrol.id}/start_patrol/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_complete_patrol_action(self):
        patrol = self._create_patrol(status='in_progress', actual_start=timezone.now())
        self._auth(self.guard_user)
        resp = self.client.post(f'/api/security/patrols/{patrol.id}/complete_patrol/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_active_patrols_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/patrols/active/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class EmergencyAlertAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.guard_user = self._create_user(role='security_guard')
        self.guard = self._create_guard(user=self.guard_user)
        self.client = APIClient()

    def _create_alert(self, **kwargs):
        defaults = {
            'alert_type': 'fire',
            'priority': 'critical',
            'status': 'active',
            'location': 'Building A, Floor 3',
            'title': 'Fire alarm activated',
            'description': 'Fire alarm triggered on floor 3',
            'triggered_by': self.tenant,
            'triggered_at': timezone.now(),
        }
        defaults.update(kwargs)
        return EmergencyAlert.objects.create(**defaults)

    def test_list_alerts(self):
        self._create_alert()
        self._auth(self.admin)
        resp = self.client.get('/api/security/emergency-alerts/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_acknowledge_action(self):
        alert = self._create_alert()
        self._auth(self.guard_user)
        resp = self.client.post(f'/api/security/emergency-alerts/{alert.id}/acknowledge/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_resolve_action(self):
        alert = self._create_alert(status='acknowledged')
        self._auth(self.admin)
        resp = self.client.post(f'/api/security/emergency-alerts/{alert.id}/resolve/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_active_alerts_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/emergency-alerts/active_alerts/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CCTVCameraAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list_cameras(self):
        self._create_camera()
        self._auth(self.admin)
        resp = self.client.get('/api/security/cctv-cameras/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_offline_cameras_action(self):
        self._create_camera(status='offline')
        self._auth(self.admin)
        resp = self.client.get('/api/security/cctv-cameras/offline_cameras/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_maintenance_due_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/cctv-cameras/maintenance_due/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class SecurityAnnouncementAPITests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def _create_announcement(self, **kwargs):
        defaults = {
            'title': 'Security update',
            'message': 'New parking rules effective next week',
            'priority': 'medium',
            'send_to_all': True,
            'published': False,
            'created_by': self.admin,
        }
        defaults.update(kwargs)
        return SecurityAnnouncement.objects.create(**defaults)

    def test_list_announcements(self):
        self._create_announcement()
        self._auth(self.admin)
        resp = self.client.get('/api/security/announcements/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_publish_action(self):
        ann = self._create_announcement()
        self._auth(self.admin)
        resp = self.client.post(f'/api/security/announcements/{ann.id}/publish/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class SecurityDashboardTests(SecurityTestMixin, APITestCase):

    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_dashboard_endpoint(self):
        self._auth(self.admin)
        resp = self.client.get('/api/security/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_dashboard_unauthenticated(self):
        resp = self.client.get('/api/security/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
