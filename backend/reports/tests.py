# reports/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import timedelta, date
import uuid

from .models import ReportTemplate, GeneratedReport, ScheduledReport

User = get_user_model()


class ReportsTestMixin:
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
            'name': 'Monthly Financial Report', 'description': 'Financial summary',
            'report_type': 'financial', 'columns': ['amount', 'date', 'category'],
            'filters': {'date_range': 'monthly'}, 'is_system': False,
            'is_active': True, 'created_by': created_by,
        }
        defaults.update(kwargs)
        return ReportTemplate.objects.create(**defaults)

    def _create_generated_report(self, template=None, generated_by=None, **kwargs):
        if generated_by is None:
            generated_by = self._create_user(role='master_admin', is_staff=True)
        if template is None:
            template = self._create_template(created_by=generated_by)
        defaults = {
            'template': template, 'name': 'Jan 2025 Financial',
            'report_type': 'financial', 'output_format': 'pdf',
            'parameters': {}, 'date_from': date.today() - timedelta(days=30),
            'date_to': date.today(), 'status': 'completed',
            'generated_by': generated_by,
        }
        defaults.update(kwargs)
        return GeneratedReport.objects.create(**defaults)

    def _create_scheduled_report(self, template=None, created_by=None, **kwargs):
        if created_by is None:
            created_by = self._create_user(role='master_admin', is_staff=True)
        if template is None:
            template = self._create_template(created_by=created_by)
        defaults = {
            'template': template, 'name': 'Weekly occupancy',
            'frequency': 'weekly', 'output_format': 'pdf',
            'is_active': True, 'next_run': timezone.now() + timedelta(days=7),
            'created_by': created_by,
        }
        defaults.update(kwargs)
        return ScheduledReport.objects.create(**defaults)


class ReportTemplateModelTests(ReportsTestMixin, TestCase):
    def test_create(self):
        t = self._create_template()
        self.assertTrue(t.is_active)
        self.assertEqual(t.report_type, 'financial')

    def test_str(self):
        t = self._create_template(name='Occupancy')
        self.assertIn('Occupancy', str(t))


class GeneratedReportModelTests(ReportsTestMixin, TestCase):
    def test_auto_generated_number(self):
        r = self._create_generated_report()
        self.assertTrue(r.report_number.startswith('RPT-'))

    def test_unique_numbers(self):
        r1 = self._create_generated_report()
        r2 = self._create_generated_report()
        self.assertNotEqual(r1.report_number, r2.report_number)


class ScheduledReportModelTests(ReportsTestMixin, TestCase):
    def test_create(self):
        s = self._create_scheduled_report()
        self.assertTrue(s.is_active)
        self.assertEqual(s.frequency, 'weekly')


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ReportTemplateAPITests(ReportsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list(self):
        self._create_template(created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.get('/api/reports/templates/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create(self):
        self._auth(self.admin)
        data = {
            'name': 'Payment Report', 'report_type': 'payment',
            'columns': ['amount', 'status'], 'is_active': True,
        }
        resp = self.client.post('/api/reports/templates/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class GeneratedReportAPITests(ReportsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.template = self._create_template(created_by=self.admin)
        self.client = APIClient()

    def test_list(self):
        self._create_generated_report(template=self.template, generated_by=self.admin)
        self._auth(self.admin)
        resp = self.client.get('/api/reports/generated/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_generate_action(self):
        self._auth(self.admin)
        data = {
            'template': str(self.template.id), 'name': 'Q1 Report',
            'output_format': 'csv',
            'date_from': str(date.today() - timedelta(days=90)),
            'date_to': str(date.today()),
        }
        resp = self.client.post('/api/reports/generated/generate/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])

    def test_download_action(self):
        r = self._create_generated_report(template=self.template, generated_by=self.admin)
        self._auth(self.admin)
        resp = self.client.get(f'/api/reports/generated/{r.id}/download/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_regenerate_action(self):
        r = self._create_generated_report(template=self.template, generated_by=self.admin)
        self._auth(self.admin)
        resp = self.client.post(f'/api/reports/generated/{r.id}/regenerate/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ScheduledReportAPITests(ReportsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.template = self._create_template(created_by=self.admin)
        self.client = APIClient()

    def test_list(self):
        self._create_scheduled_report(template=self.template, created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.get('/api/reports/scheduled/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_toggle_active_action(self):
        s = self._create_scheduled_report(template=self.template, created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.post(f'/api/reports/scheduled/{s.id}/toggle_active/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_run_now_action(self):
        s = self._create_scheduled_report(template=self.template, created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.post(f'/api/reports/scheduled/{s.id}/run_now/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ReportsDashboardTests(ReportsTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_dashboard(self):
        self._auth(self.admin)
        resp = self.client.get('/api/reports/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        resp = self.client.get('/api/reports/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
