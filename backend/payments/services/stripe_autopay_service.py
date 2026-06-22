# payments/services/stripe_autopay_service.py
import stripe
from django.conf import settings
from decimal import Decimal
import logging
from .stripe_service import StripeService

logger = logging.getLogger(__name__)

class StripeAutoPayService(StripeService):
    """
    Stripe auto-pay service for recurring subscription payments.
    Handles Customer creation, Setup Intents (for mandates), and Subscriptions.
    """
    
    def enroll(self, user, amount, frequency='monthly', metadata=None):
        """
        Enroll a user in Stripe auto-pay.
        In Stripe, we usually create a Customer and then a Subscription 
        attached to a Price.
        """
        try:
            # Step 1: Create or get Stripe customer
            customer_result = self.create_or_get_customer(user)
            if not customer_result['success']:
                return customer_result
            
            customer_id = customer_result['customer_id']
            
            # Step 2: For Stripe, we might use Checkout or PaymentElement to collect payment method
            # For direct enrollment, we return the customer_id to the frontend
            return {
                'success': True,
                'customer_id': customer_id,
                'status': 'pending'
            }
        except Exception as e:
            logger.error(f"StripeAutoPayService.enroll failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
            
    def create_subscription(self, customer_id, amount, frequency='monthly', metadata=None):
        """Create a recurring subscription for a customer with Connect fee routing if active"""
        try:
            # 1. Find or create a Price for this amount/frequency
            # In a real app, you might want to reuse existing prices
            amount_unit = int(Decimal(str(amount)) * 100)
            
            # Simplified: Create a dynamic price or use a lookup
            price = stripe.Price.create(
                unit_amount=amount_unit,
                currency='usd',
                recurring={'interval': 'month' if frequency == 'monthly' else 'year'}, # Basic mapping
                product_data={'name': f"HOA Payment - {frequency}"},
            )
            
            # 2. Setup subscription params
            sub_params = {
                'customer': customer_id,
                'items': [{'price': price.id}],
                'metadata': metadata or {},
                'payment_behavior': 'default_incomplete',
                'payment_settings': {'save_default_payment_method': 'on_subscription'},
                'expand': ['latest_invoice.payment_intent'],
            }
            
            connected_acct_id = self.gateway.stripe_connected_account_id
            # Only route via Connect when the HOA account has charges_enabled=True.
            if connected_acct_id and getattr(self.gateway, 'charges_enabled', False):
                # Calculate fee percentage dynamically based on settings
                enabled, fee_percentage = self._get_platform_fee_settings()
                if enabled and fee_percentage > 0:
                    fee_percent = min(100.0, max(0.0, float(fee_percentage)))
                    sub_params['application_fee_percent'] = fee_percent
                sub_params['transfer_data'] = {
                    'destination': connected_acct_id
                }
                from django.db import connection
                sub_params['metadata']['tenant_schema'] = getattr(connection, 'schema_name', 'public')
                sub_params['metadata']['connected_acct'] = connected_acct_id
            
            # 3. Create the subscription
            subscription = stripe.Subscription.create(**sub_params)
            
            # Extract client_secret safely
            client_secret = None
            latest_invoice = getattr(subscription, 'latest_invoice', None)
            if latest_invoice:
                # In newer API versions, payment_intent might be an object if expanded, or just an ID
                pi = getattr(latest_invoice, 'payment_intent', None)
                if pi:
                    if isinstance(pi, str):
                        # If it's just an ID, we might need to retrieve it (but usually expand works)
                        pi_obj = stripe.PaymentIntent.retrieve(pi)
                        client_secret = pi_obj.client_secret
                    else:
                        client_secret = getattr(pi, 'client_secret', None)

            return {
                'success': True,
                'subscription_id': subscription.id,
                'status': subscription.status,
                'client_secret': client_secret
            }
        except Exception as e:
            logger.error(f"Failed to create Stripe subscription: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def cancel(self, subscription_id):
        """Cancel a Stripe subscription"""
        try:
            stripe.Subscription.delete(subscription_id)
            return {'success': True}
        except Exception as e:
            logger.error(f"Failed to cancel Stripe subscription: {str(e)}")
            return {'success': False, 'error': str(e)}

    def pause(self, subscription_id):
        """Pause a Stripe subscription"""
        try:
            stripe.Subscription.modify(
                subscription_id,
                pause_collection={'behavior': 'void'}
            )
            return {'success': True}
        except Exception as e:
            logger.error(f"Failed to pause Stripe subscription: {str(e)}")
            return {'success': False, 'error': str(e)}

    def resume(self, subscription_id):
        """Resume a paused Stripe subscription"""
        try:
            stripe.Subscription.modify(
                subscription_id,
                pause_collection=''
            )
            return {'success': True}
        except Exception as e:
            logger.error(f"Failed to resume Stripe subscription: {str(e)}")
            return {'success': False, 'error': str(e)}
