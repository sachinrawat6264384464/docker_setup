# payments/services/razorpay_service.py
# CONSOLIDATED RAZORPAY SERVICE - All Razorpay functionality in one file

import razorpay
from decimal import Decimal
import hmac
import hashlib
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RazorpayService:
    """
    Complete Razorpay payment service including:
    - Basic payments (one-time)
    - Recurring payments / Auto-pay
    - Subscriptions
    - Refunds
    - Customer management
    - UPI, Cards, Net Banking, Wallets
    """
    
    def __init__(self, gateway):
        self.gateway = gateway
        self.client = razorpay.Client(auth=(gateway.public_key, gateway.secret_key))
    
    # ═══════════════════════════════════════════════════════════════════════
    # BASIC PAYMENT OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    def test_connection(self):
        """Test Razorpay API connection"""
        try:
            # Use a lightweight authenticated call to verify credentials.
            orders = self.client.order.all({'count': 1})
            return {
                'success': True,
                'message': 'Razorpay credentials are valid',
                'orders_fetched': len(orders.get('items', []))
            }
        except Exception as e:
            logger.error(f"Razorpay connection test failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_order(self, amount, currency='INR', metadata=None, customer_id=None):
        """Create a Razorpay order for one-time payment"""
        try:
            # Convert amount to paise (smallest currency unit)
            amount_paise = int(Decimal(str(amount)) * 100)
            
            data = {
                'amount': amount_paise,
                'currency': currency.upper(),
                'notes': metadata or {}
            }
            if customer_id:
                data['customer_id'] = customer_id
            
            order = self.client.order.create(data=data)
            
            return {
                'success': True,
                'order_id': order['id'],
                'amount': order['amount'],  # keep in paise — frontend passes this directly to Razorpay
                'currency': order['currency'],
                'status': order['status'],
                'key_id': self.gateway.public_key,  # required by Razorpay checkout JS
            }
        except Exception as e:
            logger.error(f"Failed to create Razorpay order: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def verify_payment(self, order_id, payment_id, signature):
        """Verify Razorpay payment signature"""
        try:
            # Generate signature
            generated_signature = hmac.new(
                self.gateway.secret_key.encode(),
                f"{order_id}|{payment_id}".encode(),
                hashlib.sha256
            ).hexdigest()
            
            if generated_signature == signature:
                # Fetch payment details
                payment = self.client.payment.fetch(payment_id)
                
                return {
                    'success': True,
                    'payment_id': payment['id'],
                    'order_id': payment['order_id'],
                    'status': payment['status'],
                    'amount': payment['amount'] / 100,
                    'method': payment['method']
                }
            else:
                return {
                    'success': False,
                    'error': 'Invalid payment signature'
                }
        except Exception as e:
            logger.error(f"Failed to verify payment: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def capture_payment(self, payment_id, amount):
        """Capture a payment"""
        try:
            amount_paise = int(Decimal(str(amount)) * 100)
            
            payment = self.client.payment.capture(
                payment_id,
                amount_paise
            )
            
            return {
                'success': True,
                'payment_id': payment['id'],
                'status': payment['status'],
                'amount': payment['amount'] / 100
            }
        except Exception as e:
            logger.error(f"Failed to capture payment: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_refund(self, payment_id, amount=None):
        """Create a refund"""
        try:
            refund_params = {'payment_id': payment_id}
            
            if amount:
                # Convert to paise
                refund_params['amount'] = int(Decimal(str(amount)) * 100)
            
            refund = self.client.payment.refund(payment_id, refund_params)
            
            return {
                'success': True,
                'refund_id': refund['id'],
                'status': refund['status'],
                'amount': refund['amount'] / 100
            }
        except Exception as e:
            logger.error(f"Failed to create refund: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    # ═══════════════════════════════════════════════════════════════════════
    # CUSTOMER MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    def create_customer(self, user):
        """Create a Razorpay customer"""
        try:
            customer = self.client.customer.create(data={
                'name': user.get_full_name(),
                'email': user.email,
                'contact': getattr(user, 'phone', ''),
                'notes': {
                    'user_id': str(user.id),
                    'username': user.username
                }
            })
            return {
                'success': True,
                'customer_id': customer['id']
            }
        except Exception as e:
            logger.error(f"Failed to create Razorpay customer: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_or_get_customer(self, user):
        """Create or retrieve Razorpay customer"""
        try:
            # Check if user already has a customer ID
            from payments.models import AutoPayEnrollment
            existing = AutoPayEnrollment.objects.filter(
                user=user,
                gateway=self.gateway,
                razorpay_customer_id__isnull=False
            ).exclude(razorpay_customer_id='').first()
            
            if existing and existing.razorpay_customer_id:
                try:
                    customer = self.client.customer.fetch(existing.razorpay_customer_id)
                    return {
                        'success': True,
                        'customer_id': customer['id'],
                        'is_new': False
                    }
                except Exception:
                    pass  # Customer not found, create new one
            
            # Try to create new customer
            try:
                customer = self.client.customer.create(data={
                    'name': user.get_full_name(),
                    'email': user.email,
                    'contact': str(getattr(user, 'phone', '')) or '',
                    'notes': {
                        'user_id': str(user.id),
                        'username': user.username
                    }
                })
                is_new = True
            except Exception as e:
                # If customer already exists for merchant, try to find by email
                error_msg = str(e).lower()
                if "already exists" in error_msg:
                    logger.info(f"Customer {user.email} already exists in Razorpay, searching...")
                    customers = self.client.customer.all({'email': user.email})
                    if customers['count'] > 0:
                        customer = customers['items'][0]
                        is_new = False
                    else:
                        raise e
                else:
                    raise e
            
            return {
                'success': True,
                'customer_id': customer['id'],
                'is_new': is_new
            }
        except Exception as e:
            logger.error(f"Failed to create/get Razorpay customer: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    # ═══════════════════════════════════════════════════════════════════════
    # AUTO-PAY / SUBSCRIPTION MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    def create_subscription(self, customer_id, amount, frequency='monthly', metadata=None):
        """Create recurring subscription for auto-pay"""
        try:
            amount_paise = int(Decimal(str(amount)) * 100)
            
            # Map frequency to Razorpay period
            period_map = {
                'monthly': 'monthly',
                'quarterly': 'monthly',  # Will use count
                'semi_annual': 'monthly',
                'annual': 'yearly'
            }
            
            period_count_map = {
                'monthly': 1,
                'quarterly': 3,
                'semi_annual': 6,
                'annual': 1
            }
            
            # Create plan first
            plan = self.client.plan.create(data={
                'period': period_map.get(frequency, 'monthly'),
                'interval': period_count_map.get(frequency, 1),
                'item': {
                    'name': metadata.get('product_name', 'Recurring Payment') if metadata else 'Recurring Payment',
                    'amount': amount_paise,
                    'currency': self.gateway.currency.upper(),
                },
                'notes': metadata or {}
            })
            
            # Create subscription
            subscription = self.client.subscription.create(data={
                'plan_id': plan['id'],
                'customer_id': customer_id,
                'quantity': 1,
                'total_count': 120,  # 120 months (10 years) limit since 0 is not allowed
                'notes': metadata or {}
            })
            
            return {
                'success': True,
                'subscription_id': subscription['id'],
                'plan_id': plan['id'],
                'status': subscription['status'],
                'start_at': datetime.fromtimestamp(subscription['start_at']) if subscription.get('start_at') else None,
                'charge_at': datetime.fromtimestamp(subscription['charge_at']) if subscription.get('charge_at') else None
            }
        except Exception as e:
            logger.error(f"Failed to create subscription: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def cancel_subscription(self, subscription_id, cancel_at_period_end=True):
        """Cancel subscription"""
        try:
            subscription = self.client.subscription.cancel(subscription_id, data={
                'cancel_at_cycle_end': 1 if cancel_at_period_end else 0
            })
            
            return {
                'success': True,
                'subscription_id': subscription['id'],
                'status': subscription['status'],
                'cancelled_at': datetime.fromtimestamp(subscription.get('cancelled_at', 0)) if subscription.get('cancelled_at') else None
            }
        except Exception as e:
            logger.error(f"Failed to cancel subscription: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def pause_subscription(self, subscription_id):
        """Pause subscription"""
        try:
            subscription = self.client.subscription.pause(subscription_id)
            
            return {
                'success': True,
                'subscription_id': subscription['id'],
                'status': subscription['status']
            }
        except Exception as e:
            logger.error(f"Failed to pause subscription: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def resume_subscription(self, subscription_id):
        """Resume paused subscription"""
        try:
            subscription = self.client.subscription.resume(subscription_id)
            
            return {
                'success': True,
                'subscription_id': subscription['id'],
                'status': subscription['status']
            }
        except Exception as e:
            logger.error(f"Failed to resume subscription: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def update_subscription_amount(self, subscription_id, new_amount):
        """Update subscription amount"""
        try:
            amount_paise = int(Decimal(str(new_amount)) * 100)
            
            # Get current subscription
            subscription = self.client.subscription.fetch(subscription_id)
            
            # Update subscription
            updated_subscription = self.client.subscription.update(subscription_id, data={
                'quantity': 1,
                'schedule_change_at': 'now'
            })
            
            return {
                'success': True,
                'subscription_id': updated_subscription['id'],
                'status': updated_subscription['status']
            }
        except Exception as e:
            logger.error(f"Failed to update subscription amount: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    # ═══════════════════════════════════════════════════════════════════════
    # OFF-SESSION PAYMENTS (AUTO-PAY)
    # ═══════════════════════════════════════════════════════════════════════
    
    def charge_customer_off_session(self, customer_id, amount, metadata=None, token_id=None):
        """Charge customer automatically using saved payment method (token)"""
        try:
            amount_paise = int(Decimal(str(amount)) * 100)
            
            if token_id:
                # Actual recurring charge using Token API
                # POST /payments/create/recurring
                # Note: email and contact are required by Razorpay for this call
                # We try to get them from metadata or user object if available
                email = metadata.get('email', '') if metadata else ''
                contact = metadata.get('contact', '') if metadata else ''
                
                payment_data = {
                    'amount': amount_paise,
                    'currency': self.gateway.currency.upper(),
                    'customer_id': customer_id,
                    'token': token_id,
                    'notes': metadata or {},
                    'recurring': 1
                }
                
                if email:
                    payment_data['email'] = email
                if contact:
                    payment_data['contact'] = contact
                
                # Create recurring payment
                payment = self.client.payment.create_recurring(payment_data)
                
                logger.info(f"Successfully charged customer {customer_id} off-session. Payment: {payment['id']}")
                
                return {
                    'success': True,
                    'payment_id': payment['id'],
                    'order_id': payment.get('order_id'),
                    'amount': float(payment['amount']) / 100 if 'amount' in payment else amount,
                    'status': payment['status']
                }
            else:
                # Off-session recurring charge requires a saved mandate token.
                logger.warning(f"No token_id provided for off-session charge (customer: {customer_id}).")
                return {
                    'success': False,
                    'error': 'Token is required for off-session recurring charge',
                    'error_code': 'token_required',
                    'requires_action': True
                }
        except Exception as e:
            logger.error(f"Failed to charge customer off-session: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'requires_action': False
            }
    
    # ═══════════════════════════════════════════════════════════════════════
    # PAYMENT METHOD MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_payment_methods(self, customer_id):
        """Get payment methods for a customer"""
        try:
            customer = self.client.customer.fetch(customer_id)
            
            return {
                'success': True,
                'customer': customer
            }
        except Exception as e:
            logger.error(f"Failed to get payment methods: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_payment_link(self, amount, description, customer_id=None, metadata=None):
        """Create payment link for easy payment"""
        try:
            amount_paise = int(Decimal(str(amount)) * 100)
            
            payment_link = self.client.payment_link.create(data={
                'amount': amount_paise,
                'currency': self.gateway.currency.upper(),
                'description': description,
                'customer': {
                    'id': customer_id
                } if customer_id else None,
                'notes': metadata or {}
            })
            
            return {
                'success': True,
                'payment_link_id': payment_link['id'],
                'short_url': payment_link['short_url'],
                'amount': amount
            }
        except Exception as e:
            logger.error(f"Failed to create payment link: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    # ═══════════════════════════════════════════════════════════════════════
    # WEBHOOK HANDLING
    # ═══════════════════════════════════════════════════════════════════════
    
    def handle_webhook(self, payload, signature):
        """Handle Razorpay webhook events"""
        try:
            # Verify webhook signature
            expected_signature = hmac.new(
                self.gateway.webhook_secret.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()
            
            if expected_signature == signature:
                import json
                event_data = json.loads(payload)
                event_type = event_data.get('event')
                
                # Handle payment events
                if event_type == 'payment.captured':
                    payment = event_data.get('payload', {}).get('payment', {}).get('entity', {})
                    return {
                        'success': True,
                        'event': 'payment_captured',
                        'payment_id': payment.get('id')
                    }
                
                elif event_type == 'payment.failed':
                    payment = event_data.get('payload', {}).get('payment', {}).get('entity', {})
                    return {
                        'success': True,
                        'event': 'payment_failed',
                        'payment_id': payment.get('id')
                    }
                
                # Handle subscription events
                elif event_type == 'subscription.charged':
                    subscription = event_data.get('payload', {}).get('subscription', {}).get('entity', {})
                    return {
                        'success': True,
                        'event': 'subscription_charged',
                        'subscription_id': subscription.get('id')
                    }
                
                elif event_type == 'subscription.cancelled':
                    subscription = event_data.get('payload', {}).get('subscription', {}).get('entity', {})
                    return {
                        'success': True,
                        'event': 'subscription_cancelled',
                        'subscription_id': subscription.get('id')
                    }
                
                elif event_type == 'subscription.paused':
                    subscription = event_data.get('payload', {}).get('subscription', {}).get('entity', {})
                    return {
                        'success': True,
                        'event': 'subscription_paused',
                        'subscription_id': subscription.get('id')
                    }
                
                elif event_type == 'subscription.resumed':
                    subscription = event_data.get('payload', {}).get('subscription', {}).get('entity', {})
                    return {
                        'success': True,
                        'event': 'subscription_resumed',
                        'subscription_id': subscription.get('id')
                    }
                
                # Handle refund events
                elif event_type == 'refund.created':
                    refund = event_data.get('payload', {}).get('refund', {}).get('entity', {})
                    return {
                        'success': True,
                        'event': 'refund_created',
                        'refund_id': refund.get('id')
                    }
                
                return {
                    'success': True,
                    'event': event_type
                }
            else:
                return {
                    'success': False,
                    'error': 'Invalid webhook signature'
                }
        
        except Exception as e:
            logger.error(f"Webhook error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    # ═══════════════════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════════════════
    
    def fetch_payment(self, payment_id):
        """Fetch payment details"""
        try:
            payment = self.client.payment.fetch(payment_id)
            return {
                'success': True,
                'payment': payment
            }
        except Exception as e:
            logger.error(f"Failed to fetch payment: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def fetch_subscription(self, subscription_id):
        """Fetch subscription details"""
        try:
            subscription = self.client.subscription.fetch(subscription_id)
            return {
                'success': True,
                'subscription': subscription
            }
        except Exception as e:
            logger.error(f"Failed to fetch subscription: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }