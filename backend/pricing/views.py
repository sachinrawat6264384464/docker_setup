import hmac
import hashlib
import logging
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status as http_status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.conf import settings
from .models import PricingPlan, Subscription, PlanService, PlanServiceMapping, AddOnRequest, TenantAddonGrant
from .serializers import (PricingPlanSerializer, SubscriptionSerializer, PlanServiceSerializer,
                          PlanServiceMappingSerializer, AddOnRequestSerializer, TenantAddonGrantSerializer)

try:
    import razorpay
    RAZORPAY_AVAILABLE = True
except ImportError:
    RAZORPAY_AVAILABLE = False


def ensure_pricing_seeded():
    """Seed default pricing data if not already present.
    
    Cache-guarded: runs the full seed logic at most once per hour.
    On subsequent calls within the cache window, returns immediately
    (zero DB queries), eliminating the 75-query overhead on every request.
    """
    from django.core.cache import cache
    CACHE_KEY = 'pricing_seeded_v2'
    if cache.get(CACHE_KEY):
        return  # Already seeded recently — skip all DB work

    # 1. Create Plans if missing
    plans_data = [
        {'name': 'Basic', 'slug': 'basic', 'monthly_price': 9.99, 'annual_price': 99.90},
        {'name': 'Premium', 'slug': 'premium', 'monthly_price': 79.99, 'annual_price': 799.90},
        {'name': 'Enterprise', 'slug': 'enterprise', 'monthly_price': 199.99, 'annual_price': 1999.90},
    ]
    plans = {}
    for p in plans_data:
        plan = PricingPlan.objects.filter(slug=p['slug']).first()
        unit_limit = 10 if p['slug'] == 'basic' else (200 if p['slug'] == 'premium' else 99999)
        manager_limit = 5 if p['slug'] == 'basic' else (15 if p['slug'] == 'premium' else 99999)
        display_order = 0 if p['slug'] == 'basic' else (1 if p['slug'] == 'premium' else 2)
        if not plan:
            plan = PricingPlan.objects.create(
                slug=p['slug'],
                name=p['name'],
                monthly_price=p['monthly_price'],
                annual_price=p['annual_price'],
                is_active=True,
                unit_limit=unit_limit,
                manager_limit=manager_limit,
                display_order=display_order
            )
        else:
            # Update values if they differ to ensure seeding changes take effect
            updated = False
            if plan.monthly_price != p['monthly_price']:
                plan.monthly_price = p['monthly_price']
                updated = True
            if plan.unit_limit != unit_limit:
                plan.unit_limit = unit_limit
                updated = True
            if updated:
                plan.save()
        plans[p['slug']] = plan

    # 2. Create Services
    services_data = [
        {'name': 'Dashboard', 'desc': 'Organization overview', 'price': 0},
        {'name': 'Communities', 'desc': 'Manage communities/projects', 'price': 0},
        {'name': 'Blocks/Sectors', 'desc': 'Manage blocks and sectors', 'price': 0},
        {'name': 'Units', 'desc': 'Manage individual units', 'price': 9.00},
        {'name': 'People Hub', 'desc': 'Resident and owner management', 'price': 0},
        {'name': 'Facility Managers', 'desc': 'Manage facility staff', 'price': 0},
        {'name': 'Documents', 'desc': 'Document storage and management', 'price': 0},
        {'name': 'Payments', 'desc': 'Fee collection and invoicing', 'price': 0},
        {'name': 'Maintenance', 'desc': 'Service requests and tracking', 'price': 0},
        {'name': 'Rental Hub', 'desc': 'Manage rentals and tenants', 'price': 7.99},
        {'name': 'Reports', 'desc': 'Advanced analytics and exports', 'price': 14.99},
        {'name': 'Amenities', 'desc': 'Clubhouse and facility booking', 'price': 7.99},
        {'name': 'Security', 'desc': 'Visitor and gate management', 'price': 12.00},
        {'name': 'Vendors', 'desc': 'Vendor and AMC management', 'price': 5.99},
        {'name': 'Message Center', 'desc': 'Broadcast messages and alerts', 'price': 4.99},

        {'name': 'Senior Hub Managers', 'desc': 'Higher-level staff management', 'price': 9.99},
        {'name': 'Support Center', 'desc': 'Priority support access', 'price': 10.00},
    ]
    services = {}
    for s in services_data:
        svc = PlanService.objects.filter(name=s['name']).first()
        if not svc:
            svc = PlanService.objects.create(
                name=s['name'],
                description=s['desc'],
                price_per_unit=s['price'],
                is_active=True
            )
        elif s['name'] == 'Units' and float(svc.price_per_unit) != float(s['price']):
            svc.price_per_unit = s['price']
            svc.save()
        services[s['name']] = svc

    # 3. Mappings
    plan_mappings = {
        'basic': {
            'included': ['Dashboard', 'Communities', 'Blocks/Sectors', 'Units', 'People Hub', 'Facility Managers', 'Documents', 'Payments', 'Maintenance'],
            'addons': ['Rental Hub', 'Reports', 'Amenities', 'Security', 'Vendors', 'Message Center', 'Senior Hub Managers', 'Support Center']
        },
        'premium': {
            'included': ['Dashboard', 'Communities', 'Blocks/Sectors', 'Units', 'People Hub', 'Facility Managers', 'Documents', 'Payments', 'Maintenance', 'Rental Hub', 'Reports'],
            'addons': ['Amenities', 'Security', 'Vendors', 'Message Center', 'Senior Hub Managers', 'Support Center']
        },
        'enterprise': {
            'included': ['Dashboard', 'Communities', 'Blocks/Sectors', 'Units', 'People Hub', 'Facility Managers', 'Documents', 'Payments', 'Maintenance', 'Rental Hub', 'Reports', 'Amenities', 'Security', 'Vendors', 'Message Center', 'Senior Hub Managers', 'Support Center'],
            'addons': []
        }
    }

    from django.db import IntegrityError

    for slug, rules in plan_mappings.items():
        plan = plans.get(slug)
        if not plan:
            continue
        for s_name in rules['included']:
            svc = services.get(s_name)
            if svc:
                try:
                    mapping, created = PlanServiceMapping.objects.get_or_create(
                        plan=plan,
                        service=svc,
                        defaults={'is_included': True}
                    )
                    if not created and not mapping.is_included:
                        mapping.is_included = True
                        mapping.save()
                except IntegrityError:
                    pass
        for s_name in rules['addons']:
            svc = services.get(s_name)
            if svc:
                try:
                    mapping, created = PlanServiceMapping.objects.get_or_create(
                        plan=plan,
                        service=svc,
                        defaults={'is_included': False}
                    )
                    if not created and mapping.is_included:
                        mapping.is_included = False
                        mapping.save()
                except IntegrityError:
                    pass

    # 4. Synchronize existing basic tenant subscriptions if they still have the old amount/limit
    try:
        from tenants.models import TenantSubscription, Client
        from decimal import Decimal
        basic_clients = Client.objects.filter(subscription_plan='basic')
        for client in basic_clients:
            sub = TenantSubscription.objects.filter(tenant=client).first()
            if sub:
                from pricing.models import TenantAddonGrant
                addons_count = TenantAddonGrant.objects.filter(tenant_schema=client.schema_name, service__name='Units', is_active=True).count()
                if addons_count == 0:
                    updated = False
                    if sub.max_units != 10:
                        sub.max_units = 10
                        updated = True
                    if float(sub.monthly_amount) != 99.99:
                        sub.monthly_amount = Decimal('99.99')
                        updated = True
                    if updated:
                        sub.save()
                        logger.info(f"Updated existing basic tenant {client.name} subscription to $99.99 and 10 units.")
        
        # Sync existing pending activation invoices for basic plan
        from tenants.models import PlatformInvoice
        for client in basic_clients:
            inv = PlatformInvoice.objects.filter(tenant=client, status='pending', plan_name='basic').first()
            if inv:
                if float(inv.amount) != 99.99:
                    inv.amount = Decimal('99.99')
                    inv.save()
                    logger.info(f"Updated pending basic activation invoice {inv.invoice_number} to $99.99")
    except Exception as e:
        logger.error(f"Failed to sync existing subscriptions/invoices: {e}")

    # Mark as seeded for 1 hour so subsequent requests skip all DB work
    cache.set(CACHE_KEY, True, 3600)


class PublicPricingView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PricingPlanSerializer

    def get(self, request):
        ensure_pricing_seeded()
        plans = (
            PricingPlan.objects
            .filter(is_active=True, slug__in=['basic', 'premium', 'enterprise'])
            .prefetch_related('service_mappings__service', 'features')
        )
        return Response(PricingPlanSerializer(plans, many=True).data)


class PricingPlanDetailView(APIView):
    """SuperAdmin: update a pricing plan"""
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        plan = get_object_or_404(PricingPlan, pk=pk)
        serializer = PricingPlanSerializer(plan, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            from django.core.cache import cache
            cache.delete('pricing_seeded_v1')
            return Response(serializer.data)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)


class TenantSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def _get_schema(self, request):
        return getattr(getattr(request, 'tenant', None), 'schema_name', '')

    def get(self, request):
        # Direct database sync on API request to force update
        try:
            from pricing.models import PricingPlan, PlanService, AddOnRequest
            from tenants.models import TenantSubscription, Client, PlatformInvoice
            from decimal import Decimal
            from django.db.models import Sum
            
            # 1. Update Basic Plan
            plan = PricingPlan.objects.filter(slug='basic').first()
            if plan:
                plan.monthly_price = Decimal('9.99')
                plan.unit_limit = 10
                plan.save()
                
            # 2. Update Units Service
            service = PlanService.objects.filter(name='Units').first()
            if service:
                service.price_per_unit = Decimal('9.00')
                service.save()
                
            # 3. Update TenantSubscriptions for basic clients dynamically based on approved addons
            basic_clients = Client.objects.filter(subscription_plan__iexact='basic')
            for client in basic_clients:
                sub_rec = TenantSubscription.objects.filter(tenant=client).first()
                if sub_rec:
                    # Sum approved Units requests
                    approved_units = AddOnRequest.objects.filter(
                        tenant_schema=client.schema_name,
                        service__name='Units',
                        status='approved'
                    ).aggregate(sum_qty=Sum('quantity'))['sum_qty'] or 0
                    
                    # Sum approved other addon requests
                    approved_other_cost = AddOnRequest.objects.filter(
                        tenant_schema=client.schema_name,
                        status='approved'
                    ).exclude(service__name='Units').aggregate(sum_cost=Sum('monthly_price'))['sum_cost'] or Decimal('0.00')
                    
                    sub_rec.max_units = 10 + approved_units
                    
                    unit_price_dec = service.price_per_unit if service else Decimal('9.00')
                    sub_rec.monthly_amount = Decimal('9.99') + (sub_rec.max_units * unit_price_dec) + approved_other_cost
                    sub_rec.save()
                    
                    # 4. Update Pending Activation Invoices for this client
                    invoices = PlatformInvoice.objects.filter(tenant=client, status='pending')
                    for inv in invoices:
                        if inv.plan_name in ['basic', 'premium', 'enterprise'] or inv.remarks.startswith('Activation Invoice'):
                            # Activation invoice should strictly be the base subscription price (e.g. $99.99 for Basic)
                            # Extra units approved during the month are billed on the next recurring platform invoice
                            inv.amount = Decimal('9.99') + (Decimal('10') * unit_price_dec)
                            inv.save()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Direct sync error: {e}")

        ensure_pricing_seeded()
        schema = self._get_schema(request)
        from .models import TenantAddonGrant, AddOnRequest, PlanService, PricingPlan
        
        # Fetch units price per unit
        units_service = PlanService.objects.filter(name='Units').first()
        unit_price = float(units_service.price_per_unit) if units_service else 9.00
        
        # Fetch all pending requests for this tenant
        pending_reqs_qs = AddOnRequest.objects.filter(tenant_schema=schema, status='pending').select_related('service')
        pending_requests = []
        for req in pending_reqs_qs:
            pending_requests.append({
                'id': str(req.id),
                'service_name': req.service.name,
                'quantity': req.quantity,
                'monthly_price': float(req.monthly_price),
                'created_at': req.created_at
            })

        try:
            sub = (
                Subscription.objects
                .select_related('plan')
                .prefetch_related('plan__service_mappings__service', 'plan__features')
                .get(tenant_schema=schema)
            )

            # Fetch active addons for this tenant
            addons = TenantAddonGrant.objects.filter(tenant_schema=schema, is_active=True).select_related('service', 'addon_request')
            addons_data = []
            total_addons_cost = 0
            
            extra_units = 0
            extra_units_cost = 0.0

            for grant in addons:
                if grant.service.name == 'Units':
                    qty = grant.addon_request.quantity if grant.addon_request else 0
                    price = float(grant.addon_request.monthly_price) if grant.addon_request else 0.0
                    extra_units += qty
                    extra_units_cost += price
                else:
                    qty = 1
                    price = float(grant.service.price_per_unit)
                
                addons_data.append({
                    'id': str(grant.id),
                    'service_name': grant.service.name,
                    'price': price,
                    'quantity': qty,
                    'granted_at': grant.granted_at
                })
                total_addons_cost += price
            
            sub_price = float(sub.plan.monthly_price or 0) if sub.billing_cycle == 'monthly' else (float(sub.plan.annual_price or 0) / 12)
            unit_limit = sub.plan.unit_limit if sub.plan else 0
            included_units_cost = unit_limit * unit_price
            
            # Fetch TenantSubscription to get dynamic monthly_amount and max_units
            from tenants.models import TenantSubscription
            tenant_sub = TenantSubscription.objects.filter(tenant__schema_name=schema).first()
            if tenant_sub:
                total_monthly_cost = float(tenant_sub.monthly_amount)
                max_units = tenant_sub.max_units
            else:
                total_monthly_cost = sub_price + included_units_cost + total_addons_cost
                max_units = unit_limit + extra_units
            
            # Recalculate extra units if max_units differs
            if max_units is not None and max_units > unit_limit:
                extra_units = max_units - unit_limit
                extra_units_cost = extra_units * unit_price
            
            sub_data = SubscriptionSerializer(sub).data
            
            from tenants.models import PlatformInvoice
            latest_inv = PlatformInvoice.objects.filter(tenant__schema_name=schema).order_by('-created_at').first()
            current_month_invoice = float(latest_inv.amount) if latest_inv else (sub_price + included_units_cost)

            return Response({
                'subscription': sub_data,
                'addons': addons_data,
                'plan_cost': sub_price,
                'total_monthly_cost': total_monthly_cost,
                'max_units': max_units,
                'billing_cycle': sub.billing_cycle,
                'status': sub.status,
                'start_date': sub.current_period_start or sub.created_at,
                'end_date': sub.current_period_end,
                
                # New fields for breakdown
                'unit_limit': unit_limit,
                'unit_price': unit_price,
                'included_units_cost': included_units_cost,
                'extra_units': extra_units,
                'extra_units_cost': extra_units_cost,
                'pending_requests': pending_requests,
                'current_month_invoice': current_month_invoice,
            })
        except Subscription.DoesNotExist:
            from tenants.models import Client
            tenant_obj = Client.objects.filter(schema_name=schema).first()
            if tenant_obj:
                plan_slug = tenant_obj.subscription_plan or 'basic'
                plan = PricingPlan.objects.filter(slug=plan_slug).first()
                if plan:
                    sub_price = float(plan.monthly_price)
                    unit_limit = plan.unit_limit
                else:
                    sub_price = 9.99 if plan_slug == 'basic' else (79.99 if plan_slug == 'premium' else 199.99)
                    unit_limit = 10 if plan_slug == 'basic' else (200 if plan_slug == 'premium' else 99999)
                
                # Fetch active addons for this tenant
                addons = TenantAddonGrant.objects.filter(tenant_schema=schema, is_active=True).select_related('service', 'addon_request')
                addons_data = []
                total_addons_cost = 0
                extra_units = 0
                extra_units_cost = 0.0

                for grant in addons:
                    if grant.service.name == 'Units':
                        qty = grant.addon_request.quantity if grant.addon_request else 0
                        price = float(grant.addon_request.monthly_price) if grant.addon_request else 0.0
                        extra_units += qty
                        extra_units_cost += price
                    else:
                        qty = 1
                        price = float(grant.service.price_per_unit)
                    
                    addons_data.append({
                        'id': str(grant.id),
                        'service_name': grant.service.name,
                        'price': price,
                        'quantity': qty,
                        'granted_at': grant.granted_at
                    })
                    total_addons_cost += price
                
                included_units_cost = unit_limit * unit_price

                from tenants.models import TenantSubscription
                tenant_sub = TenantSubscription.objects.filter(tenant=tenant_obj).first()
                if tenant_sub:
                    total_monthly_cost = float(tenant_sub.monthly_amount)
                    max_units = tenant_sub.max_units
                else:
                    total_monthly_cost = sub_price + included_units_cost + total_addons_cost
                    max_units = unit_limit + extra_units
                
                if max_units is not None and max_units > unit_limit:
                    extra_units = max_units - unit_limit
                    extra_units_cost = extra_units * unit_price

                from tenants.models import PlatformInvoice
                latest_inv = PlatformInvoice.objects.filter(tenant=tenant_obj).order_by('-created_at').first()
                current_month_invoice = float(latest_inv.amount) if latest_inv else (sub_price + included_units_cost)

                return Response({
                    'subscription': {
                        'plan': {
                            'name': plan_slug.capitalize() + " Plan",
                            'monthly_price': sub_price,
                            'annual_price': sub_price * 12,
                            'description': 'Organization subscription plan'
                        },
                        'billing_cycle': 'monthly',
                        'status': 'active',
                        'created_at': tenant_obj.created_on
                    },
                    'addons': addons_data,
                    'plan_cost': sub_price,
                    'total_monthly_cost': total_monthly_cost,
                    'max_units': max_units,
                    'billing_cycle': 'monthly',
                    'status': 'active',
                    'start_date': tenant_obj.created_on,
                    'end_date': None,
                    
                    # New fields for breakdown
                    'unit_limit': unit_limit,
                    'unit_price': unit_price,
                    'included_units_cost': included_units_cost,
                    'extra_units': extra_units,
                    'extra_units_cost': extra_units_cost,
                    'pending_requests': pending_requests,
                    'current_month_invoice': current_month_invoice,
                })
            return Response({'status': 'no_subscription'}, status=404)


class SubscribeView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def post(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        plan_id = request.data.get('plan_id')
        billing_cycle = request.data.get('billing_cycle', 'monthly')
        try:
            plan = PricingPlan.objects.get(id=plan_id, is_active=True)
        except PricingPlan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=404)
        sub, created = Subscription.objects.get_or_create(
            tenant_schema=schema,
            defaults={'plan': plan, 'billing_cycle': billing_cycle, 'status': 'trialing'}
        )
        if not created:
            sub.plan = plan
            sub.billing_cycle = billing_cycle
            sub.status = 'active'
            sub.save()

        # Track analytics event
        try:
            from analytics.signals import track_event
            track_event(
                event_type='subscription_created',
                user=request.user,
                request=request,
                object_type='Subscription',
                object_id=str(sub.id),
                metadata={'plan_name': plan.name, 'billing_cycle': billing_cycle, 'was_new': created},
            )
        except Exception:
            pass

        return Response(SubscriptionSerializer(sub).data)


class UpgradePlanView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def post(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        plan_id = request.data.get('plan_id')
        billing_cycle = request.data.get('billing_cycle', 'monthly')
        try:
            plan = PricingPlan.objects.get(id=plan_id, is_active=True)
            sub = Subscription.objects.get(tenant_schema=schema)
        except (PricingPlan.DoesNotExist, Subscription.DoesNotExist):
            return Response({'error': 'Plan or subscription not found'}, status=404)
        sub.plan = plan
        sub.billing_cycle = billing_cycle
        sub.save()

        # Track analytics event
        try:
            from analytics.signals import track_event
            track_event(
                event_type='subscription_upgraded',
                user=request.user,
                request=request,
                object_type='Subscription',
                object_id=str(sub.id),
                metadata={'new_plan': plan.name, 'billing_cycle': billing_cycle},
            )
        except Exception:
            pass

        return Response(SubscriptionSerializer(sub).data)


class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def post(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        try:
            sub = Subscription.objects.get(tenant_schema=schema)
        except Subscription.DoesNotExist:
            return Response({'error': 'No active subscription'}, status=404)
        sub.status = 'cancelled'
        sub.cancelled_at = timezone.now()
        sub.save()

        # Track analytics event
        try:
            from analytics.signals import track_event
            track_event(
                event_type='subscription_cancelled',
                user=request.user,
                request=request,
                object_type='Subscription',
                object_id=str(sub.id),
                metadata={'plan_name': sub.plan.name},
            )
        except Exception:
            pass

        return Response({'status': 'cancelled', 'message': 'Subscription cancelled successfully'})


class CreateRazorpaySubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def post(self, request):
        if not RAZORPAY_AVAILABLE:
            return Response({'error': 'Razorpay not configured'}, status=503)
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        plan_id = request.data.get('plan_id')
        billing_cycle = request.data.get('billing_cycle', 'monthly')
        try:
            plan = PricingPlan.objects.get(id=plan_id, is_active=True)
        except PricingPlan.DoesNotExist:
            return Response({'error': 'Plan not found'}, status=404)
        if not plan.razorpay_plan_id:
            return Response({'error': 'Razorpay plan not configured'}, status=400)
        try:
            client = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )
            subscription = client.subscription.create({
                'plan_id': plan.razorpay_plan_id,
                'total_count': 12 if billing_cycle == 'monthly' else 1,
                'notes': {'tenant_schema': schema, 'plan_name': plan.name},
            })
            return Response({
                'subscription_id': subscription['id'],
                'razorpay_key_id': settings.RAZORPAY_KEY_ID,
                'plan_name': plan.name,
                'amount': float(plan.monthly_price if billing_cycle == 'monthly' else plan.annual_price),
                'currency': 'INR',
            })
        except Exception as e:
            return Response({'error': str(e)}, status=400)


class VerifyRazorpaySubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def post(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        razorpay_subscription_id = request.data.get('razorpay_subscription_id')
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_signature = request.data.get('razorpay_signature')
        plan_id = request.data.get('plan_id')
        billing_cycle = request.data.get('billing_cycle', 'monthly')
        msg = f"{razorpay_payment_id}|{razorpay_subscription_id}"
        key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
        expected = hmac.new(key_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, razorpay_signature or ''):
            return Response({'error': 'Invalid signature'}, status=400)
        try:
            plan = PricingPlan.objects.get(id=plan_id)
            sub, _ = Subscription.objects.get_or_create(
                tenant_schema=schema,
                defaults={'plan': plan, 'billing_cycle': billing_cycle}
            )
            sub.plan = plan
            sub.billing_cycle = billing_cycle
            sub.status = 'active'
            sub.razorpay_subscription_id = razorpay_subscription_id
            sub.current_period_start = timezone.now()
            sub.save()
            return Response({'status': 'success', 'subscription': SubscriptionSerializer(sub).data})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class AllSubscriptionsView(APIView):
    """SuperAdmin: list all tenant subscriptions"""
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def get(self, request):
        from tenants.models import Client
        existing_schemas = Client.objects.exclude(
            schema_name='public'
        ).values_list('schema_name', flat=True)
        subscriptions = (
            Subscription.objects
            .select_related('plan')
            .prefetch_related('plan__service_mappings__service', 'plan__features')
            .filter(tenant_schema__in=existing_schemas)
        )
        return Response(SubscriptionSerializer(subscriptions, many=True).data)


class SubscriptionDetailView(APIView):
    """SuperAdmin: update a tenant subscription"""
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def patch(self, request, pk):
        subscription = get_object_or_404(Subscription, pk=pk)
        plan_id = request.data.get('plan_id')
        if plan_id:
            plan = get_object_or_404(PricingPlan, id=plan_id)
            subscription.plan = plan
        
        serializer = SubscriptionSerializer(subscription, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)


class RevenueSummaryView(APIView):
    """SuperAdmin: revenue metrics"""
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer

    def get(self, request):
        from django.db.models import Count, Q, Sum, Case, When, F, FloatField
        from tenants.models import Client
        
        # Only consider subscriptions for existing (non-public) tenants
        existing_schemas = Client.objects.exclude(
            schema_name='public'
        ).values_list('schema_name', flat=True)
        all_existing_subs = Subscription.objects.filter(tenant_schema__in=existing_schemas)

        stats = all_existing_subs.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(status='active')),
            cancelled=Count('id', filter=Q(status='cancelled')),
            trialing=Count('id', filter=Q(status='trialing')),
            mrr=Sum(
                Case(
                    When(status='active', billing_cycle='monthly', then=F('plan__monthly_price')),
                    When(status='active', billing_cycle='annual', then=F('plan__annual_price') / 12.0),
                    default=0.0,
                    output_field=FloatField()
                )
            )
        )

        mrr = float(stats['mrr'] or 0.0)
        arr = mrr * 12
        plan_distribution = list(
            all_existing_subs.filter(status='active').values('plan__name').annotate(count=Count('id')).order_by('-count')
        )
        
        return Response({
            'mrr': round(mrr, 2),
            'arr': round(arr, 2),
            'active_subscriptions': stats['active'] or 0,
            'total_subscriptions': stats['total'] or 0,
            'cancelled_subscriptions': stats['cancelled'] or 0,
            'trial_subscriptions': stats['trialing'] or 0,
            'plan_distribution': plan_distribution,
        })


class PlanServiceListCreateView(APIView):
    """SuperAdmin: list and create plan services"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ensure_pricing_seeded() is intentionally skipped here — services are
        # always present after first run and the seeder is guarded by cache.
        # Calling it on every list request added ~75 extra queries.
        services = PlanService.objects.all()
        return Response(PlanServiceSerializer(services, many=True).data)

    def post(self, request):
        serializer = PlanServiceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=http_status.HTTP_201_CREATED)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)


class PlanServiceDetailView(APIView):
    """SuperAdmin: retrieve, update, delete a plan service"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        svc = get_object_or_404(PlanService, pk=pk)
        return Response(PlanServiceSerializer(svc).data)

    def put(self, request, pk):
        svc = get_object_or_404(PlanService, pk=pk)
        serializer = PlanServiceSerializer(svc, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        get_object_or_404(PlanService, pk=pk).delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class PlanServicesByPlanView(APIView):
    """Public: get included + addon services for a specific plan"""
    permission_classes = [AllowAny]

    def get(self, request, plan_id):
        ensure_pricing_seeded()
        plan = get_object_or_404(PricingPlan, id=plan_id, is_active=True)
        mappings = (
            PlanServiceMapping.objects
            .filter(plan=plan, service__is_active=True)
            .select_related('service')
        )
        included, addons = [], []
        for m in mappings:
            entry = {
                'id': str(m.service.id),
                'mapping_id': str(m.id),
                'name': m.service.name,
                'description': m.service.description,
                'price_per_unit': float(m.service.price_per_unit),
            }
            (included if m.is_included else addons).append(entry)
        return Response({
            'plan_id': str(plan.id),
            'plan_name': plan.name,
            'included_services': included,
            'addon_services': addons,
        })


class PlanServiceMappingListCreateView(APIView):
    """SuperAdmin: list and create plan-service mappings"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ensure_pricing_seeded() skipped — mappings exist after first boot and
        # seeder overhead (~75 queries) on every list request is eliminated.
        mappings = PlanServiceMapping.objects.select_related('plan', 'service').all()
        return Response(PlanServiceMappingSerializer(mappings, many=True).data)

    def post(self, request):
        serializer = PlanServiceMappingSerializer(data=request.data)
        if serializer.is_valid():
            try:
                serializer.save()
                return Response(serializer.data, status=http_status.HTTP_201_CREATED)
            except Exception as e:
                error_msg = str(e)
                if 'unique' in error_msg.lower() or 'integrity' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    return Response(
                        {'error': 'This service is already assigned to this plan. Each service can only be mapped once per plan.'},
                        status=http_status.HTTP_400_BAD_REQUEST
                    )
                return Response({'error': error_msg}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)


class PlanServiceMappingDetailView(APIView):
    """SuperAdmin: update or delete a plan-service mapping"""
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        mapping = get_object_or_404(PlanServiceMapping.objects.select_related('plan', 'service'), pk=pk)
        serializer = PlanServiceMappingSerializer(mapping, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        get_object_or_404(PlanServiceMapping, pk=pk).delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────
# ADD-ON SERVICES REQUEST FLOW
# ─────────────────────────────────────────────

class MyAddonsView(APIView):
    """
    MasterAdmin: Returns current plan's included services, available add-ons
    (services in the DB that are NOT included in the plan), and already-granted
    add-ons for this tenant.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        # Get current subscription
        try:
            sub = Subscription.objects.select_related('plan').get(tenant_schema=schema)
            plan = sub.plan
        except Subscription.DoesNotExist:
            return Response({'error': 'No active subscription'}, status=404)

        # Ensure all services and mappings are seeded in the database dynamically (Self-healing)
        services_data = [
            {'name': 'Dashboard', 'desc': 'Organization overview', 'price': 0},
            {'name': 'Communities', 'desc': 'Manage communities/projects', 'price': 0},
            {'name': 'Blocks/Sectors', 'desc': 'Manage blocks and sectors', 'price': 0},
            {'name': 'Units', 'desc': 'Manage individual units', 'price': 0},
            {'name': 'People Hub', 'desc': 'Resident and owner management', 'price': 0},
            {'name': 'Facility Managers', 'desc': 'Manage facility staff', 'price': 0},
            {'name': 'Documents', 'desc': 'Document storage and management', 'price': 0},
            {'name': 'Payments', 'desc': 'Fee collection and invoicing', 'price': 0},
            {'name': 'Maintenance', 'desc': 'Service requests and tracking', 'price': 0},
            {'name': 'Rental Hub', 'desc': 'Manage rentals and tenants', 'price': 799},
            {'name': 'Reports', 'desc': 'Advanced analytics and exports', 'price': 1499},
            {'name': 'Amenities', 'desc': 'Clubhouse and facility booking', 'price': 799},
            {'name': 'Security', 'desc': 'Visitor and gate management', 'price': 1200},
            {'name': 'Vendors', 'desc': 'Vendor and AMC management', 'price': 599},
            {'name': 'Message Center', 'desc': 'Broadcast messages and alerts', 'price': 499},

            {'name': 'Senior Hub Managers', 'desc': 'Higher-level staff management', 'price': 999},
            {'name': 'Support Center', 'desc': 'Priority support access', 'price': 1000},
        ]
        
        # Ensure services exist
        services = {}
        for s in services_data:
            svc = PlanService.objects.filter(name=s['name']).first()
            if not svc:
                svc = PlanService.objects.create(
                    name=s['name'],
                    description=s['desc'],
                    price_per_unit=s['price'],
                    is_active=True
                )
            services[s['name']] = svc
            
        # Define basic/premium/enterprise mappings
        plan_mappings = {
            'basic': {
                'included': ['Dashboard', 'Communities', 'Blocks/Sectors', 'Units', 'People Hub', 'Facility Managers', 'Documents', 'Payments', 'Maintenance'],
                'addons': ['Rental Hub', 'Reports', 'Amenities', 'Security', 'Vendors', 'Message Center', 'Senior Hub Managers', 'Support Center']
            },
            'premium': {
                'included': ['Dashboard', 'Communities', 'Blocks/Sectors', 'Units', 'People Hub', 'Facility Managers', 'Documents', 'Payments', 'Maintenance', 'Rental Hub', 'Reports'],
                'addons': ['Amenities', 'Security', 'Vendors', 'Message Center', 'Senior Hub Managers', 'Support Center']
            },
            'enterprise': {
                'included': ['Dashboard', 'Communities', 'Blocks/Sectors', 'Units', 'People Hub', 'Facility Managers', 'Documents', 'Payments', 'Maintenance', 'Rental Hub', 'Reports', 'Amenities', 'Security', 'Vendors', 'Message Center', 'Senior Hub Managers', 'Support Center'],
                'addons': []
            }
        }
        
        slug_lower = plan.slug.lower()
        if slug_lower in plan_mappings:
            mapping_rules = plan_mappings[slug_lower]
            for s_name in mapping_rules['included']:
                svc = services.get(s_name)
                if svc:
                    mapping = PlanServiceMapping.objects.filter(plan=plan, service=svc).first()
                    if not mapping:
                        PlanServiceMapping.objects.create(plan=plan, service=svc, is_included=True)
                    elif not mapping.is_included:
                        mapping.is_included = True
                        mapping.save()
            for s_name in mapping_rules['addons']:
                svc = services.get(s_name)
                if svc:
                    mapping = PlanServiceMapping.objects.filter(plan=plan, service=svc).first()
                    if not mapping:
                        PlanServiceMapping.objects.create(plan=plan, service=svc, is_included=False)
                    elif mapping.is_included:
                        mapping.is_included = False
                        mapping.save()

        # Services included in current plan
        included_ids = set(
            PlanServiceMapping.objects
            .filter(plan=plan, is_included=True)
            .values_list('service_id', flat=True)
        )

        # All active services
        all_services = PlanService.objects.filter(is_active=True)

        # Granted add-ons for this tenant
        grants = TenantAddonGrant.objects.filter(tenant_schema=schema, is_active=True).select_related('service')
        granted_ids = set(g.service_id for g in grants)

        # Pending requests
        pending_ids = set(
            AddOnRequest.objects.filter(tenant_schema=schema, status='pending')
            .values_list('service_id', flat=True)
        )

        # Approved but unpaid requests (pending payment)
        approved_ids = set(
            AddOnRequest.objects.filter(tenant_schema=schema, status='approved')
            .values_list('service_id', flat=True)
        )
        pending_payment_ids = approved_ids - granted_ids

        included_services = []
        addon_services = []

        for svc in all_services:
            entry = {
                'id': str(svc.id),
                'name': svc.name,
                'description': svc.description,
                'price_per_unit': float(svc.price_per_unit),
                'is_granted': str(svc.id) in [str(x) for x in granted_ids],
                'is_pending': str(svc.id) in [str(x) for x in pending_ids],
                'is_pending_payment': str(svc.id) in [str(x) for x in pending_payment_ids],
            }
            if svc.id in included_ids:
                included_services.append(entry)
            else:
                addon_services.append(entry)

        return Response({
            'plan_name': plan.name,
            'included_services': included_services,
            'addon_services': addon_services,
            'granted_addons': TenantAddonGrantSerializer(grants, many=True).data,
        })


class AddOnRequestListCreateView(APIView):
    """
    MasterAdmin:
    - GET  /api/pricing/addon-requests/           → list own requests
    - POST /api/pricing/addon-requests/           → create new requests (bulk)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        requests_qs = AddOnRequest.objects.filter(tenant_schema=schema).select_related('service')
        return Response(AddOnRequestSerializer(requests_qs, many=True).data)

    def post(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        service_ids = request.data.get('service_ids', [])
        notes = request.data.get('notes', '')
        quantity = int(request.data.get('quantity', 1))

        if not service_ids:
            return Response({'error': 'service_ids is required'}, status=400)

        created = []
        skipped = []
        for sid in service_ids:
            try:
                svc = PlanService.objects.get(id=sid, is_active=True)
            except PlanService.DoesNotExist:
                skipped.append(str(sid))
                continue

            is_units = (svc.name == 'Units')

            # Skip if already pending
            already = AddOnRequest.objects.filter(
                tenant_schema=schema, service_id=sid, status='pending'
            ).exists()

            # For non-units, also skip if already active (granted)
            granted = False
            if not is_units:
                granted = TenantAddonGrant.objects.filter(
                    tenant_schema=schema, service_id=sid, is_active=True
                ).exists()

            if already or granted:
                skipped.append(str(sid))
                continue

            req_qty = quantity if is_units else 1
            req = AddOnRequest.objects.create(
                tenant_schema=schema,
                service=svc,
                status='pending',
                requested_by_email=request.user.email,
                requested_by_name=f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
                monthly_price=svc.price_per_unit * req_qty,
                quantity=req_qty,
                notes=notes,
            )
            created.append(AddOnRequestSerializer(req).data)

        return Response({
            'created': created,
            'skipped_count': len(skipped),
            'message': f'{len(created)} request(s) submitted. {len(skipped)} skipped (already pending or granted).'
        }, status=http_status.HTTP_201_CREATED)


class AllAddOnRequestsView(APIView):
    """
    SuperAdmin: List all add-on requests across all tenants.
    Optional ?tenant=<schema> filter.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_filter = request.query_params.get('tenant')
        qs = AddOnRequest.objects.select_related('service')
        if tenant_filter:
            qs = qs.filter(tenant_schema=tenant_filter)
        return Response(AddOnRequestSerializer(qs, many=True).data)


class AddOnRequestApproveView(APIView):
    """
    SuperAdmin: Approve a pending add-on request.
    Creates a TenantAddonGrant entry (inactive) and generates a pending PlatformInvoice.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        addon_req = get_object_or_404(AddOnRequest, pk=pk)
        if addon_req.status != 'pending':
            return Response({'error': f'Request is already {addon_req.status}'}, status=400)

        # 1. Update status to approved
        addon_req.status = 'approved'
        addon_req.review_notes = request.data.get('review_notes', '')
        addon_req.reviewed_by_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
        addon_req.save()

        is_units_service = addon_req.service.name == 'Units'

        if is_units_service:
            # 2. Create the grant in ACTIVE state immediately
            grant, _ = TenantAddonGrant.objects.update_or_create(
                tenant_schema=addon_req.tenant_schema,
                service=addon_req.service,
                defaults={'is_active': True, 'revoked_at': None, 'addon_request': addon_req}
            )

            # 3. Upgrade limit inside the tenant's schema context
            from tenants.models import Client
            try:
                tenant_obj = Client.objects.get(schema_name=addon_req.tenant_schema)
            except Client.DoesNotExist:
                return Response({'error': 'Tenant organization not found'}, status=404)

            from django_tenants.utils import schema_context
            try:
                with schema_context(addon_req.tenant_schema):
                    from tenants.models import TenantSubscription
                    tenant_sub = TenantSubscription.objects.filter(tenant=tenant_obj).first()
                    if tenant_sub:
                        tenant_sub.max_units += addon_req.quantity
                        tenant_sub.monthly_amount += addon_req.monthly_price
                        tenant_sub.save()
            except Exception as e:
                logger.error(f"Failed to update units limit for tenant {addon_req.tenant_schema}: {e}")

            return Response({
                'message': f"Add-on '{addon_req.service.name}' approved and limit upgraded for {addon_req.tenant_schema} by {addon_req.quantity} units. Cost added to recurring monthly subscription.",
                'request': AddOnRequestSerializer(addon_req).data,
                'grant': TenantAddonGrantSerializer(grant).data,
            })

        # 2. Create the grant in INACTIVE state (is_active=False) - activated upon invoice payment
        grant, _ = TenantAddonGrant.objects.update_or_create(
            tenant_schema=addon_req.tenant_schema,
            service=addon_req.service,
            defaults={'is_active': False, 'revoked_at': None, 'addon_request': addon_req}
        )

        # 3. Create PlatformInvoice
        from tenants.models import Client, PlatformInvoice
        import datetime
        try:
            tenant_obj = Client.objects.get(schema_name=addon_req.tenant_schema)
        except Client.DoesNotExist:
            return Response({'error': 'Tenant organization not found'}, status=404)

        # Map pricing service name to JSON feature key
        SERVICE_TO_FEATURE_KEY = {
            'Dashboard': 'dashboard',
            'Communities': 'communities',
            'Blocks/Sectors': 'buildings',
            'Units': 'units',
            'People Hub': 'people_hub',
            'Facility Managers': 'facility_managers',
            'Senior Hub Managers': 'senior_managers',
            'Rental Hub': 'leases',
            'Documents': 'documents',
            'Bulk Upload': 'bulk_upload',
            'Bulk Export': 'bulk_export',
            'Payments': 'payments',
            'Maintenance': 'maintenance',
            'Amenities': 'amenities',
            'Security': 'security',
            'Vendors': 'vendors',
            'Calendar': 'calendar',
            'Message Center': 'communication',
            'Support Center': 'support',
            'Developer Portal': 'developer_portal',
            'Reports': 'reports',
        }
        feature_key = SERVICE_TO_FEATURE_KEY.get(addon_req.service.name, addon_req.service.name.lower())

        due_date = datetime.date.today() + datetime.timedelta(days=7)
        invoice = PlatformInvoice.objects.create(
            tenant=tenant_obj,
            amount=addon_req.monthly_price,
            plan_name=f"Add-on: {addon_req.service.name}",
            billing_email=addon_req.requested_by_email or tenant_obj.contact_email or 'billing@hoaconnecthub.com',
            due_date=due_date,
            status='pending',
            pending_features=[feature_key],
            remarks=f"Approved Add-on Service Request for {addon_req.service.name}"
        )

        return Response({
            'message': f"Add-on '{addon_req.service.name}' approved for {addon_req.tenant_schema}. Invoice {invoice.invoice_number} generated for payment.",
            'request': AddOnRequestSerializer(addon_req).data,
            'grant': TenantAddonGrantSerializer(grant).data,
        })


class AddOnRequestRejectView(APIView):
    """
    SuperAdmin: Reject a pending add-on request.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        addon_req = get_object_or_404(AddOnRequest, pk=pk)
        if addon_req.status != 'pending':
            return Response({'error': f'Request is already {addon_req.status}'}, status=400)

        addon_req.status = 'rejected'
        addon_req.review_notes = request.data.get('review_notes', 'Request was not approved.')
        addon_req.reviewed_by_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
        addon_req.save()

        return Response({
            'message': f"Add-on request for '{addon_req.service.name}' has been rejected.",
            'request': AddOnRequestSerializer(addon_req).data,
        })
