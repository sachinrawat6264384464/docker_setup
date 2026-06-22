import stripe
import logging
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.shortcuts import redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework import status

from django_tenants.utils import schema_context
from tenants.models import Client
from payments.models import PaymentGateway, WebhookEventLog, OwnerPaymentProfile

logger = logging.getLogger(__name__)

def _get_stripe_api_key():
    key = getattr(settings, 'STRIPE_PLATFORM_SECRET_KEY', None) or getattr(settings, 'STRIPE_SECRET_KEY', None)
    if not key:
        with schema_context('public'):
            gw = PaymentGateway.objects.filter(gateway_type='stripe').first()
            if gw and gw.secret_key:
                key = gw.secret_key
    return key

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_connected_account(request):
    """
    Creates a Stripe Express Connected Account for the Master Admin's organization.
    Saves the Connected Account ID to the tenant's PaymentGateway record.
    """
    if request.user.role not in ('master_admin', 'masteradmin'):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    schema_name = getattr(request.user, 'tenant_id', None)
    if not schema_name or schema_name == 'public':
        return Response({'error': 'Invalid tenant context'}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        with schema_context('public'):
            client = Client.objects.get(schema_name=schema_name)
    except Client.DoesNotExist:
        return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)
        
    # Switch schema to read/write PaymentGateway
    with schema_context(schema_name):
        gateway, _ = PaymentGateway.objects.get_or_create(gateway_type='stripe')
        
        # Duplicate account check
        if gateway.stripe_connected_account_id:
            return JsonResponse({'error': 'Account already exists'}, status=400)
            
    # Extract user for email
    user = request.user

    # Base Stripe Account payload (simplified for Reverse Sync)
    stripe_payload = {
        'type': 'express',
        'country': 'US',
        'capabilities': {
            'card_payments': {'requested': True},
            'transfers':     {'requested': True},
            'us_bank_account_ach_payments': {'requested': True},
        },
        'metadata': {
            'org_id': str(client.id),
            'tenant_schema': schema_name,
        }
    }

    # Call Stripe API
    try:
        stripe.api_key = _get_stripe_api_key()
        account = stripe.Account.create(**stripe_payload)

        
        with schema_context(schema_name):
            gw = PaymentGateway.objects.get(gateway_type='stripe')
            gw.stripe_connected_account_id = account.id
            gw.payment_status = 'PENDING'
            gw.onboarding_started = True
            gw.save()
            
        logger.info(f"Created Express Connected Account {account.id} for schema {schema_name}")
        return Response({
            'account_id': account.id,
            'status': 'PENDING'
        })
    except Exception as e:
        logger.error(f"Stripe Connect account creation failed: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_onboarding_link(request):
    """
    Generates a fresh Stripe Express onboarding link for the organization.
    """
    if request.user.role not in ('master_admin', 'masteradmin'):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    schema_name = getattr(request.user, 'tenant_id', None)
    if not schema_name or schema_name == 'public':
        return Response({'error': 'Invalid tenant context'}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        with schema_context('public'):
            client = Client.objects.get(schema_name=schema_name)
    except Client.DoesNotExist:
        return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)
        
    with schema_context(schema_name):
        gateway = PaymentGateway.objects.filter(gateway_type='stripe').first()
        if not gateway or not gateway.stripe_connected_account_id:
            return Response({'error': 'Stripe Connect account not created yet'}, status=status.HTTP_400_BAD_REQUEST)
            
        acct_id = gateway.stripe_connected_account_id
        
    try:
        stripe.api_key = _get_stripe_api_key()
        
        origin = request.headers.get('Origin')
        if origin:
            base_url = origin
        else:
            domain_obj = client.domains.filter(is_primary=True).first() or client.domains.first()
            domain = domain_obj.domain if domain_obj else request.get_host()
            protocol = "https" if request.is_secure() or not settings.DEBUG else "http"
            base_url = f"{protocol}://{domain}"
        
        refresh_url = f"{base_url}/masteradmin/settings?tab=payments&stripe=refresh"
        return_url = f"{base_url}/masteradmin/settings?tab=payments&stripe=return"
        
        link = stripe.AccountLink.create(
            account=acct_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type='account_onboarding',
        )
        return JsonResponse({'url': link.url})
    except Exception as e:
        logger.error(f"Failed to create Stripe AccountLink: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_connect_status(request, org_id):
    """
    Fetch Connect onboarding status and details from Stripe and sync database.
    """
    if request.user.role not in ('master_admin', 'masteradmin'):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    schema_name = getattr(request.user, 'tenant_id', None)
    if not schema_name or schema_name == 'public':
        return Response({'error': 'Invalid tenant context'}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        with schema_context('public'):
            client = Client.objects.get(id=org_id, schema_name=schema_name)
    except Client.DoesNotExist:
        return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)
        
    with schema_context(schema_name):
        gateway = PaymentGateway.objects.filter(gateway_type='stripe').first()
        if not gateway or not gateway.stripe_connected_account_id:
            return JsonResponse({'connected': False})
            
        acct_id = gateway.stripe_connected_account_id
        bank_connected = gateway.bank_connected
        onboarding_completed = gateway.onboarding_completed
        bank_name = gateway.bank_name
        bank_last4 = gateway.bank_last4
        
    # Sync from Stripe
    try:
        stripe.api_key = _get_stripe_api_key()
        acct = stripe.Account.retrieve(acct_id)
        
        charges_enabled = acct.charges_enabled
        payouts_enabled = acct.payouts_enabled
        requirements_due = list(acct.requirements.currently_due) if hasattr(acct, 'requirements') and hasattr(acct.requirements, 'currently_due') else []
        disabled_reason = acct.requirements.disabled_reason if hasattr(acct, 'requirements') and hasattr(acct.requirements, 'disabled_reason') else None
        
        with schema_context(schema_name):
            gw = PaymentGateway.objects.get(gateway_type='stripe')
            gw.charges_enabled = charges_enabled
            gw.payouts_enabled = payouts_enabled
            
            details_submitted = getattr(acct, 'details_submitted', False)
            if details_submitted:
                gw.onboarding_completed = True
                onboarding_completed = True
                
            external_accounts = getattr(acct, 'external_accounts', None)
            if external_accounts and hasattr(external_accounts, 'data') and len(external_accounts.data) > 0:
                bank_connected = True
                primary_bank = external_accounts.data[0]
                bank_name = getattr(primary_bank, 'bank_name', None)
                bank_last4 = getattr(primary_bank, 'last4', None)
                gw.bank_connected = True
                gw.bank_name = bank_name
                gw.bank_last4 = bank_last4
                
            business_profile = getattr(acct, 'business_profile', None)
            if business_profile:
                if getattr(business_profile, 'name', None):
                    gw.business_name = business_profile.name
                if getattr(business_profile, 'support_email', None):
                    gw.support_email = business_profile.support_email
                if getattr(business_profile, 'support_phone', None):
                    gw.business_phone = business_profile.support_phone
                if getattr(business_profile, 'url', None):
                    gw.business_url = business_profile.url
                
            if charges_enabled:
                gw.payment_status = 'ACTIVE'
                gw.stripe_verification_status = 'verified'
            else:
                gw.payment_status = 'PENDING'
                gw.stripe_verification_status = 'pending'
            gw.save()
            business_name = gw.business_name
            stripe_verification_status = gw.stripe_verification_status
            payment_status = gw.payment_status
            
        return JsonResponse({
            'connected': True,
            'stripe_connected_account_id': acct_id,
            'bank_connected': bank_connected,
            'onboarding_completed': onboarding_completed,
            'charges_enabled': charges_enabled,
            'payouts_enabled': payouts_enabled,
            'requirements_due': requirements_due,
            'disabled_reason': disabled_reason,
            'bank_name': bank_name,
            'bank_last4': bank_last4,
            'business_name': business_name,
            'stripe_verification_status': stripe_verification_status,
            'payment_status': payment_status,
        })
            
    except Exception as e:
        logger.warning(f"Failed to sync Stripe Connect status for account {acct_id}: {str(e)}")
        # Fallback if Stripe API fails
        return JsonResponse({
            'connected': True,
            'stripe_connected_account_id': acct_id,
            'bank_connected': bank_connected,
            'onboarding_completed': onboarding_completed,
            'charges_enabled': getattr(gateway, 'charges_enabled', False),
            'payouts_enabled': getattr(gateway, 'payouts_enabled', False),
            'requirements_due': [],
            'disabled_reason': None,
            'bank_name': bank_name,
            'bank_last4': bank_last4,
            'business_name': getattr(gateway, 'business_name', None),
            'stripe_verification_status': getattr(gateway, 'stripe_verification_status', None),
            'payment_status': getattr(gateway, 'payment_status', None),
        })


# onboarding_return and onboarding_reauth removed as they are no longer used

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def owner_create_connected_account(request):
    """
    Creates a Stripe Express Connected Account for the Owner.
    Saves the Connected Account ID to the OwnerPaymentProfile record.
    """
    if request.user.role not in ('owner',):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    schema_name = getattr(request.user, 'tenant_id', None)
    if not schema_name or schema_name == 'public':
        return Response({'error': 'Invalid tenant context'}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        with schema_context('public'):
            client = Client.objects.get(schema_name=schema_name)
    except Client.DoesNotExist:
        return Response({'error': 'Organization not found'}, status=status.HTTP_404_NOT_FOUND)
        
    # Switch schema to read/write OwnerPaymentProfile
    with schema_context(schema_name):
        profile, _ = OwnerPaymentProfile.objects.get_or_create(owner=request.user)
        
        if profile.stripe_connected_account_id:
            return JsonResponse({'error': 'Account already exists'}, status=400)
            
    # Base Stripe Account payload
    stripe_payload = {
        'type': 'express',
        'country': 'US',
        'capabilities': {
            'card_payments': {'requested': True},
            'transfers':     {'requested': True},
            'us_bank_account_ach_payments': {'requested': True},
        },
        'metadata': {
            'org_id': str(client.id),
            'tenant_schema': schema_name,
            'owner_id': str(request.user.id)
        }
    }

    try:
        stripe.api_key = _get_stripe_api_key()
        account = stripe.Account.create(**stripe_payload)
        
        with schema_context(schema_name):
            profile = OwnerPaymentProfile.objects.get(owner=request.user)
            profile.stripe_connected_account_id = account.id
            profile.payment_status = 'PENDING'
            profile.save()
            
        logger.info(f"Created Owner Express Connected Account {account.id} for owner {request.user.id}")
        return Response({
            'account_id': account.id,
            'status': 'PENDING'
        })
    except Exception as e:
        logger.error(f"Owner Stripe Connect account creation failed: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def owner_get_onboarding_link(request):
    """Generates onboarding link for owner"""
    if request.user.role not in ('owner',):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    schema_name = getattr(request.user, 'tenant_id', None)
    if not schema_name or schema_name == 'public':
        return Response({'error': 'Invalid tenant context'}, status=status.HTTP_400_BAD_REQUEST)
        
    with schema_context(schema_name):
        profile = OwnerPaymentProfile.objects.filter(owner=request.user).first()
        if not profile or not profile.stripe_connected_account_id:
            return Response({'error': 'Stripe Connect account not created yet'}, status=status.HTTP_400_BAD_REQUEST)
        acct_id = profile.stripe_connected_account_id
        
    try:
        stripe.api_key = _get_stripe_api_key()
        
        origin = request.headers.get('Origin')
        if origin:
            base_url = origin
        else:
            protocol = "https" if request.is_secure() or not settings.DEBUG else "http"
            base_url = f"{protocol}://{request.get_host()}"
        
        # Route to backend endpoints which will redirect
        refresh_url = f"{base_url}/api/v1/tenants/connect/owner/refresh/"
        return_url = f"{base_url}/api/v1/tenants/connect/owner/return/"
        
        link = stripe.AccountLink.create(
            account=acct_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type='account_onboarding',
        )
        return JsonResponse({'url': link.url})
    except Exception as e:
        logger.error(f"Failed to create Owner Stripe AccountLink: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_get_connect_status(request):
    if request.user.role not in ('owner',):
        return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
        
    schema_name = getattr(request.user, 'tenant_id', None)
    with schema_context(schema_name):
        profile = OwnerPaymentProfile.objects.filter(owner=request.user).first()
        if not profile or not profile.stripe_connected_account_id:
            return JsonResponse({'connected': False})
            
        acct_id = profile.stripe_connected_account_id
        bank_connected = profile.bank_connected
        bank_name = profile.bank_name
        bank_last4 = profile.bank_last4
        
    try:
        stripe.api_key = _get_stripe_api_key()
        acct = stripe.Account.retrieve(acct_id)
        
        charges_enabled = acct.charges_enabled
        payouts_enabled = acct.payouts_enabled
        requirements_due = list(acct.requirements.currently_due) if hasattr(acct, 'requirements') and hasattr(acct.requirements, 'currently_due') else []
        disabled_reason = acct.requirements.disabled_reason if hasattr(acct, 'requirements') and hasattr(acct.requirements, 'disabled_reason') else None
        
        with schema_context(schema_name):
            profile = OwnerPaymentProfile.objects.get(owner=request.user)
            profile.charges_enabled = charges_enabled
            profile.payouts_enabled = payouts_enabled
            
            external_accounts = getattr(acct, 'external_accounts', None)
            if external_accounts and hasattr(external_accounts, 'data') and len(external_accounts.data) > 0:
                bank_connected = True
                primary_bank = external_accounts.data[0]
                bank_name = getattr(primary_bank, 'bank_name', None)
                bank_last4 = getattr(primary_bank, 'last4', None)
                profile.bank_connected = True
                profile.bank_name = bank_name
                profile.bank_last4 = bank_last4
                
            if charges_enabled:
                profile.payment_status = 'ACTIVE'
            else:
                profile.payment_status = 'PENDING'
            profile.save()
            payment_status = profile.payment_status
            
        return JsonResponse({
            'connected': True,
            'stripe_connected_account_id': acct_id,
            'bank_connected': bank_connected,
            'charges_enabled': charges_enabled,
            'payouts_enabled': payouts_enabled,
            'requirements_due': requirements_due,
            'disabled_reason': disabled_reason,
            'bank_name': bank_name,
            'bank_last4': bank_last4,
            'payment_status': payment_status,
        })
            
    except Exception as e:
        logger.warning(f"Failed to sync Owner Stripe Connect status for account {acct_id}: {str(e)}")
        return JsonResponse({
            'connected': True,
            'stripe_connected_account_id': acct_id,
            'bank_connected': bank_connected,
            'charges_enabled': getattr(profile, 'charges_enabled', False),
            'payouts_enabled': getattr(profile, 'payouts_enabled', False),
            'requirements_due': [],
            'disabled_reason': None,
            'bank_name': bank_name,
            'bank_last4': bank_last4,
            'payment_status': getattr(profile, 'payment_status', None),
        })

@api_view(['GET'])
@permission_classes([AllowAny])
def owner_stripe_return(request):
    """Callback when owner completes Stripe onboarding"""
    # Simply redirect to frontend owner dashboard with stripe query param
    # Origin headers are usually not present on GET redirects, so we infer from host
    protocol = "https" if request.is_secure() or not settings.DEBUG else "http"
    base_url = f"{protocol}://{request.get_host()}"
    return redirect(f"{base_url}/owner/payments?stripe=return")

@api_view(['GET'])
@permission_classes([AllowAny])
def owner_stripe_refresh(request):
    """Callback when owner onboarding session expires/refreshes"""
    protocol = "https" if request.is_secure() or not settings.DEBUG else "http"
    base_url = f"{protocol}://{request.get_host()}"
    return redirect(f"{base_url}/owner/payments?stripe=refresh")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_get_stripe_profile(request):
    """
    Returns the synchronized read-only Stripe profile data for the Owner's connected account.
    """
    if request.user.role not in ('owner',):
        return JsonResponse({'error': 'Forbidden'}, status=403)
        
    schema_name = getattr(request.user, 'tenant_id', None)
    if not schema_name or schema_name == 'public':
        return Response({'error': 'Invalid tenant context'}, status=status.HTTP_400_BAD_REQUEST)
        
    with schema_context(schema_name):
        profile = OwnerPaymentProfile.objects.filter(owner=request.user).first()
        if not profile or not profile.stripe_connected_account_id:
            return JsonResponse({'error': 'Not connected to Stripe'}, status=404)
            
        try:
            stripe.api_key = _get_stripe_api_key()
            acct = stripe.Account.retrieve(profile.stripe_connected_account_id)
            
            company = getattr(acct, 'company', None) or getattr(acct, 'individual', None)
            company_address = getattr(company, 'address', None) if company else None
            
            persons = stripe.Account.list_persons(profile.stripe_connected_account_id)
            rep = persons.data[0] if persons and hasattr(persons, 'data') and len(persons.data) > 0 else None
            
            settings_obj = getattr(acct, 'settings', None)
            payments_settings = getattr(settings_obj, 'payments', None) if settings_obj else None
            statement_descriptor = getattr(payments_settings, 'statement_descriptor', None) if payments_settings else None
            
            data = {
                'business_name': getattr(acct.business_profile, 'name', None),
                'support_email': getattr(acct.business_profile, 'support_email', None),
                'business_phone': getattr(acct.business_profile, 'support_phone', None),
                'business_url': getattr(acct.business_profile, 'url', None),
                
                'business_type': getattr(acct, 'business_type', None),
                'business_structure': getattr(company, 'structure', None) if company else None,
                'mcc': getattr(acct.business_profile, 'mcc', None) if getattr(acct, 'business_profile', None) else None,
                
                'address_line1': getattr(company_address, 'line1', None) if company_address else None,
                'address_city': getattr(company_address, 'city', None) if company_address else None,
                'address_state': getattr(company_address, 'state', None) if company_address else None,
                'address_postal_code': getattr(company_address, 'postal_code', None) if company_address else None,
                'address_country': getattr(company_address, 'country', None) if company_address else None,
                'tax_id_provided': getattr(company, 'tax_id_provided', False) if company and hasattr(company, 'tax_id_provided') else getattr(acct, 'details_submitted', False),
                
                'rep_name': f"{getattr(rep, 'first_name', '')} {getattr(rep, 'last_name', '')}".strip() if rep else None,
                'rep_email': getattr(rep, 'email', None) if rep else None,
                'rep_phone': getattr(rep, 'phone', None) if rep and getattr(rep, 'phone', None) else ('Hidden for Security' if getattr(acct, 'details_submitted', False) else None),
                'rep_dob': f"{getattr(rep.dob, 'year', '')}-{getattr(rep.dob, 'month', '')}-{getattr(rep.dob, 'day', '')}" if rep and getattr(rep, 'dob', None) else ('Hidden for Security' if getattr(acct, 'details_submitted', False) else None),
                
                'rep_address_line1': getattr(rep.address, 'line1', None) if rep and getattr(rep, 'address', None) else None,
                'rep_address_city': getattr(rep.address, 'city', None) if rep and getattr(rep, 'address', None) else None,
                'rep_address_state': getattr(rep.address, 'state', None) if rep and getattr(rep, 'address', None) else None,
                'rep_address_postal_code': getattr(rep.address, 'postal_code', None) if rep and getattr(rep, 'address', None) else None,
                'rep_address_country': getattr(rep.address, 'country', None) if rep and getattr(rep, 'address', None) else None,
                
                'rep_id_provided': getattr(rep, 'id_number_provided', False) if rep and hasattr(rep, 'id_number_provided') else getattr(acct, 'details_submitted', False),
                'rep_ssn_provided': getattr(rep, 'ssn_last_4_provided', False) if rep and hasattr(rep, 'ssn_last_4_provided') else getattr(acct, 'details_submitted', False),
                
                'statement_descriptor': statement_descriptor,
                
                'stripe_verification_status': 'verified' if acct.charges_enabled else 'pending',
                'payment_status': 'ACTIVE' if acct.charges_enabled else 'PENDING',
            }
            return JsonResponse(data)
        except Exception as e:
            return JsonResponse({
                'stripe_verification_status': 'pending',
                'payment_status': 'PENDING',
                'error': str(e)
            })

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny] if hasattr(permissions, 'AllowAny') else [])
def stripe_connect_webhook(request):
    """
    Handles Stripe Connect webhooks (account.updated, account.application.deauthorized, payout.failed)
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    webhook_secret = settings.STRIPE_CONNECT_WEBHOOK_SECRET
    if not webhook_secret:
        logger.error("STRIPE_CONNECT_WEBHOOK_SECRET is not configured.")
        return HttpResponse("Webhook secret missing", status=500)
        
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        return HttpResponse("Invalid payload", status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse("Invalid signature", status=400)
        
    # Idempotency check
    with schema_context('public'):
        if WebhookEventLog.objects.filter(stripe_event_id=event['id']).exists():
            return HttpResponse("Already processed", status=200)
            
        WebhookEventLog.objects.create(
            stripe_event_id=event['id'],
            event_type=event['type'],
            payload=event
        )
        
    event_type = event['type']
    data = event['data']['object']
    
    if event_type == 'account.updated':
        _handle_account_updated(data)
    elif event_type == 'account.application.deauthorized':
        _handle_account_deauthorized(data)
    elif event_type == 'payout.failed':
        _handle_payout_failed(data)
    elif event_type == 'account.external_account.created':
        _handle_external_account_created(data)
    elif event_type == 'account.external_account.deleted':
        _handle_external_account_deleted(data)
    elif event_type == 'financial_connections.account.created':
        _handle_financial_connections_account_created(data)
        
    return HttpResponse("OK", status=200)


def _handle_account_updated(account_data):
    try:
        acct_id = account_data['id']
        charges_enabled = account_data.get('charges_enabled', False)
        payouts_enabled = account_data.get('payouts_enabled', False)
        requirements = account_data.get('requirements', {})
        requirements_due = requirements.get('currently_due', [])
        disabled_reason = requirements.get('disabled_reason')
        
        tenant_schema = account_data.get('metadata', {}).get('tenant_schema')
        
        if not tenant_schema:
            with schema_context('public'):
                clients = Client.objects.exclude(schema_name='public')
                for c in clients:
                    with schema_context(c.schema_name):
                        if PaymentGateway.objects.filter(stripe_connected_account_id=acct_id).exists():
                            tenant_schema = c.schema_name
                            break
                            
        if not tenant_schema:
            logger.warning(f"account.updated received for unknown connected account: {acct_id}")
            return
            
        with schema_context(tenant_schema):
            try:
                gateway = PaymentGateway.objects.get(stripe_connected_account_id=acct_id)
                gateway.charges_enabled = charges_enabled
                gateway.payouts_enabled = payouts_enabled
                
                is_completed = charges_enabled and payouts_enabled and len(requirements_due) == 0
                gateway.onboarding_completed = is_completed
                
                if charges_enabled:
                    gateway.payment_status = 'ACTIVE'
                else:
                    gateway.payment_status = 'PENDING'
                    
                if is_completed and not gateway.onboarding_completed_at:
                    gateway.onboarding_completed_at = timezone.now()

                # Reverse Sync Stripe Data
                business_profile = account_data.get('business_profile', {})
                business_name = business_profile.get('name')
                support_email = business_profile.get('support_email')
                business_phone = business_profile.get('support_phone')
                business_url = business_profile.get('url')
                
                if business_name: gateway.business_name = business_name
                if support_email: gateway.support_email = support_email
                if business_phone: gateway.business_phone = business_phone
                if business_url: gateway.business_url = business_url
                if disabled_reason:
                    gateway.stripe_verification_status = disabled_reason
                elif is_completed:
                    gateway.stripe_verification_status = 'verified'
                    gateway.onboarding_completed = True
                    
                gateway.save()
                
                # Update Client
                try:
                    client = Client.objects.get(schema_name=tenant_schema)
                    if business_name and not client.name:
                        client.name = business_name
                    if business_phone and not client.contact_phone:
                        client.contact_phone = business_phone
                    if support_email and not client.contact_email:
                        client.contact_email = support_email
                        
                    # Try to extract address
                    company = account_data.get('company', {})
                    individual = account_data.get('individual', {})
                    address = company.get('address') or individual.get('address') or {}
                    
                    if address.get('line1') and not client.address: client.address = address.get('line1')
                    if address.get('city') and not client.city: client.city = address.get('city')
                    if address.get('state') and not client.state: client.state = address.get('state')
                    if address.get('postal_code') and not client.pincode: client.pincode = address.get('postal_code')
                    if address.get('country') and not client.country: client.country = address.get('country')
                    
                    client.save()
                except Client.DoesNotExist:
                    pass
                
                # Update UserProfile
                try:
                    from accounts.models import User
                    master_admin = User.objects.filter(role__in=['master_admin', 'masteradmin']).first()
                    if master_admin and hasattr(master_admin, 'profile'):
                        profile = master_admin.profile
                        addr = individual.get('address') or {}
                        if addr.get('line1') and not profile.address_line_1: profile.address_line_1 = addr.get('line1')
                        if addr.get('city') and not profile.city: profile.city = addr.get('city')
                        if addr.get('state') and not profile.state: profile.state = addr.get('state')
                        if addr.get('postal_code') and not profile.postal_code: profile.postal_code = addr.get('postal_code')
                        if addr.get('country') and not profile.country: profile.country = addr.get('country')
                        profile.save()
                except Exception as ex:
                    logger.error(f"Failed to update UserProfile from webhook: {ex}")

                logger.info(f"Updated connection status for account {acct_id}: charges={charges_enabled}, completed={is_completed}")
            except PaymentGateway.DoesNotExist:
                logger.error(f"PaymentGateway not found in schema {tenant_schema} for account {acct_id}")
    except Exception as e:
        logger.error(f"Error processing account.updated webhook: {e}")


def _handle_account_deauthorized(account_data):
    acct_id = account_data['id']
    tenant_schema = account_data.get('metadata', {}).get('tenant_schema')
    
    if not tenant_schema:
        with schema_context('public'):
            clients = Client.objects.exclude(schema_name='public')
            for c in clients:
                with schema_context(c.schema_name):
                    if PaymentGateway.objects.filter(stripe_connected_account_id=acct_id).exists():
                        tenant_schema = c.schema_name
                        break
                        
    if not tenant_schema:
        logger.warning(f"Deauthorized unknown account: {acct_id}")
        return
        
    with schema_context(tenant_schema):
        try:
            gateway = PaymentGateway.objects.get(stripe_connected_account_id=acct_id)
            gateway.payment_status = 'DISABLED'
            gateway.charges_enabled = False
            gateway.save()
            logger.warning(f"Stripe account {acct_id} deauthorized by user.")
        except PaymentGateway.DoesNotExist:
            pass


def _handle_payout_failed(payout_data):
    acct_id = payout_data.get('destination')
    logger.error(f"Payout failed for Connected Account: {acct_id}")


def _handle_external_account_created(ext_data):
    acct_id = ext_data.get('account')
    if not acct_id: return
    
    with schema_context('public'):
        clients = Client.objects.exclude(schema_name='public')
        for c in clients:
            with schema_context(c.schema_name):
                gateway = PaymentGateway.objects.filter(stripe_connected_account_id=acct_id).first()
                if gateway:
                    gateway.bank_connected = True
                    gateway.bank_name = ext_data.get('bank_name')
                    gateway.bank_last4 = ext_data.get('last4')
                    gateway.save()
                    return


def _handle_external_account_deleted(ext_data):
    acct_id = ext_data.get('account')
    if not acct_id: return
    
    with schema_context('public'):
        clients = Client.objects.exclude(schema_name='public')
        for c in clients:
            with schema_context(c.schema_name):
                gateway = PaymentGateway.objects.filter(stripe_connected_account_id=acct_id).first()
                if gateway:
                    gateway.bank_connected = False
                    gateway.bank_name = None
                    gateway.bank_last4 = None
                    gateway.save()
                    return


def _handle_financial_connections_account_created(fc_data):
    acct_holder = fc_data.get('account_holder')
    if acct_holder and acct_holder.get('type') == 'account':
        acct_id = acct_holder.get('account')
        if not acct_id: return
        with schema_context('public'):
            clients = Client.objects.exclude(schema_name='public')
            for c in clients:
                with schema_context(c.schema_name):
                    gateway = PaymentGateway.objects.filter(stripe_connected_account_id=acct_id).first()
                    if gateway:
                        gateway.financial_connections_account_id = fc_data.get('id')
                        gateway.save()
                        return


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_stripe_profile(request):
    """
    Returns the synchronized read-only Stripe profile data from PaymentGateway.
    """
    if request.user.role not in ('master_admin', 'masteradmin', 'super_admin', 'superadmin') and not request.user.is_staff and not request.user.is_superuser:
        return JsonResponse({'error': 'Forbidden'}, status=403)
        
    schema_name = getattr(request.user, 'tenant_id', None)
    if not schema_name or schema_name == 'public':
        return Response({'error': 'Invalid tenant context'}, status=status.HTTP_400_BAD_REQUEST)
        
    with schema_context(schema_name):
        gateway = PaymentGateway.objects.filter(gateway_type='stripe').first()
        if not gateway or not gateway.stripe_connected_account_id:
            return JsonResponse({'error': 'Not connected to Stripe'}, status=404)
            
        try:
            stripe.api_key = _get_stripe_api_key()
            acct = stripe.Account.retrieve(gateway.stripe_connected_account_id)
            
            company = getattr(acct, 'company', None) or getattr(acct, 'individual', None)
            company_address = getattr(company, 'address', None) if company else None
            
            persons = stripe.Account.list_persons(gateway.stripe_connected_account_id)
            rep = persons.data[0] if persons and hasattr(persons, 'data') and len(persons.data) > 0 else None
            
            settings_obj = getattr(acct, 'settings', None)
            payments_settings = getattr(settings_obj, 'payments', None) if settings_obj else None
            statement_descriptor = getattr(payments_settings, 'statement_descriptor', None) if payments_settings else None
            
            data = {
                'business_name': getattr(acct.business_profile, 'name', gateway.business_name) if getattr(acct, 'business_profile', None) else gateway.business_name,
                'support_email': getattr(acct.business_profile, 'support_email', gateway.support_email) if getattr(acct, 'business_profile', None) else gateway.support_email,
                'business_phone': getattr(acct.business_profile, 'support_phone', gateway.business_phone) if getattr(acct, 'business_profile', None) else gateway.business_phone,
                'business_url': getattr(acct.business_profile, 'url', gateway.business_url) if getattr(acct, 'business_profile', None) else gateway.business_url,
                
                'business_type': getattr(acct, 'business_type', None),
                'business_structure': getattr(company, 'structure', None) if company else None,
                'mcc': getattr(acct.business_profile, 'mcc', None) if getattr(acct, 'business_profile', None) else None,
                
                'address_line1': getattr(company_address, 'line1', None) if company_address else None,
                'address_city': getattr(company_address, 'city', None) if company_address else None,
                'address_state': getattr(company_address, 'state', None) if company_address else None,
                'address_postal_code': getattr(company_address, 'postal_code', None) if company_address else None,
                'address_country': getattr(company_address, 'country', None) if company_address else None,
                'tax_id_provided': getattr(company, 'tax_id_provided', False) if company and hasattr(company, 'tax_id_provided') else getattr(acct, 'details_submitted', False),
                
                'rep_name': f"{getattr(rep, 'first_name', '')} {getattr(rep, 'last_name', '')}".strip() if rep else None,
                'rep_email': getattr(rep, 'email', None) if rep else None,
                'rep_phone': getattr(rep, 'phone', None) if rep and getattr(rep, 'phone', None) else ('Hidden for Security' if getattr(acct, 'details_submitted', False) else None),
                'rep_dob': f"{getattr(rep.dob, 'year', '')}-{getattr(rep.dob, 'month', '')}-{getattr(rep.dob, 'day', '')}" if rep and getattr(rep, 'dob', None) else ('Hidden for Security' if getattr(acct, 'details_submitted', False) else None),
                
                'rep_address_line1': getattr(rep.address, 'line1', None) if rep and getattr(rep, 'address', None) else None,
                'rep_address_city': getattr(rep.address, 'city', None) if rep and getattr(rep, 'address', None) else None,
                'rep_address_state': getattr(rep.address, 'state', None) if rep and getattr(rep, 'address', None) else None,
                'rep_address_postal_code': getattr(rep.address, 'postal_code', None) if rep and getattr(rep, 'address', None) else None,
                'rep_address_country': getattr(rep.address, 'country', None) if rep and getattr(rep, 'address', None) else None,
                
                'rep_id_provided': getattr(rep, 'id_number_provided', False) if rep and hasattr(rep, 'id_number_provided') else getattr(acct, 'details_submitted', False),
                'rep_ssn_provided': getattr(rep, 'ssn_last_4_provided', False) if rep and hasattr(rep, 'ssn_last_4_provided') else getattr(acct, 'details_submitted', False),
                
                'statement_descriptor': statement_descriptor,
                
                'stripe_verification_status': gateway.stripe_verification_status,
                'payment_status': gateway.payment_status,
            }
            return JsonResponse(data)
        except Exception as e:
            data = {
                'business_name': gateway.business_name,
                'business_phone': gateway.business_phone,
                'business_url': gateway.business_url,
                'support_email': gateway.support_email,
                'stripe_verification_status': gateway.stripe_verification_status,
                'payment_status': gateway.payment_status,
            }
            return JsonResponse(data)
