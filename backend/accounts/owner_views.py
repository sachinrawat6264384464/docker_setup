from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ActivityLog
from .serializers import UserSerializer, UserUpdateSerializer

User = get_user_model()


def _require_owner(user):
    if getattr(user, 'role', None) != 'owner':
        return Response(
            {'error': 'Only property owners can access this endpoint'},
            status=http_status.HTTP_403_FORBIDDEN,
        )
    return None


def _unit_tenant_q(owner):
    query = Q(role='tenant')
    if owner.unit_number:
        query &= Q(unit_number=owner.unit_number)
    if owner.building_name:
        query &= Q(building_name=owner.building_name)

    # Keep tenant schema scoping aligned with current owner context.
    if owner.tenant_id:
        query &= Q(tenant_id=owner.tenant_id)
    return query


def _safe_activity_log(*, user, action, description, affected_user=None, metadata=None):
    ActivityLog.objects.create(
        user=user,
        action=action,
        description=description,
        affected_user=affected_user,
        tenant_schema=user.tenant_id or '',
        metadata=metadata or {},
    )


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_dashboard_stats(request):
    err = _require_owner(request.user)
    if err:
        return err

    owner = request.user
    stats = {
        'active_tenants': 0,
        'vacant_units': 0,
        'rent_due': 0.0,
        'pending_invites': 0,
        'tenant_issues': 0,
        'unit_info': {
            'unit_number': owner.unit_number or '',
            'building_name': owner.building_name or '',
        },
    }

    tenant_qs = User.objects.filter(_unit_tenant_q(owner))
    stats['active_tenants'] = tenant_qs.filter(is_active=True, is_approved=True).count()
    stats['pending_invites'] = tenant_qs.filter(is_active=True, is_approved=False).count()

    try:
        from payments.models import Invoice

        invoice_qs = Invoice.objects.filter(user__in=tenant_qs, status__in=['pending', 'overdue', 'partially_paid'])
        stats['rent_due'] = float(invoice_qs.aggregate(total=Sum('amount_due'))['total'] or 0)
    except Exception:
        # Optional stats block; keep endpoint stable even if an app is unavailable.
        pass

    try:
        from maintenance.models import MaintenanceRequest

        issues_qs = MaintenanceRequest.objects.filter(
            requested_by__in=tenant_qs,
            status__in=['submitted', 'acknowledged', 'assigned', 'in_progress', 'on_hold'],
        )
        stats['tenant_issues'] = issues_qs.count()
    except Exception:
        pass

    try:
        from properties.models import Unit

        if owner.unit_number and owner.building_name:
            owner_unit = Unit.objects.filter(
                unit_number__iexact=owner.unit_number,
                building__name__iexact=owner.building_name,
            ).first()
            if owner_unit and (not owner_unit.is_occupied or owner_unit.status == 'vacant'):
                stats['vacant_units'] = 1
    except Exception:
        pass

    return Response(stats)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_tenants_list(request):
    err = _require_owner(request.user)
    if err:
        return err

    tenants = User.objects.filter(_unit_tenant_q(request.user)).order_by('first_name', 'last_name', 'email')
    serializer = UserSerializer(tenants, many=True)
    return Response({'results': serializer.data, 'count': tenants.count()})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def owner_invite_tenant(request):
    err = _require_owner(request.user)
    if err:
        return err

    owner = request.user
    email = (request.data.get('email') or '').strip().lower()
    if not email:
        return Response({'error': 'Email is required.'}, status=http_status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email__iexact=email).exists():
        return Response({'error': 'A user with this email already exists.'}, status=http_status.HTTP_400_BAD_REQUEST)

    first_name = (request.data.get('first_name') or '').strip()
    last_name = (request.data.get('last_name') or '').strip()
    phone = (request.data.get('phone') or '').strip()

    temp_password = User.objects.make_random_password()
    tenant = User.objects.create_user(
        username=email,
        email=email,
        password=temp_password,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        role='tenant',
        unit_number=owner.unit_number or '',
        building_name=owner.building_name or '',
        tenant_id=owner.tenant_id,
        is_approved=False,
        is_active=True,
    )

    _safe_activity_log(
        user=owner,
        action='tenant_invited',
        description=f'Owner invited tenant {email} to unit {owner.unit_number}',
        affected_user=tenant,
        metadata={'invited_by': str(owner.id)},
    )

    return Response(UserSerializer(tenant).data, status=http_status.HTTP_201_CREATED)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def owner_tenant_detail(request, tenant_id):
    err = _require_owner(request.user)
    if err:
        return err

    query = _unit_tenant_q(request.user) & Q(id=tenant_id)
    tenant = User.objects.filter(query).first()
    if not tenant:
        return Response(
            {'error': 'Tenant not found or not assigned to your unit.'},
            status=http_status.HTTP_404_NOT_FOUND,
        )

    if request.method == 'GET':
        return Response(UserSerializer(tenant).data)

    if request.method == 'PATCH':
        allowed = {'first_name', 'last_name', 'phone', 'email'}
        payload = {k: v for k, v in request.data.items() if k in allowed}
        serializer = UserUpdateSerializer(tenant, data=payload, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            _safe_activity_log(
                user=request.user,
                action='tenant_updated',
                description=f'Owner updated tenant {tenant.email}',
                affected_user=tenant,
            )
            return Response(serializer.data)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    # DELETE as move-out: keep account for history, unassign from owner's unit.
    tenant.is_active = False
    tenant.unit_number = ''
    tenant.building_name = ''
    tenant.save(update_fields=['is_active', 'unit_number', 'building_name', 'updated_at'])

    _safe_activity_log(
        user=request.user,
        action='tenant_moved_out',
        description=f'Owner moved out tenant {tenant.email} from unit {request.user.unit_number}',
        affected_user=tenant,
    )

    return Response({'message': 'Tenant moved out successfully.'})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def owner_approve_tenant(request, tenant_id):
    err = _require_owner(request.user)
    if err:
        return err

    tenant = User.objects.filter(_unit_tenant_q(request.user) & Q(id=tenant_id)).first()
    if not tenant:
        return Response({'error': 'Tenant not found.'}, status=http_status.HTTP_404_NOT_FOUND)

    tenant.is_approved = True
    tenant.save(update_fields=['is_approved', 'updated_at'])

    _safe_activity_log(
        user=request.user,
        action='tenant_approved',
        description=f'Owner approved tenant {tenant.email}',
        affected_user=tenant,
    )

    return Response({'message': 'Tenant approved.'})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def owner_tenant_summary(request, tenant_id):
    err = _require_owner(request.user)
    if err:
        return err

    tenant = User.objects.filter(_unit_tenant_q(request.user) & Q(id=tenant_id)).first()
    if not tenant:
        return Response({'error': 'Tenant not found.'}, status=http_status.HTTP_404_NOT_FOUND)

    summary = {
        'tenant': UserSerializer(tenant).data,
        'payments': {'total_paid': 0.0, 'pending': 0.0, 'recent': []},
        'maintenance': {'total': 0, 'pending': 0, 'recent': []},
        'lease': None,
    }

    try:
        from payments.models import Payment, Invoice

        paid_total = Payment.objects.filter(user=tenant, status='completed').aggregate(total=Sum('amount'))['total'] or 0
        due_total = Invoice.objects.filter(user=tenant, status__in=['pending', 'overdue', 'partially_paid']).aggregate(total=Sum('amount_due'))['total'] or 0
        recent_payments = list(
            Payment.objects.filter(user=tenant)
            .order_by('-created_at')
            .values('id', 'amount', 'status', 'payment_date')[:5]
        )

        summary['payments'] = {
            'total_paid': float(paid_total),
            'pending': float(due_total),
            'recent': recent_payments,
        }
    except Exception:
        pass

    try:
        from maintenance.models import MaintenanceRequest

        maintenance_qs = MaintenanceRequest.objects.filter(requested_by=tenant)
        summary['maintenance'] = {
            'total': maintenance_qs.count(),
            'pending': maintenance_qs.filter(status__in=['submitted', 'acknowledged', 'assigned', 'in_progress', 'on_hold']).count(),
            'recent': list(
                maintenance_qs.order_by('-created_at').values('id', 'title', 'status', 'created_at')[:5]
            ),
        }
    except Exception:
        pass

    try:
        from properties.models import Lease

        lease = Lease.objects.filter(tenant=tenant, status='active').first()
        if lease:
            summary['lease'] = {
                'start_date': lease.start_date.isoformat() if lease.start_date else None,
                'end_date': lease.end_date.isoformat() if lease.end_date else None,
                'monthly_rent': float(lease.monthly_rent or 0),
                'status': lease.status,
            }
    except Exception:
        pass

    return Response(summary)
