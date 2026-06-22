# payments/services/razorpay_autopay_service.py
# Razorpay Auto-Pay Service

from decimal import Decimal
from datetime import datetime
import json
import hmac
import hashlib
import logging

from .razorpay_service import RazorpayService

logger = logging.getLogger(__name__)


class RazorpayAutoPayService(RazorpayService):
    """
    Razorpay auto-pay service for recurring subscription payments.
    Extends the base RazorpayService with auto-pay specific operations:
    - Enrollment (create customer + plan + subscription)
    - Cancel / Pause / Resume subscriptions
    - Off-session payment processing
    - Webhook handling for subscription events
    """

    # ===================================================================
    # ENROLLMENT
    # ===================================================================

    def enroll(self, user, amount, frequency='monthly', metadata=None):
        """
        Enroll a user in Razorpay auto-pay.
        Creates a customer (or retrieves existing), creates a plan,
        and creates a subscription.

        Returns dict with success, customer_id, subscription_id, plan_id.
        """
        try:
            # Step 1: Create or get Razorpay customer
            customer_result = self.create_or_get_customer(user)
            if not customer_result['success']:
                return customer_result

            customer_id = customer_result['customer_id']

            # Step 2: Create plan + subscription
            subscription_result = self.create_subscription(
                customer_id=customer_id,
                amount=amount,
                frequency=frequency,
                metadata=metadata
            )

            if not subscription_result['success']:
                return subscription_result

            return {
                'success': True,
                'customer_id': customer_id,
                'subscription_id': subscription_result['subscription_id'],
                'plan_id': subscription_result['plan_id'],
                'status': subscription_result['status'],
            }
        except Exception as e:
            logger.error(f"RazorpayAutoPayService.enroll failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    # ===================================================================
    # CANCEL
    # ===================================================================

    def cancel(self, subscription_id, cancel_at_period_end=True):
        """
        Cancel a Razorpay subscription.
        Delegates to the base cancel_subscription method.
        """
        try:
            return self.cancel_subscription(
                subscription_id,
                cancel_at_period_end=cancel_at_period_end
            )
        except Exception as e:
            logger.error(f"RazorpayAutoPayService.cancel failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    # ===================================================================
    # PAUSE
    # ===================================================================

    def pause(self, subscription_id):
        """
        Pause a Razorpay subscription.
        Delegates to the base pause_subscription method.
        """
        try:
            return self.pause_subscription(subscription_id)
        except Exception as e:
            logger.error(f"RazorpayAutoPayService.pause failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    # ===================================================================
    # RESUME
    # ===================================================================

    def resume(self, subscription_id):
        """
        Resume a paused Razorpay subscription.
        Delegates to the base resume_subscription method.
        """
        try:
            return self.resume_subscription(subscription_id)
        except Exception as e:
            logger.error(f"RazorpayAutoPayService.resume failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    # ===================================================================
    # PROCESS PAYMENT (off-session charge)
    # ===================================================================

    def process_payment(self, customer_id, amount, metadata=None):
        """
        Process an off-session payment for a Razorpay customer.
        Creates an order that can be auto-captured via subscription billing.
        """
        try:
            result = self.charge_customer_off_session(
                customer_id=customer_id,
                amount=amount,
                metadata=metadata
            )
            return result
        except Exception as e:
            logger.error(f"RazorpayAutoPayService.process_payment failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    # ===================================================================
    # WEBHOOK HANDLING
    # ===================================================================

    def handle_webhook(self, payload, signature):
        """
        Handle Razorpay webhook events for auto-pay / subscriptions.
        Verifies the signature and parses subscription-specific events.

        Supported events:
        - subscription.charged
        - subscription.halted
        - subscription.cancelled
        - subscription.paused
        - subscription.resumed
        - subscription.pending
        - payment.captured
        - payment.failed
        """
        try:
            # Verify webhook signature
            expected_signature = hmac.new(
                self.gateway.webhook_secret.encode('utf-8'),
                payload.encode('utf-8') if isinstance(payload, str) else payload,
                hashlib.sha256
            ).hexdigest()

            if isinstance(signature, str):
                sig_to_compare = signature
            else:
                sig_to_compare = signature.decode('utf-8')

            if expected_signature != sig_to_compare:
                logger.error("RazorpayAutoPayService webhook: invalid signature")
                return {
                    'success': False,
                    'error': 'Invalid webhook signature'
                }

            event_data = json.loads(payload) if isinstance(payload, str) else json.loads(payload.decode('utf-8'))
            event_type = event_data.get('event', '')

            # --- Subscription events ---
            if event_type == 'subscription.charged':
                subscription_entity = (
                    event_data.get('payload', {})
                    .get('subscription', {}).get('entity', {})
                )
                payment_entity = (
                    event_data.get('payload', {})
                    .get('payment', {}).get('entity', {})
                )
                return {
                    'success': True,
                    'event': 'subscription_charged',
                    'subscription_id': subscription_entity.get('id'),
                    'plan_id': subscription_entity.get('plan_id'),
                    'payment_id': payment_entity.get('id'),
                    'amount_paid': Decimal(str(payment_entity.get('amount', 0))) / 100,
                    'status': subscription_entity.get('status'),
                }

            elif event_type == 'subscription.halted':
                subscription_entity = (
                    event_data.get('payload', {})
                    .get('subscription', {}).get('entity', {})
                )
                return {
                    'success': True,
                    'event': 'subscription_halted',
                    'subscription_id': subscription_entity.get('id'),
                    'plan_id': subscription_entity.get('plan_id'),
                    'status': subscription_entity.get('status'),
                }

            elif event_type == 'subscription.cancelled':
                subscription_entity = (
                    event_data.get('payload', {})
                    .get('subscription', {}).get('entity', {})
                )
                return {
                    'success': True,
                    'event': 'subscription_cancelled',
                    'subscription_id': subscription_entity.get('id'),
                    'plan_id': subscription_entity.get('plan_id'),
                    'status': subscription_entity.get('status'),
                }

            elif event_type == 'subscription.paused':
                subscription_entity = (
                    event_data.get('payload', {})
                    .get('subscription', {}).get('entity', {})
                )
                return {
                    'success': True,
                    'event': 'subscription_paused',
                    'subscription_id': subscription_entity.get('id'),
                    'plan_id': subscription_entity.get('plan_id'),
                    'status': subscription_entity.get('status'),
                }

            elif event_type == 'subscription.resumed':
                subscription_entity = (
                    event_data.get('payload', {})
                    .get('subscription', {}).get('entity', {})
                )
                return {
                    'success': True,
                    'event': 'subscription_resumed',
                    'subscription_id': subscription_entity.get('id'),
                    'plan_id': subscription_entity.get('plan_id'),
                    'status': subscription_entity.get('status'),
                }

            elif event_type == 'subscription.pending':
                subscription_entity = (
                    event_data.get('payload', {})
                    .get('subscription', {}).get('entity', {})
                )
                return {
                    'success': True,
                    'event': 'subscription_pending',
                    'subscription_id': subscription_entity.get('id'),
                    'plan_id': subscription_entity.get('plan_id'),
                    'status': subscription_entity.get('status'),
                }

            # --- Payment events (auto-pay related) ---
            elif event_type == 'payment.captured':
                payment_entity = (
                    event_data.get('payload', {})
                    .get('payment', {}).get('entity', {})
                )
                return {
                    'success': True,
                    'event': 'payment_captured',
                    'payment_id': payment_entity.get('id'),
                    'amount': Decimal(str(payment_entity.get('amount', 0))) / 100,
                }

            elif event_type == 'payment.failed':
                payment_entity = (
                    event_data.get('payload', {})
                    .get('payment', {}).get('entity', {})
                )
                return {
                    'success': True,
                    'event': 'payment_failed',
                    'payment_id': payment_entity.get('id'),
                    'error_description': payment_entity.get('error_description', 'Payment failed'),
                }

            # Unhandled event type
            return {
                'success': True,
                'event': event_type
            }

        except Exception as e:
            logger.error(f"RazorpayAutoPayService.handle_webhook error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
