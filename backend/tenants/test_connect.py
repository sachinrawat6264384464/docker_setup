from unittest.mock import patch, MagicMock
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django_tenants.utils import schema_context, get_tenant_model
from django.utils import timezone
from accounts.models import User
from tenants.models import Client, Domain
from payments.models import PaymentGateway, WebhookEventLog
import stripe

class StripeConnectTestCase(APITestCase):
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        TenantModel = get_tenant_model()
        cls.public_tenant, created = TenantModel.objects.get_or_create(
            schema_name='public',
            defaults={
                'name': 'Public Schema',
                'contact_email': 'public@system.com',
                'contact_phone': '0000000000',
                'address': 'System Address',
            }
        )
        if created:
            Domain.objects.get_or_create(
                domain='localhost',
                tenant=cls.public_tenant,
                defaults={'is_primary': True}
            )

    def setUp(self):
        self.client = APIClient()
        
        # Create a tenant organization
        self.tenant = Client.objects.create(
            schema_name='test_tenant_connect',
            name='Test Connect HOA',
            contact_email='hoa@test.com',
            contact_phone='1112223333',
            address='123 Main St',
            subscription_plan='premium',
            is_active=True
        )
        
        # Domain mapping
        self.domain = Domain.objects.create(
            domain='connect.localhost',
            tenant=self.tenant,
            is_primary=True
        )
        
        # Create Master Admin user in the tenant schema
        with schema_context('test_tenant_connect'):
            self.master_admin = User.objects.create_user(
                username='master_admin_user',
                email='master@test.com',
                password='MasterPassword123!',
                role='master_admin',
                tenant_id='test_tenant_connect',
                is_active=True
            )
            self.gateway = PaymentGateway.objects.create(gateway_type='stripe', payment_status='PENDING')

    @patch('stripe.Account.create')
    def test_create_connected_account(self, mock_create):
        # Delete existing gateway to simulate first run
        with schema_context('test_tenant_connect'):
            PaymentGateway.objects.filter(gateway_type='stripe').delete()
        
        # Test 1: First creation should succeed
        with patch('tenants.views_connect.stripe.Account.create') as mock_create:
            mock_create.return_value = MagicMock(id='acct_test_mocked123')
            
            self.client.force_authenticate(user=self.master_admin)
            response = self.client.post('/api/system/tenants/connect/create-account/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['account_id'], 'acct_test123')
            self.assertEqual(response.data['status'], 'PENDING')
            
            # Verify gateway was created in db
            gw = PaymentGateway.objects.filter(gateway_type='stripe').first()
            self.assertIsNotNone(gw)
            self.assertEqual(gw.stripe_connected_account_id, 'acct_test123')
            
        # Test 2: Idempotency - calling again should return existing and 400
        response = self.client.post('/api/system/tenants/connect/create-account/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Account already exists')
        
    def test_get_onboarding_link(self):
        """Test POST /api/system/tenants/connect/account-link/ - returns stripe hosted link"""
        
        # Ensure gateway has an account id
        self.gateway.stripe_connected_account_id = 'acct_test123'
        self.gateway.save()
        
        self.client.force_authenticate(user=self.master_admin)
        
        with patch('tenants.views_connect.stripe.AccountLink.create') as mock_link:
            mock_link.return_value = MagicMock(url='https://connect.stripe.com/setup/test')
            
            response = self.client.post('/api/system/tenants/connect/account-link/')
            if response.status_code != 200:
                print("test_get_onboarding_link ERROR RESPONSE:", response.content)
            self.assertEqual(response.status_code, 200)

    @patch('stripe.Account.retrieve')
    def test_get_connect_status(self, mock_account_retrieve):
        """Test GET /api/system/tenants/connect/status/{id}/ - syncs live status from Stripe"""
        with schema_context('test_tenant_connect'):
            self.gateway.stripe_connected_account_id = 'acct_mock123'
            self.gateway.save()
            
        mock_acct = MagicMock()
        mock_acct.charges_enabled = True
        mock_acct.payouts_enabled = True
        mock_account_retrieve.return_value = mock_acct
        
        # Authenticate
        self.client.force_authenticate(user=self.master_admin)
        
        response = self.client.get(f'/api/system/tenants/connect/status/{self.tenant.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['payment_status'], 'ACTIVE')
        self.assertEqual(response.data['charges_enabled'], True)
        
        # Verify db update
        with schema_context('test_tenant_connect'):
            gateway = PaymentGateway.objects.get(gateway_type='stripe')
            self.assertEqual(gateway.charges_enabled, True)
            self.assertEqual(gateway.payouts_enabled, True)
            self.assertEqual(gateway.payment_status, 'ACTIVE')

    @patch('stripe.Webhook.construct_event')
    def test_webhook_account_updated(self, mock_construct_event):
        """Test webhook updates active state on account.updated event"""
        with schema_context('test_tenant_connect'):
            self.gateway.stripe_connected_account_id = 'acct_mock123'
            self.gateway.save()
            
        # Mock webhook event construct
        mock_event = {
            'id': 'evt_mock123',
            'type': 'account.updated',
            'data': {
                'object': {
                    'id': 'acct_mock123',
                    'charges_enabled': True,
                    'payouts_enabled': True,
                    'metadata': {
                        'tenant_schema': 'test_tenant_connect'
                    }
                }
            }
        }
        mock_construct_event.return_value = mock_event
        
        # Set signing secret settings overrides
        with self.settings(STRIPE_CONNECT_WEBHOOK_SECRET='whsec_test'):
            response = self.client.post(
                '/api/system/tenants/connect/webhooks/stripe/connect/',
                data={},
                HTTP_STRIPE_SIGNATURE='t=123,v1=abc'
            )
            
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify DB updated to ACTIVE
        with schema_context('test_tenant_connect'):
            gateway = PaymentGateway.objects.get(gateway_type='stripe')
            self.assertEqual(gateway.charges_enabled, True)
            self.assertEqual(gateway.payouts_enabled, True)
            self.assertEqual(gateway.payment_status, 'ACTIVE')
            self.assertIsNotNone(gateway.onboarding_completed_at)

    @patch('stripe.Webhook.construct_event')
    def test_webhook_idempotency(self, mock_construct_event):
        """Test webhook idempotency rejects duplicate processing"""
        # Register processed event log in db
        with schema_context('public'):
            WebhookEventLog.objects.create(
                stripe_event_id='evt_mock123',
                event_type='account.updated',
                payload={}
            )
            
        mock_construct_event.return_value = {
            'id': 'evt_mock123',
            'type': 'account.updated'
        }
        
        # Webhook should return 200 immediately without hitting DB update handlers
        with self.settings(STRIPE_CONNECT_WEBHOOK_SECRET='whsec_test'):
            response = self.client.post(
                '/api/system/tenants/connect/webhooks/stripe/connect/',
                data={},
                HTTP_STRIPE_SIGNATURE='t=123,v1=abc'
            )
            
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"Already processed")
