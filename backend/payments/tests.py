# payments/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from decimal import Decimal
from datetime import timedelta, date
import uuid
from unittest.mock import patch, MagicMock
from django_tenants.utils import schema_context, get_tenant_model
from tenants.models import Domain

from .models import (
    PaymentGateway, Invoice, Payment, PaymentMethod, Refund,
    PaymentReminder, PaymentPlan, Installment, Transaction,
    AutoPayEnrollment, AutoPaymentLog, RecurringInvoice
)

User = get_user_model()


class PaymentsTestMixin:
    """Shared helpers for payments tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with schema_context('public'):
            # Ensure public tenant exists
            TenantModel = get_tenant_model()
            cls.public_tenant, _ = TenantModel.objects.get_or_create(
                schema_name='public',
                defaults={
                    'name': 'Public Schema',
                    'contact_email': 'public@test.com',
                    'contact_phone': '0000000000',
                }
            )
            Domain.objects.get_or_create(
                domain='localhost',
                tenant=cls.public_tenant,
                defaults={'is_primary': True}
            )

            # Create test tenant
            cls.test_tenant, _ = TenantModel.objects.get_or_create(
                schema_name='test_tenant',
                defaults={
                    'name': 'Test Tenant',
                    'contact_email': 'test@tenant.com',
                    'contact_phone': '1111111111',
                    'subscription_plan': 'premium',
                    'is_active': True
                }
            )
            Domain.objects.get_or_create(
                domain='test.localhost',
                tenant=cls.test_tenant,
                defaults={'is_primary': True}
            )

    def setUp(self):
        super().setUp()
        self.schema_ctx = schema_context('test_tenant')
        self.schema_ctx.__enter__()
        
        # Ensure a gateway exists for all tests
        self.gateway = self._create_gateway(gateway_type='stripe')
        
        # Set HTTP_HOST for tenant awareness (if using a client)
        if hasattr(self, 'client'):
            self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def tearDown(self):
        self.schema_ctx.__exit__(None, None, None)
        super().tearDown()

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
        user = User.objects.create_user(password=pw, **defaults)
        return user

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def _create_gateway(self, **kwargs):
        defaults = {
            'gateway_type': 'razorpay',
            'is_active': True,
            'is_test_mode': True,
            'public_key': 'pk_test_123',
            'secret_key': 'sk_test_123',
            'webhook_secret': 'whsec_test_123',
            'currency': 'USD',
        }
        defaults.update(kwargs)
        gateway_type = defaults.pop('gateway_type')
        obj, _ = PaymentGateway.objects.get_or_create(
            gateway_type=gateway_type,
            defaults=defaults
        )
        return obj

    def _create_invoice(self, user=None, **kwargs):
        if user is None:
            user = self._create_user()
        defaults = {
            'user': user,
            'invoice_type': 'rent',
            'subtotal': Decimal('1000.00'),
            'tax_amount': Decimal('50.00'),
            'tax_percentage': Decimal('5.00'),
            'total_amount': Decimal('1050.00'),
            'amount_due': Decimal('1050.00'),
            'issue_date': date.today(),
            'due_date': date.today() + timedelta(days=30),
            'status': 'sent',
        }
        defaults.update(kwargs)
        return Invoice.objects.create(**defaults)

    def _create_payment(self, user=None, invoice=None, gateway=None, **kwargs):
        if user is None:
            user = self._create_user()
        if invoice is None:
            invoice = self._create_invoice(user=user)
        if gateway is None:
            gateway = self.gateway
            
        defaults = {
            'user': user,
            'invoice': invoice,
            'amount': Decimal('1050.00'),
            'currency': 'USD',
            'payment_method': 'card',
            'status': 'completed',
            'gateway': gateway,
            'gateway_payment_id': f'txn_{uuid.uuid4().hex[:12]}'
        }
        defaults.update(kwargs)
        return Payment.objects.create(**defaults)

    def _create_payment_method(self, user=None, gateway=None, **kwargs):
        if user is None:
            user = self._create_user()
        if gateway is None:
            gateway = self._create_gateway()
        defaults = {
            'user': user,
            'method_type': 'card',
            'gateway': gateway,
            'card_last4': '4242',
            'card_brand': 'Visa',
            'is_default': True,
            'is_verified': True,
        }
        defaults.update(kwargs)
        return PaymentMethod.objects.create(**defaults)

    def _create_refund(self, payment=None, **kwargs):
        if payment is None:
            payment = self._create_payment()
        defaults = {
            'payment': payment,
            'amount': Decimal('100.00'),
            'reason': 'Overcharged',
            'status': 'pending',
            'requested_by': payment.user,
        }
        defaults.update(kwargs)
        return Refund.objects.create(**defaults)

    def _create_payment_plan(self, user=None, invoice=None, **kwargs):
        if user is None:
            user = self._create_user()
        if invoice is None:
            invoice = self._create_invoice(user=user)
        defaults = {
            'user': user,
            'invoice': invoice,
            'total_amount': Decimal('1050.00'),
            'installments': 3,
            'installment_amount': Decimal('350.00'),
            'start_date': date.today(),
            'frequency': 'monthly',
            'status': 'active',
        }
        defaults.update(kwargs)
        return PaymentPlan.objects.create(**defaults)

    def _create_enrollment(self, user=None, **kwargs):
        if user is None:
            user = self._create_user()
        defaults = {
            'user': user,
            'enrollment_type': 'rent',
            'frequency': 'monthly',
            'amount': Decimal('1000.00'),
            'status': 'active',
            'razorpay_subscription_id': f'sub_{uuid.uuid4().hex[:12]}'
        }
        defaults.update(kwargs)
        return AutoPayEnrollment.objects.create(**defaults)


# =============================================================================
# MODEL TESTS
# =============================================================================

class PaymentGatewayModelTests(PaymentsTestMixin, TestCase):

    def test_create_gateway(self):
        gw = self._create_gateway()
        self.assertEqual(gw.gateway_type, 'razorpay')
        self.assertTrue(gw.is_active)
        self.assertTrue(gw.is_test_mode)

    def test_gateway_statistics_defaults(self):
        gw = self._create_gateway()
        self.assertEqual(gw.total_transactions, 0)
        self.assertEqual(gw.successful_transactions, 0)
        self.assertEqual(gw.failed_transactions, 0)

    def test_gateway_str(self):
        gw = self._create_gateway()
        self.assertIn('razorpay', str(gw).lower())


class InvoiceModelTests(PaymentsTestMixin, TestCase):

    def test_auto_generated_invoice_number(self):
        inv = self._create_invoice()
        self.assertTrue(inv.invoice_number.startswith('INV-'))
        self.assertEqual(len(inv.invoice_number), 16)  # INV-YYYYMM-XXXXX

    def test_unique_invoice_numbers(self):
        inv1 = self._create_invoice()
        inv2 = self._create_invoice()
        self.assertNotEqual(inv1.invoice_number, inv2.invoice_number)

    def test_invoice_defaults(self):
        inv = self._create_invoice()
        self.assertEqual(inv.amount_paid, Decimal('0.00'))
        self.assertIsNotNone(inv.created_at)

    def test_invoice_status_choices(self):
        inv = self._create_invoice(status='draft')
        self.assertEqual(inv.status, 'draft')


class PaymentModelTests(PaymentsTestMixin, TestCase):

    def test_auto_generated_payment_number(self):
        pmt = self._create_payment()
        self.assertTrue(pmt.payment_number.startswith('PAY-'))

    def test_payment_linked_to_invoice(self):
        user = self._create_user()
        inv = self._create_invoice(user=user)
        pmt = self._create_payment(user=user, invoice=inv)
        self.assertEqual(pmt.invoice, inv)
        self.assertEqual(pmt.user, user)


class RefundModelTests(PaymentsTestMixin, TestCase):

    def test_auto_generated_refund_number(self):
        ref = self._create_refund()
        self.assertTrue(ref.refund_number.startswith('REF-'))

    def test_refund_linked_to_payment(self):
        pmt = self._create_payment()
        ref = self._create_refund(payment=pmt)
        self.assertEqual(ref.payment, pmt)


class PaymentPlanModelTests(PaymentsTestMixin, TestCase):

    def test_auto_generated_plan_number(self):
        pp = self._create_payment_plan()
        self.assertTrue(pp.plan_number.startswith('PPL-'))

    def test_payment_plan_fields(self):
        pp = self._create_payment_plan()
        self.assertEqual(pp.installments, 3)
        self.assertEqual(pp.status, 'active')


class TransactionModelTests(PaymentsTestMixin, TestCase):

    def test_create_transaction(self):
        user = self._create_user()
        pmt = self._create_payment(user=user)
        txn = Transaction.objects.create(
            transaction_type='payment',
            user=user,
            payment=pmt,
            amount=Decimal('1050.00'),
            currency='USD',
            description='Rent payment',
        )
        self.assertTrue(txn.transaction_number.startswith('TRX-'))
        self.assertEqual(txn.amount, Decimal('1050.00'))


# =============================================================================
# API TESTS
# =============================================================================

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class PaymentGatewayAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def test_list_gateways(self):
        self._create_gateway()
        self._auth(self.admin)
        resp = self.client.get('/api/payments/gateways/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_gateway(self):
        self._auth(self.admin)
        data = {
            'gateway_type': 'paypal',
            'is_active': True,
            'is_test_mode': True,
            'public_key': 'paypal_test_123',
            'secret_key': 'paypal_secret_123',
            'currency': 'USD',
        }
        resp = self.client.post('/api/payments/gateways/', data, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['gateway_type'], 'paypal')

    def test_retrieve_gateway(self):
        gw = self._create_gateway(gateway_type='paypal')
        self._auth(self.admin)
        resp = self.client.get(f'/api/payments/gateways/{gw.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_secret_key_write_only(self):
        gw = self._create_gateway(gateway_type='paypal')
        self._auth(self.admin)
        resp = self.client.get(f'/api/payments/gateways/{gw.id}/')
        self.assertNotIn('secret_key', resp.data)

    @patch('payments.services.stripe_service.StripeService.test_connection')
    def test_test_connection_action(self, mock_test):
        mock_test.return_value = {'success': True, 'message': 'Stripe credentials are valid'}
        gw = self._create_gateway(gateway_type='stripe')
        self._auth(self.admin)
        resp = self.client.post(f'/api/payments/gateways/{gw.id}/test_connection/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unauthenticated_access_denied(self):
        resp = self.client.get('/api/payments/gateways/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class InvoiceAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def test_list_invoices_admin(self):
        self._create_invoice(user=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/payments/invoices/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data.get('results', resp.data)), 1)

    def test_tenant_sees_only_own_invoices(self):
        self._create_invoice(user=self.tenant)
        other = self._create_user(role='tenant')
        self._create_invoice(user=other)
        self._auth(self.tenant)
        resp = self.client.get('/api/payments/invoices/')
        data = resp.data.get('results', resp.data)
        for inv in data:
            self.assertEqual(str(inv['user']), str(self.tenant.id))

    def test_create_invoice(self):
        self._auth(self.admin)
        data = {
            'user': str(self.tenant.id),
            'invoice_type': 'rent',
            'subtotal': '1000.00',
            'building': 'Building A',
            'unit_number': '101',
            'tax_percentage': '5.00',
            'issue_date': str(date.today()),
            'due_date': str(date.today() + timedelta(days=30)),
        }
        resp = self.client.post('/api/payments/invoices/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_send_invoice_action(self):
        inv = self._create_invoice(user=self.tenant, status='draft')
        self._auth(self.admin)
        resp = self.client.post(f'/api/payments/invoices/{inv.id}/send/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_overdue_invoices(self):
        self._create_invoice(
            user=self.tenant,
            due_date=date.today() - timedelta(days=5),
            status='sent'
        )
        self._auth(self.admin)
        resp = self.client.get('/api/payments/invoices/overdue/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_my_invoices(self):
        self._create_invoice(user=self.tenant)
        self._auth(self.tenant)
        resp = self.client.get('/api/payments/invoices/my_invoices/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_filter_by_status(self):
        self._create_invoice(user=self.tenant, status='paid')
        self._auth(self.admin)
        resp = self.client.get('/api/payments/invoices/?status=paid')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class PaymentAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.gateway = self._create_gateway()
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def test_list_payments(self):
        self._create_payment(user=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/payments/payments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_my_payments(self):
        self._create_payment(user=self.tenant)
        self._auth(self.tenant)
        resp = self.client.get('/api/payments/payments/my_payments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    @patch('payments.services.stripe_service.StripeService.create_payment_intent')
    def test_initiate_payment(self, mock_intent):
        mock_intent.return_value = {
            'success': True,
            'client_secret': 'pi_test_secret',
            'intent_id': 'pi_test_123'
        }
        # Configure Stripe gateway so it doesn't bypass routing
        self.gateway.charges_enabled = True
        self.gateway.stripe_connected_account_id = 'acct_123'
        self.gateway.save()

        inv = self._create_invoice(user=self.tenant)
        self._auth(self.tenant)
        data = {
            'invoice_id': str(inv.id),
            'amount': '1050.00',
            'payment_method': 'stripe_card',
            'gateway_type': 'stripe',
        }
        resp = self.client.post('/api/payments/payments/initiate/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])

    def test_unauthenticated_access(self):
        resp = self.client.get('/api/payments/payments/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class PaymentMethodAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.gateway = self._create_gateway()
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def test_list_payment_methods(self):
        self._create_payment_method(user=self.tenant, gateway=self.gateway)
        self._auth(self.tenant)
        resp = self.client.get('/api/payments/payment-methods/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_set_default(self):
        pm = self._create_payment_method(user=self.tenant, gateway=self.gateway, is_default=False)
        self._auth(self.tenant)
        resp = self.client.post(f'/api/payments/payment-methods/{pm.id}/set_default/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RefundAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def test_list_refunds(self):
        pmt = self._create_payment(user=self.tenant)
        self._create_refund(payment=pmt)
        self._auth(self.admin)
        resp = self.client.get('/api/payments/refunds/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_refund(self):
        pmt = self._create_payment(user=self.tenant)
        self._auth(self.admin)
        data = {
            'payment': str(pmt.id),
            'amount': '100.00',
            'reason': 'Partial refund',
        }
        resp = self.client.post('/api/payments/refunds/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_process_refund_action(self):
        pmt = self._create_payment(user=self.tenant)
        ref = self._create_refund(payment=pmt)
        self._auth(self.admin)
        resp = self.client.post(f'/api/payments/refunds/{ref.id}/process/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class PaymentPlanAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def test_list_payment_plans(self):
        self._create_payment_plan(user=self.tenant)
        self._auth(self.admin)
        resp = self.client.get('/api/payments/payment-plans/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_retrieve_payment_plan(self):
        pp = self._create_payment_plan(user=self.tenant)
        self._auth(self.admin)
        resp = self.client.get(f'/api/payments/payment-plans/{pp.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AutoPayEnrollmentAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.pm = self._create_payment_method(user=self.tenant, gateway=self.gateway)
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def _create_enrollment(self, **kwargs):
        defaults = {
            'user': self.tenant,
            'gateway': self.gateway,
            'payment_method': self.pm,
            'enrollment_type': 'rent',
            'frequency': 'monthly',
            'amount': Decimal('1000.00'),
            'start_date': date.today(),
            'next_payment_date': date.today() + timedelta(days=30),
            'status': 'active',
            'razorpay_subscription_id': f'sub_{uuid.uuid4().hex[:12]}'
        }
        defaults.update(kwargs)
        return AutoPayEnrollment.objects.create(**defaults)

    def test_list_enrollments(self):
        self._create_enrollment()
        self._auth(self.admin)
        resp = self.client.get('/api/payments/autopay/enrollments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_my_enrollments(self):
        self._create_enrollment()
        self._auth(self.tenant)
        resp = self.client.get('/api/payments/autopay/enrollments/my_enrollments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    @patch('payments.services.stripe_autopay_service.StripeAutoPayService.pause')
    def test_pause_enrollment(self, mock_pause):
        mock_pause.return_value = {'success': True}
        enr = self._create_enrollment()
        self._auth(self.tenant)
        resp = self.client.post(f'/api/payments/autopay/enrollments/{enr.id}/pause/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    @patch('payments.services.stripe_autopay_service.StripeAutoPayService.resume')
    def test_resume_enrollment(self, mock_resume):
        mock_resume.return_value = {'success': True}
        enr = self._create_enrollment(status='paused')
        self._auth(self.tenant)
        resp = self.client.post(f'/api/payments/autopay/enrollments/{enr.id}/resume/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    @patch('payments.services.stripe_autopay_service.StripeAutoPayService.cancel')
    def test_cancel_enrollment(self, mock_cancel):
        mock_cancel.return_value = {'success': True}
        enr = self._create_enrollment()
        self._auth(self.tenant)
        resp = self.client.post(f'/api/payments/autopay/enrollments/{enr.id}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_auto_generated_enrollment_number(self):
        enr = self._create_enrollment()
        self.assertTrue(enr.enrollment_number.startswith('APE-'))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AutoPaymentLogAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def test_list_logs_readonly(self):
        self._auth(self.admin)
        resp = self.client.get('/api/payments/autopay/logs/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RecurringInvoiceAPITests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def _create_recurring_invoice(self, **kwargs):
        defaults = {
            'user': self.tenant,
            'invoice_type': 'rent',
            'description': 'Monthly rent',
            'subtotal': Decimal('1000.00'),
            'tax_percentage': Decimal('5.00'),
            'frequency': 'monthly',
            'start_date': date.today(),
            'next_invoice_date': date.today() + timedelta(days=30),
            'billing_day': 1,
            'status': 'active',
        }
        defaults.update(kwargs)
        return RecurringInvoice.objects.create(**defaults)

    def test_list_recurring_invoices(self):
        self._create_recurring_invoice()
        self._auth(self.admin)
        resp = self.client.get('/api/payments/recurring-invoices/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_auto_generated_template_number(self):
        ri = self._create_recurring_invoice()
        self.assertTrue(ri.template_number.startswith('RIT-'))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class PaymentDashboardTests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    def test_dashboard_endpoint(self):
        self._auth(self.admin)
        resp = self.client.get('/api/payments/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_dashboard_unauthenticated(self):
        resp = self.client.get('/api/payments/dashboard/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

# =============================================================================
# STRIPE DYNAMIC PLATFORM FEE TESTS
# =============================================================================
from payments.services.stripe_service import StripeService

class StripeServicePlatformFeeTests(PaymentsTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        with schema_context('public'):
            PaymentGateway.objects.filter(gateway_type='stripe').delete()

    def test_default_platform_fee_settings(self):
        # When no config exists, it should fall back to enabled and 2.0%
        service = StripeService(self.gateway)
        enabled, fee_percentage = service._get_platform_fee_settings()
        self.assertTrue(enabled)
        self.assertEqual(fee_percentage, Decimal('2.00'))
        
        # Calculated fee for $100.00 (10000 cents) should be 200 cents
        self.assertEqual(service._get_platform_fee(10000), 200)

    def test_custom_platform_fee_percentage(self):
        # Save custom settings in the public schema gateway
        with schema_context('public'):
            gw, _ = PaymentGateway.objects.get_or_create(gateway_type='stripe')
            gw.settings = {'platform_fee_enabled': True, 'platform_fee_percentage': 3.50}
            gw.save()

        service = StripeService(self.gateway)
        enabled, fee_percentage = service._get_platform_fee_settings()
        self.assertTrue(enabled)
        self.assertEqual(fee_percentage, Decimal('3.50'))
        
        # Calculated fee for $100.00 (10000 cents) should be 350 cents
        self.assertEqual(service._get_platform_fee(10000), 350)

    def test_disabled_platform_fee(self):
        # Save custom settings in the public schema gateway disabling fee
        with schema_context('public'):
            gw, _ = PaymentGateway.objects.get_or_create(gateway_type='stripe')
            gw.settings = {'platform_fee_enabled': False, 'platform_fee_percentage': 5.00}
            gw.save()

        service = StripeService(self.gateway)
        enabled, fee_percentage = service._get_platform_fee_settings()
        self.assertFalse(enabled)
        
        # Calculated fee should be 0 cents
        self.assertEqual(service._get_platform_fee(10000), 0)

    @patch('stripe.PaymentIntent.create')
    def test_create_payment_intent_applies_fee(self, mock_stripe_create):
        mock_stripe_create.return_value = MagicMock(
            id='pi_test_123',
            client_secret='pi_test_secret',
            amount=10000,
            currency='usd',
            status='requires_payment_method'
        )
        
        # Set up a tenant gateway with stripe connected account
        self.gateway.stripe_connected_account_id = 'acct_123'
        self.gateway.charges_enabled = True
        self.gateway.save()
        
        # 1. Enabled platform fee of 3.5%
        with schema_context('public'):
            gw, _ = PaymentGateway.objects.get_or_create(gateway_type='stripe')
            gw.settings = {'platform_fee_enabled': True, 'platform_fee_percentage': 3.50}
            gw.save()
            
        service = StripeService(self.gateway)
        service.create_payment_intent(amount=100.00, currency='USD')
        
        # Verify mocked stripe API received 350 cents application fee
        args, kwargs = mock_stripe_create.call_args
        self.assertEqual(kwargs.get('application_fee_amount'), 350)
        self.assertEqual(kwargs.get('transfer_data', {}).get('destination'), 'acct_123')

    @patch('stripe.PaymentIntent.create')
    def test_create_payment_intent_disabled_fee(self, mock_stripe_create):
        mock_stripe_create.return_value = MagicMock(
            id='pi_test_123',
            client_secret='pi_test_secret',
            amount=10000,
            currency='usd',
            status='requires_payment_method'
        )
        
        # Set up a tenant gateway with stripe connected account
        self.gateway.stripe_connected_account_id = 'acct_123'
        self.gateway.charges_enabled = True
        self.gateway.save()
        
        # 2. Disabled platform fee
        with schema_context('public'):
            gw, _ = PaymentGateway.objects.get_or_create(gateway_type='stripe')
            gw.settings = {'platform_fee_enabled': False, 'platform_fee_percentage': 5.00}
            gw.save()
            
        service = StripeService(self.gateway)
        service.create_payment_intent(amount=100.00, currency='USD')
        
        # Verify mocked stripe API did not receive application_fee_amount
        args, kwargs = mock_stripe_create.call_args
        self.assertNotIn('application_fee_amount', kwargs)
        self.assertEqual(kwargs.get('transfer_data', {}).get('destination'), 'acct_123')

    def test_invoice_creation_adds_platform_fee_line_item(self):
        # 1. Enable platform fee of 2.5% globally
        with schema_context('public'):
            gw, _ = PaymentGateway.objects.get_or_create(gateway_type='stripe')
            gw.settings = {'platform_fee_enabled': True, 'platform_fee_percentage': 2.50}
            gw.save()

        # 2. Create invoice with subtotal $1000 and tax $50
        invoice = self._create_invoice(
            subtotal=Decimal('1000.00'),
            tax_amount=Decimal('50.00'),
            status='draft'
        )

        # Platform fee line item should be auto-calculated: 2.5% of $1000 = $25
        # total_amount = subtotal ($1000) + tax ($50) + platform_fee ($25) = $1075
        self.assertEqual(invoice.total_amount, Decimal('1075.00'))
        
        # Verify line item exists
        platform_fee_items = [item for item in invoice.line_items if item.get('type') == 'platform_fee']
        self.assertEqual(len(platform_fee_items), 1)
        self.assertEqual(platform_fee_items[0]['amount'], 25.00)
        self.assertEqual(platform_fee_items[0]['description'], "Platform Processing Fee (2.50%)")

    @patch('stripe.PaymentIntent.create')
    def test_create_payment_intent_extracts_fee_from_invoice(self, mock_stripe_create):
        mock_stripe_create.return_value = MagicMock(
            id='pi_test_123',
            client_secret='pi_test_secret',
            amount=107500,
            currency='usd',
            status='requires_payment_method'
        )
        
        # Set up a tenant gateway with stripe connected account
        self.gateway.stripe_connected_account_id = 'acct_123'
        self.gateway.charges_enabled = True
        self.gateway.save()
        
        # Enable platform fee of 2.5% globally
        with schema_context('public'):
            gw, _ = PaymentGateway.objects.get_or_create(gateway_type='stripe')
            gw.settings = {'platform_fee_enabled': True, 'platform_fee_percentage': 2.50}
            gw.save()

        # Create invoice
        invoice = self._create_invoice(
            subtotal=Decimal('1000.00'),
            tax_amount=Decimal('50.00'),
            status='sent'
        )

        # Create pending payment
        payment = self._create_payment(
            invoice=invoice,
            amount=invoice.total_amount,
            status='pending',
            gateway=self.gateway
        )

        service = StripeService(self.gateway)
        metadata = {'payment_id': str(payment.id)}
        service.create_payment_intent(amount=invoice.total_amount, currency='USD', metadata=metadata)
        
        # Verify mocked stripe API received exactly the platform fee from the invoice ($25 = 2500 cents)
        args, kwargs = mock_stripe_create.call_args
        self.assertEqual(kwargs.get('application_fee_amount'), 2500)


class StripePlatformKeysFallbackTests(PaymentsTestMixin, APITestCase):

    def setUp(self):
        super().setUp()
        self.tenant_user = self._create_user(role='tenant')
        self.client = APIClient()
        self.client.defaults['HTTP_HOST'] = 'test.localhost'

    @override_settings(
        STRIPE_PLATFORM_SECRET_KEY=None,
        STRIPE_SECRET_KEY=None,
        STRIPE_PLATFORM_PUBLISHABLE_KEY=None,
        STRIPE_PUBLISHABLE_KEY=None
    )
    def test_verify_setup_fallback_to_public_schema_db(self):
        # 1. Create a public schema Stripe gateway with a secret key
        with schema_context('public'):
            PaymentGateway.objects.filter(gateway_type='stripe').delete()
            public_gw = PaymentGateway.objects.create(
                gateway_type='stripe',
                secret_key='sk_public_test_key_123',
                public_key='pk_public_test_key_123',
                is_active=True
            )

        # 2. In tenant schema, have a Stripe Connect gateway (no secret_key, has connected account)
        self.gateway.secret_key = ''
        self.gateway.stripe_connected_account_id = 'acct_tenant_123'
        self.gateway.save()

        # 3. Call get_platform_keys() directly
        from payments.views import get_platform_keys
        secret, pub = get_platform_keys()
        self.assertEqual(secret, 'sk_public_test_key_123')
        self.assertEqual(pub, 'pk_public_test_key_123')

        # 4. Mock stripe SetupIntent.retrieve and verify verify_setup view action uses the fallback key
        self._auth(self.tenant_user)
        with patch('stripe.SetupIntent.retrieve') as mock_retrieve, \
             patch('stripe.PaymentMethod.retrieve') as mock_pm_retrieve:
            
            mock_setup_intent = MagicMock()
            mock_setup_intent.status = 'succeeded'
            mock_setup_intent.payment_method = 'pm_123'
            mock_retrieve.return_value = mock_setup_intent

            mock_pm = MagicMock()
            mock_pm.id = 'pm_123'
            mock_pm.customer = 'cus_123'
            mock_pm.type = 'card'
            mock_pm.card = MagicMock(last4='4242', brand='Visa', exp_month=12, exp_year=2030)
            mock_pm_retrieve.return_value = mock_pm

            response = self.client.post('/api/payments/payment-methods/verify_setup/', {
                'setup_intent_id': 'seti_123',
                'gateway_type': 'stripe'
            }, format='json')

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            import stripe
            # Check that stripe.api_key was set to the public schema's key
            self.assertEqual(stripe.api_key, 'sk_public_test_key_123')

