from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from django.db.models import Count, Sum, Q
from django.db import connection
from django.db.utils import ProgrammingError
from django.contrib.auth import get_user_model
from datetime import datetime, timedelta
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

User = get_user_model()


def _get_tenant_scope_id(user):
    tenant_id = getattr(user, 'tenant_id', None)
    if tenant_id:
        return tenant_id
    return getattr(connection, 'schema_name', None)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def master_admin_stats(request):
    """
    Master Admin Dashboard Statistics
    Returns organization-wide stats for master admin
    """
    user = request.user
    if user.role not in ('master_admin', 'super_admin'):
        return Response(
            {'error': 'Only master admins and super admins can access this endpoint'},
            status=http_status.HTTP_403_FORBIDDEN,
        )
    tenant_id = user.tenant_id
    
    # Initialize stats dict
    stats = {
        'total_colonies': 0,
        'total_blocks': 0,
        'total_buildings': 0,
        'total_units': 0,
        'occupied_units': 0,
        'vacant_units': 0,
        'total_facility_managers': 0,
        'total_owners': 0,
        'total_tenants': 0,
        'total_residents': 0,
        'active_leases': 0,
        'under_process_rentals': 0,
        'expiring_leases': 0,
        'monthly_revenue': 0,
        'total_collection_monthly': 0,
        'overdue_amount': 0,
        'collection_rate': 0,
        'pending_payments': 0,
        'pending_maintenance': 0,
        'overdue_maintenance': 0,
        'assigned_maintenance': 0,
        'unassigned_maintenance': 0,
        'completed_maintenance': 0,
        'occupancy_rate': 0,
        'data_checks': {
            'units_vs_occupancy_delta': 0,
            'residents_vs_rentals_delta': 0,
            'payments_vs_revenue_delta': 0,
        }
    }
    
    try:
        is_public = connection.schema_name == 'public'

        # 1. Properties
        try:
            from properties.models import Township, Block, Building, Unit
            
            # These are usually tenant-specific unless explicitly made shared
            if not is_public:
                stats['total_colonies'] = Township.objects.filter(is_active=True).count()
                stats['total_blocks'] = Block.objects.filter(is_active=True).count()
                
                buildings = Building.objects.filter(is_active=True)
                stats['total_buildings'] = buildings.count()
                
                unit_stats = Unit.objects.aggregate(
                    total=Count('id'),
                    occupied=Count('id', filter=Q(status='occupied')),
                    vacant=Count('id', filter=Q(status='vacant'))
                )
                stats['total_units'] = unit_stats['total']
                stats['occupied_units'] = unit_stats['occupied']
                stats['vacant_units'] = unit_stats['vacant']
            else:
                # Public schema placeholder or overall totals logic (if implemented)
                pass
        except (ImportError, ProgrammingError):
            pass
        
        # 2. Roles / People
        user_stats = User.objects.filter(is_active=True).aggregate(
            facility_managers=Count('id', filter=Q(role='facility_manager')),
            owners=Count('id', filter=Q(role='owner')),
            tenants=Count('id', filter=Q(role='tenant'))
        )
        stats['total_facility_managers'] = user_stats['facility_managers']
        stats['total_owners'] = user_stats['owners']
        stats['total_tenants'] = user_stats['tenants']
        stats['total_residents'] = stats['total_tenants'] + stats['total_owners']
        
        # 3. Leases
        try:
            if not is_public:
                from properties.models import Lease
                thirty_days_from_now = timezone.now().date() + timedelta(days=30)
                
                active_leases = Lease.objects.filter(status='active')
                lease_stats = Lease.objects.aggregate(
                    active=Count('id', filter=Q(status='active')),
                    under_process=Count('id', filter=Q(status='pending')),
                    expiring=Count('id', filter=Q(status='active', end_date__lte=thirty_days_from_now)),
                    revenue=Sum('monthly_rent', filter=Q(status='active'))
                )
                stats['active_leases'] = lease_stats['active']
                stats['under_process_rentals'] = lease_stats['under_process']
                stats['expiring_leases'] = lease_stats['expiring']
                stats['monthly_revenue'] = float(lease_stats['revenue'] or 0)
        except (ImportError, ProgrammingError):
            pass
        
        # 4. Payments & Financials
        try:
            if not is_public:
                from payments.models import Payment, Invoice
                month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                payment_stats = Payment.objects.aggregate(
                    pending_payments=Sum('amount', filter=Q(status='pending')),
                    total_collection_monthly=Sum('amount', filter=Q(status='paid', updated_at__gte=month_start))
                )
                stats['pending_payments'] = float(payment_stats['pending_payments'] or 0)
                stats['total_collection_monthly'] = float(payment_stats['total_collection_monthly'] or 0)
                
                # overdue amount from Invoices
                stats['overdue_amount'] = float(Invoice.objects.filter(
                    status='overdue'
                ).aggregate(total=Sum('amount_due'))['total'] or 0)
                
                if stats['monthly_revenue'] > 0:
                    stats['collection_rate'] = round((stats['total_collection_monthly'] / stats['monthly_revenue']) * 100, 2)
        except (ImportError, ProgrammingError):
            pass
        
        # 5. Maintenance
        try:
            if not is_public:
                from maintenance.models import MaintenanceRequest
                
                three_days_ago = timezone.now() - timedelta(days=3)
                month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                m_stats = MaintenanceRequest.objects.aggregate(
                    pending=Count('id', filter=Q(status__in=['open', 'submitted', 'acknowledged', 'assigned', 'in_progress', 'on_hold'])),
                    unassigned=Count('id', filter=Q(status__in=['open', 'submitted', 'acknowledged', 'assigned', 'in_progress', 'on_hold'], assigned_to__isnull=True)),
                    assigned=Count('id', filter=Q(status__in=['open', 'submitted', 'acknowledged', 'assigned', 'in_progress', 'on_hold'], assigned_to__isnull=False)),
                    overdue=Count('id', filter=Q(status__in=['open', 'submitted', 'acknowledged', 'assigned', 'in_progress', 'on_hold'], requested_date__lt=three_days_ago)),
                    completed=Count('id', filter=Q(status='completed', updated_at__gte=month_start))
                )
                
                stats['pending_maintenance'] = m_stats['pending']
                stats['unassigned_maintenance'] = m_stats['unassigned']
                stats['assigned_maintenance'] = m_stats['assigned']
                stats['overdue_maintenance'] = m_stats['overdue']
                stats['completed_maintenance'] = m_stats['completed']
        except (ImportError, ProgrammingError):
            pass
            
        # 6. Support Tickets
        try:
            if not is_public:
                from support.models import Ticket
                ticket_stats = Ticket.objects.aggregate(
                    total=Count('id'),
                    open=Count('id', filter=Q(status='open')),
                    in_progress=Count('id', filter=Q(status='in_progress')),
                    resolved=Count('id', filter=Q(status='resolved')),
                    closed=Count('id', filter=Q(status='closed'))
                )
                stats['support_tickets'] = ticket_stats
        except (ImportError, ProgrammingError):
            pass
            
        # 7. Today's Alerts & Upcoming Alerts
        try:
            if not is_public:
                from calendar_alerts.models import CalendarAlert
                today = timezone.now().date()
                alerts = CalendarAlert.objects.filter(
                    start_datetime__date=today,
                    status__in=['scheduled', 'active']
                ).order_by('start_datetime')[:10]
                
                stats['today_alerts'] = [
                    {
                        'id': str(alert.id),
                        'title': alert.title,
                        'alert_type': alert.alert_type,
                        'priority': alert.priority,
                        'start_datetime': alert.start_datetime.isoformat(),
                    }
                    for alert in alerts
                ]
                
                thirty_days_later = today + timedelta(days=30)
                upcoming = CalendarAlert.objects.filter(
                    start_datetime__date__gt=today,
                    start_datetime__date__lte=thirty_days_later,
                    status__in=['scheduled', 'active']
                ).order_by('start_datetime')[:20]
                
                stats['upcoming_alerts'] = [
                    {
                        'id': str(alert.id),
                        'title': alert.title,
                        'alert_type': alert.alert_type,
                        'priority': alert.priority,
                        'start_datetime': alert.start_datetime.isoformat(),
                    }
                    for alert in upcoming
                ]
            else:
                stats['today_alerts'] = []
                stats['upcoming_alerts'] = []
        except (ImportError, ProgrammingError):
            stats['today_alerts'] = []
            stats['upcoming_alerts'] = []
        
        # Occupancy & Data Checks
        if stats['total_units'] > 0:
            stats['occupancy_rate'] = round((stats['occupied_units'] / stats['total_units']) * 100, 2)
            
        stats['data_checks']['units_vs_occupancy_delta'] = stats['total_units'] - (stats['occupied_units'] + stats['vacant_units'])
        stats['data_checks']['residents_vs_rentals_delta'] = stats['total_residents'] - stats['active_leases']
        stats['data_checks']['payments_vs_revenue_delta'] = stats['total_collection_monthly'] - stats['monthly_revenue']
        
        # Building Manager Mappings
        building_managers = []
        try:
            from properties.models import Building
            buildings = list(Building.objects.only('id', 'name'))
            building_names = [b.name for b in buildings]
            
            # Fetch all facility managers for these buildings in ONE query
            all_managers = User.objects.filter(
                role='facility_manager',
                building_name__in=building_names,
                is_active=True
            ).only('username', 'first_name', 'last_name', 'building_name')
            
            from collections import defaultdict
            managers_by_building = defaultdict(list)
            for m in all_managers:
                managers_by_building[m.building_name].append(m.get_full_name() or m.username)
                
            for b in buildings:
                manager_names = ", ".join(managers_by_building.get(b.name, []))
                building_managers.append({
                    'building_id': str(b.id),
                    'building_name': b.name,
                    'manager_name': manager_names or 'Unassigned'
                })
        except ImportError:
            pass
        stats['building_managers'] = building_managers
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error calculating master admin stats: {e}")
    
    return Response(stats)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def facility_manager_stats(request):
    """
    Facility Manager Dashboard Statistics
    Returns stats for buildings assigned to this facility manager
    """
    user = request.user
    if user.role not in ('master_admin', 'super_admin', 'facility_manager'):
        return Response(
            {'error': 'Only facility managers and above can access this endpoint'},
            status=http_status.HTTP_403_FORBIDDEN,
        )
    tenant_id = _get_tenant_scope_id(user)
    
    stats = {
        'total_buildings': 0,
        'total_units': 0,
        'occupied_units': 0,
        'total_residents': 0,
        'active_leases': 0,
        'pending_maintenance': 0,
    }
    
    try:
        try:
            from accounts.fm_scope import get_fm_scope
            scope = get_fm_scope(user) if user.role == 'facility_manager' else None

            if user.role == 'facility_manager' and scope is not None and not scope['building_ids'] and not scope['block_ids']:
                return Response(stats)

            from properties.models import Building, Unit, Lease
            from maintenance.models import MaintenanceRequest

            # 1. Total Buildings
            buildings = Building.objects.all()
            if user.role == 'facility_manager' and scope is not None:
                buildings = buildings.filter(id__in=scope['building_ids']).distinct()
            stats['total_buildings'] = buildings.count()

            # 2. Total Units
            units = Unit.objects.all()
            if user.role == 'facility_manager' and scope is not None:
                unit_q = Q()
                if scope['building_ids']:
                    unit_q |= Q(building_id__in=scope['building_ids'])
                if scope['block_ids']:
                    unit_q |= Q(floor_ref__block_id__in=scope['block_ids'])
                units = units.filter(unit_q) if unit_q.children else units.none()
            stats['total_units'] = units.count()
            stats['occupied_units'] = units.filter(status='occupied').count()

            # 3. Total Residents
            residents = User.objects.filter(role='tenant', tenant_id=tenant_id)
            if user.role == 'facility_manager' and scope is not None:
                building_names = list(buildings.values_list('name', flat=True))
                residents = residents.filter(building_name__in=building_names) if building_names else residents.none()
            stats['total_residents'] = residents.count()

            # 4. Active Leases
            leases = Lease.objects.filter(status='active')
            if user.role == 'facility_manager' and scope is not None:
                lease_q = Q()
                if scope['building_ids']:
                    lease_q |= Q(unit__building_id__in=scope['building_ids'])
                if scope['block_ids']:
                    lease_q |= Q(unit__floor_ref__block_id__in=scope['block_ids'])
                leases = leases.filter(lease_q) if lease_q.children else leases.none()
            stats['active_leases'] = leases.count()

            # 5. Pending Maintenance
            maint_qs = MaintenanceRequest.objects.filter(status__in=['open', 'submitted', 'acknowledged', 'assigned', 'in_progress', 'on_hold'])
            if user.role == 'facility_manager' and scope is not None:
                building_names = list(buildings.values_list('name', flat=True))
                maint_qs = maint_qs.filter(building__in=building_names) if building_names else maint_qs.none()
            stats['pending_maintenance'] = maint_qs.count()

        except ImportError as e:
            import logging
            logging.getLogger(__name__).error(f"ImportError in facility_manager_stats: {e}")
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error calculating facility manager stats: {e}")
    
    return Response(stats)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def resident_stats(request):
    """
    Resident Dashboard Statistics
    Returns stats for the logged-in resident
    """
    user = request.user
    
    stats = {
        'unit_info': {
            'unit_number': user.unit_number or '',
            'building_name': user.building_name or '',
        },
        'lease_info': {},
        'payment_info': {},
        'maintenance_requests': 0,
    }
    
    try:
        # Get resident's lease
        try:
            from properties.models import Lease
            lease = Lease.objects.filter(
                tenant=user,
                status='active'
            ).first()
            
            if lease:
                stats['lease_info'] = {
                    'start_date': lease.start_date.isoformat() if lease.start_date else None,
                    'end_date': lease.end_date.isoformat() if lease.end_date else None,
                    'monthly_rent': float(lease.monthly_rent) if lease.monthly_rent else 0,
                    'status': lease.status
                }
        except ImportError:
            pass
        
        # Get payment info
        try:
            from payments.models import Payment
            pending_payment = Payment.objects.filter(
                user=user,
                status='pending'
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            stats['payment_info'] = {
                'pending_amount': float(pending_payment),
                'next_due_date': None  # You can add logic for next due date
            }
        except ImportError:
            pass
        
        # Get maintenance requests
        try:
            from maintenance.models import MaintenanceRequest
            stats['maintenance_requests'] = MaintenanceRequest.objects.filter(
                requested_by=user
            ).count()
        except ImportError:
            pass
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error calculating resident stats: {e}")
    
    return Response(stats)