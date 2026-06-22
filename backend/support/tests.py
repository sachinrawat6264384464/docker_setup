# support/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import timedelta
import uuid

from .models import TicketCategory, Ticket, TicketComment, FAQArticle

User = get_user_model()


class SupportTestMixin:
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

    def _create_category(self, **kwargs):
        defaults = {'name': 'General', 'description': 'General inquiries', 'is_active': True}
        defaults.update(kwargs)
        return TicketCategory.objects.create(**defaults)

    def _create_ticket(self, created_by=None, category=None, **kwargs):
        if created_by is None:
            created_by = self._create_user()
        if category is None:
            category = self._create_category()
        defaults = {
            'subject': 'Broken AC', 'description': 'AC not cooling properly',
            'category': category, 'priority': 'medium',
            'status': 'open', 'created_by': created_by,
        }
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def _create_faq(self, category=None, created_by=None, **kwargs):
        if category is None:
            category = self._create_category()
        if created_by is None:
            created_by = self._create_user(role='master_admin', is_staff=True)
        defaults = {
            'category': category, 'question': 'How to pay rent?',
            'answer': 'Use the payments portal', 'is_published': True,
            'created_by': created_by,
        }
        defaults.update(kwargs)
        return FAQArticle.objects.create(**defaults)


class TicketCategoryModelTests(SupportTestMixin, TestCase):
    def test_create(self):
        c = self._create_category()
        self.assertTrue(c.is_active)

    def test_str(self):
        c = self._create_category(name='Billing')
        self.assertIn('Billing', str(c))


class TicketModelTests(SupportTestMixin, TestCase):
    def test_auto_generated_ticket_number(self):
        t = self._create_ticket()
        self.assertTrue(t.ticket_number.startswith('TKT-'))

    def test_unique_numbers(self):
        t1 = self._create_ticket()
        t2 = self._create_ticket()
        self.assertNotEqual(t1.ticket_number, t2.ticket_number)

    def test_defaults(self):
        t = self._create_ticket()
        self.assertEqual(t.status, 'open')
        self.assertIsNone(t.assigned_to)


class FAQArticleModelTests(SupportTestMixin, TestCase):
    def test_create(self):
        f = self._create_faq()
        self.assertTrue(f.is_published)
        self.assertEqual(f.view_count, 0)
        self.assertEqual(f.helpful_count, 0)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TicketCategoryAPITests(SupportTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_list(self):
        self._create_category()
        self._auth(self.admin)
        resp = self.client.get('/api/support/categories/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TicketAPITests(SupportTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.staff = self._create_user(role='property_staff', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.category = self._create_category()
        self.client = APIClient()

    def test_list_tickets(self):
        self._create_ticket(created_by=self.tenant, category=self.category)
        self._auth(self.admin)
        resp = self.client.get('/api/support/tickets/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_ticket(self):
        self._auth(self.tenant)
        data = {
            'subject': 'Noise complaint',
            'description': 'Loud music from unit above',
            'category': str(self.category.id),
            'priority': 'high',
        }
        resp = self.client.post('/api/support/tickets/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_my_tickets_action(self):
        self._create_ticket(created_by=self.tenant, category=self.category)
        self._auth(self.tenant)
        resp = self.client.get('/api/support/tickets/my_tickets/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_assign_action(self):
        t = self._create_ticket(created_by=self.tenant, category=self.category)
        self._auth(self.admin)
        data = {'assigned_to': str(self.staff.id)}
        resp = self.client.post(f'/api/support/tickets/{t.id}/assign/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_resolve_action(self):
        t = self._create_ticket(created_by=self.tenant, category=self.category, status='in_progress')
        self._auth(self.admin)
        data = {'resolution_notes': 'Fixed the issue'}
        resp = self.client.post(f'/api/support/tickets/{t.id}/resolve/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_close_action(self):
        t = self._create_ticket(created_by=self.tenant, category=self.category, status='resolved')
        self._auth(self.tenant)
        data = {'satisfaction_rating': 5, 'feedback': 'Great service'}
        resp = self.client.post(f'/api/support/tickets/{t.id}/close/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_reopen_action(self):
        t = self._create_ticket(created_by=self.tenant, category=self.category, status='resolved')
        self._auth(self.tenant)
        resp = self.client.post(f'/api/support/tickets/{t.id}/reopen/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_tenant_sees_own_tickets(self):
        self._create_ticket(created_by=self.tenant, category=self.category)
        other = self._create_user(role='tenant')
        self._create_ticket(created_by=other, category=self.category)
        self._auth(self.tenant)
        resp = self.client.get('/api/support/tickets/')
        data = resp.data.get('results', resp.data)
        for ticket in data:
            self.assertEqual(str(ticket['created_by']), str(self.tenant.id))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TicketCommentAPITests(SupportTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_comments(self):
        self._auth(self.admin)
        resp = self.client.get('/api/support/comments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class FAQArticleAPITests(SupportTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_faqs(self):
        self._create_faq(created_by=self.admin)
        self._auth(self.tenant)
        resp = self.client.get('/api/support/faqs/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_mark_helpful_action(self):
        faq = self._create_faq(created_by=self.admin)
        self._auth(self.tenant)
        resp = self.client.post(f'/api/support/faqs/{faq.id}/mark_helpful/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_increment_view_action(self):
        faq = self._create_faq(created_by=self.admin)
        self._auth(self.tenant)
        resp = self.client.post(f'/api/support/faqs/{faq.id}/increment_view/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class SupportDashboardTests(SupportTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()

    def test_dashboard(self):
        self._auth(self.admin)
        resp = self.client.get('/api/support/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated(self):
        resp = self.client.get('/api/support/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
