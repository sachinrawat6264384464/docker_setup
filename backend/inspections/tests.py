# inspections/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import timedelta, date
import uuid

from .models import InspectionTemplate, Inspection, InspectionPhoto

User = get_user_model()


class InspectionsTestMixin:
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

    def _create_template(self, created_by=None, **kwargs):
        if created_by is None:
            created_by = self._create_user(role='master_admin', is_staff=True)
        defaults = {
            'name': 'Move-in Inspection', 'inspection_type': 'move_in',
            'description': 'Standard move-in checklist',
            'checklist_items': [
                {'label': 'Walls condition', 'required': True, 'category': 'interior'},
                {'label': 'Floor condition', 'required': True, 'category': 'interior'},
                {'label': 'Plumbing check', 'required': True, 'category': 'plumbing'},
            ],
            'is_active': True, 'created_by': created_by,
        }
        defaults.update(kwargs)
        return InspectionTemplate.objects.create(**defaults)

    def _create_inspection(self, template=None, inspector=None, **kwargs):
        if inspector is None:
            inspector = self._create_user(role='facility_manager', is_staff=True)
        if template is None:
            template = self._create_template()
        defaults = {
            'template': template, 'inspection_type': 'move_in',
            'unit_id': uuid.uuid4(), 'building_id': uuid.uuid4(),
            'location_description': 'Unit 301, Building A',
            'scheduled_date': date.today() + timedelta(days=3),
            'inspector': inspector, 'status': 'scheduled',
            'result': 'pending',
        }
        defaults.update(kwargs)
        return Inspection.objects.create(**defaults)


class InspectionTemplateModelTests(InspectionsTestMixin, TestCase):
    def test_create(self):
        t = self._create_template()
        self.assertTrue(t.is_active)
        self.assertEqual(len(t.checklist_items), 3)

    def test_str(self):
        t = self._create_template(name='Safety Check')
        self.assertIn('Safety Check', str(t))


class InspectionModelTests(InspectionsTestMixin, TestCase):
    def test_auto_generated_number(self):
        i = self._create_inspection()
        self.assertTrue(i.inspection_number.startswith('INS-'))

    def test_unique_numbers(self):
        i1 = self._create_inspection()
        i2 = self._create_inspection()
        self.assertNotEqual(i1.inspection_number, i2.inspection_number)

    def test_defaults(self):
        i = self._create_inspection()
        self.assertEqual(i.status, 'scheduled')
        self.assertEqual(i.result, 'pending')
        self.assertFalse(i.follow_up_required)

    def test_str(self):
        i = self._create_inspection()
        self.assertTrue(str(i))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class InspectionTemplateAPITests(InspectionsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list(self):
        self._create_template(created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.get('/api/inspections/templates/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create(self):
        self._auth(self.admin)
        data = {
            'name': 'Fire Safety', 'inspection_type': 'safety',
            'checklist_items': [{'label': 'Smoke detectors', 'required': True}],
            'is_active': True,
        }
        resp = self.client.post('/api/inspections/templates/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class InspectionAPITests(InspectionsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.inspector = self._create_user(role='facility_manager', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.template = self._create_template(created_by=self.admin)
        self.client = APIClient()

    def test_list(self):
        self._create_inspection(template=self.template, inspector=self.inspector)
        self._auth(self.admin)
        resp = self.client.get('/api/inspections/inspections/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_my_inspections_action(self):
        self._create_inspection(template=self.template, inspector=self.inspector)
        self._auth(self.inspector)
        resp = self.client.get('/api/inspections/inspections/my_inspections/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_upcoming_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/inspections/inspections/upcoming/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_overdue_action(self):
        self._auth(self.admin)
        resp = self.client.get('/api/inspections/inspections/overdue/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_start_action(self):
        i = self._create_inspection(template=self.template, inspector=self.inspector)
        self._auth(self.inspector)
        resp = self.client.post(f'/api/inspections/inspections/{i.id}/start/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_complete_action(self):
        i = self._create_inspection(
            template=self.template, inspector=self.inspector, status='in_progress'
        )
        self._auth(self.inspector)
        data = {
            'result': 'pass', 'overall_notes': 'All items satisfactory',
            'score': 95, 'follow_up_required': False,
        }
        resp = self.client.post(f'/api/inspections/inspections/{i.id}/complete/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_cancel_action(self):
        i = self._create_inspection(template=self.template, inspector=self.inspector)
        self._auth(self.admin)
        resp = self.client.post(f'/api/inspections/inspections/{i.id}/cancel/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class InspectionPhotoAPITests(InspectionsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list(self):
        self._auth(self.admin)
        resp = self.client.get('/api/inspections/photos/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class InspectionsDashboardTests(InspectionsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_dashboard(self):
        self._auth(self.admin)
        resp = self.client.get('/api/inspections/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        resp = self.client.get('/api/inspections/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
