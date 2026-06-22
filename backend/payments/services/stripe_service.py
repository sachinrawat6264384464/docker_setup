# payments/services/stripe_service.py
import stripe
from django.conf import settings
from decimal import Decimal
import logging
import json
from django.utils import timezone

logger = logging.getLogger(__name__)

class StripeService:
    """
    Stripe payment service implementation.
    Handles PaymentIntents, Refunds, and Customer management.
    """
    
    def __init__(self, gateway):
        self.gateway = gateway
        
        # Resolve platform keys with fallback
        platform_key = getattr(settings, 'STRIPE_PLATFORM_SECRET_KEY', None) or getattr(settings, 'STRIPE_SECRET_KEY', None)
        platform_pub_key = getattr(settings, 'STRIPE_PLATFORM_PUBLISHABLE_KEY', None) or getattr(settings, 'STRIPE_PUBLISHABLE_KEY', None)
        
        if not platform_key or not platform_pub_key:
            from django_tenants.utils import schema_context
            from payments.models import PaymentGateway
            with schema_context('public'):
                gw = PaymentGateway.objects.filter(gateway_type='stripe').first()
                if gw:
                    if not platform_key:
                        platform_key = gw.secret_key
                    if not platform_pub_key:
                        platform_pub_key = gw.public_key
                        
        self.platform_key = platform_key
        self.platform_pub_key = platform_pub_key
        
        if gateway.stripe_connected_account_id:
            stripe.api_key = self.platform_key
        else:
            stripe.api_key = gateway.secret_key or self.platform_key
            
    def _get_platform_fee_settings(self):
        """
        Fetch platform fee settings from public PaymentGateway settings.
        Returns:
            (enabled: bool, fee_percentage: Decimal)
        """
        from django_tenants.utils import schema_context
        from payments.models import PaymentGateway
        
        enabled = True
        fee_type = 'flat'
        fee_amount = Decimal('2.00')
        
        with schema_context('public'):
            try:
                global_gateway = PaymentGateway.objects.filter(gateway_type='stripe').first()
                if global_gateway:
                    settings_dict = global_gateway.settings or {}
                    enabled = settings_dict.get('platform_fee_enabled', True)
                    fee_type = settings_dict.get('platform_fee_type', 'flat')
                    fee_amount_val = settings_dict.get('platform_fee_amount', settings_dict.get('platform_fee_percentage', 2.0))
                    fee_amount = Decimal(str(fee_amount_val))
            except Exception as e:
                logger.error(f"Error reading platform fee settings: {e}")
                
        return enabled, fee_type, fee_amount

    def _get_platform_fee(self, amount_cents):
        """
        Calculate platform application fee based on fixed amount. 
        Capped at amount - 50 cents to ensure destination is positive.
        """
        enabled, fee_type, fee_amount = self._get_platform_fee_settings()
        if not enabled:
            return 0
        if fee_type == 'percentage':
            fee_amount_cents = int((amount_cents * float(fee_amount)) / 100)
        else:
            fee_amount_cents = int(fee_amount * Decimal('100'))
        return min(fee_amount_cents, max(0, amount_cents - 50))
    
    def test_connection(self):
        """Test Stripe API connection"""
        try:
            params = {'limit': 1}
            # If connect is active, test connection to the connected account
            if self.gateway.stripe_connected_account_id:
                params['stripe_account'] = self.gateway.stripe_connected_account_id
            stripe.PaymentIntent.list(**params)
            return {
                'success': True,
                'message': 'Stripe credentials are valid'
            }
        except Exception as e:
            logger.error(f"Stripe connection test failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_payment_intent(self, amount, payment_method_type, currency='USD', metadata=None, customer_id=None):
        """
        Create a Stripe PaymentIntent for one-time payment.
        Uses Separate Charges and Transfers (transfer_group) for 3-way split support.
        
        We use explicit `payment_method_types` instead of `automatic_payment_methods`
        so that we can later restrict payment to the exact method the resident selected.
        This prevents fee-mismatch (e.g. resident selects Bank fee=1% but pays with Card).
        """
        try:
            base_amount = Decimal(str(amount))
            total_with_fee = round(base_amount, 2)
            
            amount_unit = int(total_with_fee * 100)
            base_amount_unit = int(base_amount * 100)
            processing_fee_unit = 0
            
            # Use payment_id or invoice_id as transfer_group
            payment_id = (metadata or {}).get('payment_id', 'unknown')
            transfer_group = f"group_{payment_id}"
            
            if metadata is not None:
                metadata['base_amount'] = base_amount_unit
                metadata['processing_fee'] = processing_fee_unit
                metadata['transfer_group'] = transfer_group
            
            # Map our internal category to Stripe's payment_method_types.
            # Card intent explicitly includes cashapp + amazon_pay so they appear
            # in the PaymentElement. Link's "pay by bank" tab (which CashApp can
            # bundle) is suppressed via wallets.link='never' in the frontend.
            if payment_method_type == 'us_bank_account':
                allowed_methods = ['us_bank_account']
            elif payment_method_type == 'klarna':
                allowed_methods = ['klarna']
            else:
                # card + cashapp + amazon_pay (strictly no bank/klarna)
                allowed_methods = ['card', 'cashapp', 'amazon_pay']
            
            params = {
                'amount': amount_unit,
                'currency': currency.lower(),
                'metadata': metadata or {},
                'payment_method_types': allowed_methods,
                'transfer_group': transfer_group
            }
            
            if customer_id:
                params['customer'] = customer_id
                
            connected_acct_id = self.gateway.stripe_connected_account_id
            
            if not connected_acct_id or not getattr(self.gateway, 'charges_enabled', False):
                return {
                    'success': False,
                    'error': 'Stripe Connect is not fully configured by the master admin. Contact the master admin for enabling this feature.'
                }
            
            if metadata is not None:
                from django.db import connection
                params['metadata']['tenant_schema'] = getattr(connection, 'schema_name', 'public')
                if connected_acct_id:
                    params['metadata']['connected_acct'] = connected_acct_id
            
            try:
                intent = stripe.PaymentIntent.create(**params)
            except stripe.error.InvalidRequestError as e:
                err_msg = str(e).lower()
                if payment_method_type in ('us_bank_account', 'klarna'):
                    # No fallback for dedicated methods.
                    raise e
                # cashapp or amazon_pay not enabled on this account — strip and retry
                if any(m in err_msg for m in ('cashapp', 'amazon_pay', 'payment_method_types')):
                    params['payment_method_types'] = ['card']
                    intent = stripe.PaymentIntent.create(**params)
                else:
                    raise e

            
            pub_key = self.platform_pub_key if connected_acct_id else self.gateway.public_key
            
            return {
                'success': True,
                'intent_id': intent.id,
                'client_secret': intent.client_secret,
                'amount': intent.amount,
                'currency': intent.currency,
                'status': intent.status,
                'publishable_key': pub_key,
            }
        except Exception as e:
            logger.error(f"Failed to create Stripe PaymentIntent: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def update_payment_intent(self, intent_id, amount, metadata=None, payment_method_type=None):
        """
        Update an existing Stripe PaymentIntent when payment method or amount changes.
        
        For NEW intents (created with explicit payment_method_types), this also updates
        payment_method_types to lock the intent to only the selected method — preventing
        fee mismatch (e.g. resident selects Bank fee=1% but pays with Card).
        
        For OLD intents created with automatic_payment_methods, we gracefully skip
        the payment_method_types update (Stripe does not allow mixing the two).
        """
        try:
            amount_unit = int(Decimal(str(amount)) * 100)
            
            params = {
                'amount': amount_unit,
            }
            if metadata is not None:
                params['metadata'] = metadata
            
            # Lock payment method type on new-style intents.
            # Card uses ['card','cashapp','amazon_pay'] — Link bank tab is
            # suppressed on the frontend via wallets.link='never'.
            if payment_method_type == 'us_bank_account':
                params['payment_method_types'] = ['us_bank_account']
            elif payment_method_type == 'klarna':
                params['payment_method_types'] = ['klarna']
            else:
                params['payment_method_types'] = ['card', 'cashapp', 'amazon_pay']
            
            try:
                intent = stripe.PaymentIntent.modify(intent_id, **params)
            except stripe.error.InvalidRequestError as stripe_err:
                err_msg = str(stripe_err).lower()
                
                # Stripe often prohibits changing `payment_method_types` on an existing intent.
                # If we hit any error related to payment_method_types, we must recreate the intent.
                if 'automatic_payment_methods' in err_msg or 'payment_method_types' in err_msg or 'cannot change' in err_msg:
                    logger.warning(f"PaymentIntent {intent_id} cannot update payment_method_types; requires recreation.")
                    return {'success': False, 'requires_recreate': True}
                
                raise stripe_err
                
            return {
                'success': True,
                'intent_id': intent.id,
                'client_secret': intent.client_secret,
                'amount': intent.amount,
                'currency': intent.currency,
                'status': intent.status,
            }
        except Exception as e:
            logger.error(f"Failed to update Stripe PaymentIntent {intent_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def cancel_payment_intent(self, intent_id):
        """
        Cancel a Stripe PaymentIntent.
        Used when user switches payment method (card ↔ bank) so we can create a
        fresh intent with the correct payment_method_types restriction.
        Non-fatal: logs a warning but does not raise on failure.
        """
        try:
            stripe.PaymentIntent.cancel(intent_id)
            logger.info(f"Cancelled PaymentIntent {intent_id}")
            return {'success': True}
        except Exception as e:
            logger.warning(f"Could not cancel PaymentIntent {intent_id}: {e}")
            return {'success': False, 'error': str(e)}

    def verify_payment(self, intent_id):
        """Retrieve and verify PaymentIntent status.
        
        Status mapping:
          succeeded        → Card payment completed immediately.
          processing       → ACH Bank payment accepted (settles in 1-3 days).
          requires_action  → Klarna redirect / bank mandate needs confirmation
                             but the payment itself was initiated correctly.
          requires_confirmation → Bank account linked, awaiting ACH confirmation.
        
        All of the above are treated as SUCCESS from our perspective — the
        invoice is marked paid and the resident sees a success message.
        Only truly failed/canceled statuses are returned as errors.
        """
        try:
            intent = stripe.PaymentIntent.retrieve(intent_id)
            
            # Statuses that mean the payment is on track (completed or will complete)
            SUCCESS_STATUSES = {'succeeded', 'processing', 'requires_action', 'requires_confirmation'}
            
            if intent.status in SUCCESS_STATUSES:
                # Only run the transfer/split logic when the charge actually landed
                if intent.status == 'succeeded':
                    self.process_successful_payment(intent_id, intent_data=intent)
                else:
                    # For async methods (ACH, Klarna) mark the payment record as
                    # completed so the invoice shows as paid immediately.
                    # Stripe will send a webhook when the charge settles.
                    from payments.models import Payment
                    try:
                        payment = Payment.objects.get(gateway_payment_id=intent_id)
                    except Payment.DoesNotExist:
                        # Try metadata lookup
                        meta_payment_id = intent.metadata.get('payment_id') if intent.metadata else None
                        if meta_payment_id:
                            try:
                                payment = Payment.objects.get(id=meta_payment_id)
                            except Payment.DoesNotExist:
                                payment = None
                        else:
                            payment = None
                    
                    if payment and payment.status not in ('completed', 'processing'):
                        payment.status = 'processing'
                        payment.completed_at = None
                        payment.gateway_payment_id = intent_id
                        payment.save()
                        if payment.invoice and payment.invoice.status not in ('paid', 'processing'):
                            payment.invoice.status = 'processing'
                            payment.invoice.paid_at = None
                            payment.invoice.save()

                return {
                    'success': True,
                    'payment_id': intent.id,
                    'status': intent.status,
                    'amount': intent.amount / 100,
                    'method': intent.payment_method_types[0] if intent.payment_method_types else 'card'
                }
            else:
                return {
                    'success': False,
                    'status': intent.status,
                    'error': f'Payment not completed (status: {intent.status})'
                }
        except Exception as e:
            logger.error(f"Failed to verify Stripe payment: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def create_refund(self, intent_id, amount=None):
        """Create a refund for a PaymentIntent"""
        try:
            params = {'payment_intent': intent_id}
            if amount:
                params['amount'] = int(Decimal(str(amount)) * 100)
            
            if self.gateway.stripe_connected_account_id:
                params['reverse_transfer'] = True
                params['refund_application_fee'] = True
                
            refund = stripe.Refund.create(**params)
            
            return {
                'success': True,
                'refund_id': refund.id,
                'status': refund.status,
                'amount': refund.amount / 100
            }
        except Exception as e:
            logger.error(f"Failed to create Stripe refund: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
            
    def process_successful_payment(self, intent_id, intent_data=None):
        """
        Process the transfer and split logic when a payment succeeds.
        Idempotent: Checks if the transfer has already occurred for this payment.
        """
        from payments.models import Payment, PaymentGateway
        
        try:
            payment = Payment.objects.get(gateway_payment_id=intent_id)
        except Payment.DoesNotExist:
            # Fallback: check metadata from intent if intent_data is provided
            if intent_data and hasattr(intent_data, 'get'):
                payment_id = intent_data.get('metadata', {}).get('payment_id')
                if payment_id:
                    try:
                        payment = Payment.objects.get(id=payment_id)
                    except Payment.DoesNotExist:
                        logger.error(f"process_successful_payment: Payment not found for intent_id {intent_id} and payment_id {payment_id}")
                        return {'success': False, 'error': 'Payment not found'}
                else:
                    return {'success': False, 'error': 'Payment not found'}
            else:
                return {'success': False, 'error': 'Payment not found'}
                
        # Idempotency Check: if split_master_amount is in metadata, it's already processed
        if payment.metadata and payment.metadata.get('split_master_amount') is not None:
            return {'success': True, 'message': 'Transfer already processed'}
            
        if not intent_data:
            intent_data = stripe.PaymentIntent.retrieve(intent_id)

        # Extract platform_fee from intent metadata
        platform_fee = Decimal('0.00')
        if hasattr(intent_data, 'metadata') and 'platform_fee' in intent_data.metadata:
            platform_fee = Decimal(str(intent_data.metadata['platform_fee'])) / Decimal('100.00')
        elif isinstance(intent_data, dict) and 'metadata' in intent_data and 'platform_fee' in intent_data['metadata']:
            platform_fee = Decimal(str(intent_data['metadata']['platform_fee'])) / Decimal('100.00')

        # Add administrative fee to invoice line items if the resident paid it
        if payment.invoice and platform_fee > 0:
            invoice = payment.invoice
            has_fee = False
            line_items = invoice.line_items or []
            for item in line_items:
                if str(item.get('type', '')).lower() == 'platform_fee' or 'administrative fee' in str(item.get('description', '')).lower() or 'administrative fee' in str(item.get('name', '')).lower():
                    has_fee = True
                    break
            
            if not has_fee:
                # Need to grab fee_label if possible, else generic
                fee_label = intent_data.metadata.get('fee_label', 'Administrative Fee') if hasattr(intent_data, 'metadata') else 'Administrative Fee'
                line_items.append({
                    'type': 'platform_fee',
                    'name': 'Administrative Fee',
                    'description': fee_label,
                    'quantity': 1,
                    'unit_price': float(platform_fee),
                    'amount': float(platform_fee)
                })
                invoice.line_items = line_items
                invoice.save()

        if payment.status != 'completed':
            payment.status = 'completed'
            payment.completed_at = timezone.now()
            payment.gateway_payment_id = intent_id
            payment.gateway_response = intent_data
            payment.save()
            
        if payment.invoice:
            invoice = payment.invoice
            if invoice.status != 'paid':
                invoice.status = 'paid'
                invoice.paid_at = timezone.now()
                invoice.save()
                
            try:
                transfer_group = intent_data.get('transfer_group') if isinstance(intent_data, dict) else getattr(intent_data, 'transfer_group', None)
                if transfer_group:
                    tenant_gw = PaymentGateway.objects.filter(gateway_type='stripe', is_active=True).first()
                    master_admin_acct = tenant_gw.stripe_connected_account_id if tenant_gw else None
                    
                    if master_admin_acct:
                        # Platform fee is already extracted above
                        
                        # Capture payment method from intent
                        payment_method_type = 'card'
                        if hasattr(intent_data, 'payment_method_types') and intent_data.payment_method_types:
                            payment_method_type = intent_data.payment_method_types[0]
                        elif isinstance(intent_data, dict) and 'payment_method_types' in intent_data and intent_data['payment_method_types']:
                            payment_method_type = intent_data['payment_method_types'][0]
                            
                        if hasattr(intent_data, 'payment_method_details') and getattr(intent_data, 'payment_method_details'):
                            pm_details = getattr(intent_data, 'payment_method_details')
                            if hasattr(pm_details, 'type'):
                                payment_method_type = pm_details.type
                        elif isinstance(intent_data, dict) and 'payment_method_details' in intent_data and intent_data['payment_method_details']:
                            payment_method_type = intent_data['payment_method_details'].get('type', payment_method_type)
                            
                        # The total charge is what the user paid, but the invoice.total_amount is what the HOA gets.
                        # Wait, what if it's an old invoice where platform_fee is in the line items?
                        legacy_platform_fee = Decimal('0.00')
                        if invoice.line_items:
                            for item in invoice.line_items:
                                desc_lower = str(item.get('description', item.get('name', ''))).lower()
                                type_lower = str(item.get('type', '')).lower()
                                if type_lower == 'platform_fee' or 'association charge' in desc_lower or 'platform' in desc_lower:
                                    qty = Decimal(str(item.get('quantity', 1)))
                                    unit_price = Decimal(str(item.get('unit_price', item.get('rate', 0))))
                                    item_amt = Decimal(str(item.get('amount', item.get('total', float(qty) * float(unit_price)))))
                                    legacy_platform_fee += item_amt
                                    
                        if legacy_platform_fee > 0:
                            if platform_fee == 0:
                                platform_fee = legacy_platform_fee
                            net_for_hoa = Decimal(str(invoice.total_amount)) - legacy_platform_fee
                        else:
                            # New flow without fee line item: invoice.total_amount is the net for HOA
                            net_for_hoa = Decimal(str(invoice.total_amount))
                        
                        if net_for_hoa > 0:
                            # 2-Way Split (HOA connected account receives net_for_hoa)
                            transfer_params = {
                                'amount': int(net_for_hoa * 100),
                                'currency': intent_data.currency if hasattr(intent_data, 'currency') else intent_data.get('currency', 'usd'),
                                'destination': master_admin_acct,
                                'transfer_group': transfer_group,
                                'metadata': {'invoice_id': str(invoice.id), 'type': 'hoa_payout'}
                            }
                            
                            # Use source_transaction to avoid insufficient balance errors in test mode
                            # by linking the transfer to the original charge.
                            latest_charge = intent_data.latest_charge if hasattr(intent_data, 'latest_charge') else intent_data.get('latest_charge')
                            if not latest_charge and (hasattr(intent_data, 'charges') or intent_data.get('charges')):
                                charges = getattr(intent_data, 'charges', intent_data.get('charges', {}))
                                charges_data = getattr(charges, 'data', charges.get('data', [])) if charges else []
                                if charges_data:
                                    latest_charge = getattr(charges_data[0], 'id', charges_data[0].get('id')) if isinstance(charges_data[0], dict) or hasattr(charges_data[0], 'id') else charges_data[0]
                                    
                            if latest_charge:
                                transfer_params['source_transaction'] = latest_charge
                                
                            stripe.Transfer.create(**transfer_params)
                                
                            # Fetch Stripe Processing Fee
                            stripe_fee = Decimal('0.00')
                            try:
                                if latest_charge:
                                    chg_obj = stripe.Charge.retrieve(latest_charge, expand=['balance_transaction'])
                                    if chg_obj.balance_transaction and getattr(chg_obj.balance_transaction, 'fee', None) is not None:
                                        stripe_fee = Decimal(str(chg_obj.balance_transaction.fee)) / Decimal('100.00')
                            except Exception as fee_err:
                                logger.error(f"Error fetching Stripe fee: {fee_err}")
                                
                            # Fallback calculation if Stripe doesn't return fee immediately (common for ACH test mode)
                            if stripe_fee == Decimal('0.00'):
                                try:
                                    # Base amount from the actual Stripe charge intent
                                    charge_amount = Decimal(str(intent_data.amount)) / Decimal('100.00')
                                    if payment_method_type == 'us_bank_account':
                                        calc_fee = (charge_amount * Decimal('0.008')).quantize(Decimal('0.01'))
                                        stripe_fee = Decimal('5.00') if calc_fee > Decimal('5.00') else calc_fee
                                    elif payment_method_type == 'klarna':
                                        stripe_fee = (charge_amount * Decimal('0.0599') + Decimal('0.30')).quantize(Decimal('0.01'))
                                    else: # card
                                        stripe_fee = (charge_amount * Decimal('0.029') + Decimal('0.30')).quantize(Decimal('0.01'))
                                except Exception as fallback_err:
                                    logger.error(f"Error calculating fallback Stripe fee: {fallback_err}")

                            payment.platform_fee = platform_fee
                            payment.net_amount = net_for_hoa
                            payment.payment_method = f"stripe_{payment_method_type}"
                            md = payment.metadata or {}
                            md['split_owner_amount'] = "0.00"
                            md['split_hoa_amount'] = str(net_for_hoa)
                            md['split_platform_fee'] = str(platform_fee)
                            md['stripe_fee'] = str(stripe_fee)
                            md['super_admin_profit'] = str(platform_fee - stripe_fee)
                            md['final_payment_method'] = payment_method_type
                            payment.metadata = md
                            payment.save(update_fields=['platform_fee', 'net_amount', 'metadata', 'payment_method'])
                            return {'success': True, 'message': 'Transfer successful'}
                        
            except Exception as e:
                import traceback
                logger.error(f"Error processing 3-way split transfers: {e}\n{traceback.format_exc()}")
                return {'success': False, 'error': str(e)}
                
        return {'success': True, 'message': 'No transfer needed'}
    
    def create_setup_intent(self, user, metadata=None):
        """
        Create a Stripe SetupIntent to securely collect and save a 
        customer's payment method without an immediate charge.
        """
        try:
            # 1. Ensure customer exists
            cust_res = self.create_or_get_customer(user)
            if not cust_res['success']:
                return cust_res
                
            customer_id = cust_res['customer_id']
            
            # 2. Setup params
            params = {
                'customer': customer_id,
                'metadata': metadata or {},
                'payment_method_types': ['card'],
            }
            
            connected_acct_id = self.gateway.stripe_connected_account_id
            # Only use on_behalf_of when the connected account has charges_enabled=True.
            # If onboarding is incomplete, Stripe rejects with "card_payments restricted".
            # Fall back to platform account flow so residents can still save cards.
            if connected_acct_id and getattr(self.gateway, 'charges_enabled', False):
                params['on_behalf_of'] = connected_acct_id
                from django.db import connection
                params['metadata']['tenant_schema'] = getattr(connection, 'schema_name', 'public')
                params['metadata']['connected_acct'] = connected_acct_id
            
            # 3. Create SetupIntent
            intent = stripe.SetupIntent.create(**params)
            
            pub_key = self.platform_pub_key if connected_acct_id else self.gateway.public_key
            
            return {
                'success': True,
                'intent_id': intent.id,
                'client_secret': intent.client_secret,
                'customer_id': customer_id,
                'publishable_key': pub_key,
            }
        except Exception as e:
            logger.error(f"Failed to create Stripe SetupIntent: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def create_or_get_customer(self, user):
        """Create or retrieve a Stripe customer on the platform account"""
        try:
            # Check if customer exists by email
            customers = stripe.Customer.list(email=user.email, limit=1).data
            if customers:
                return {
                    'success': True,
                    'customer_id': customers[0].id,
                    'is_new': False
                }
            
            # Create new customer
            customer = stripe.Customer.create(
                name=user.get_full_name(),
                email=user.email,
                phone=getattr(user, 'phone', ''),
                metadata={
                    'user_id': str(user.id)
                }
            )
            return {
                'success': True,
                'customer_id': customer.id,
                'is_new': True
            }
        except Exception as e:
            logger.error(f"Failed to create/get Stripe customer: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
