# properties/views.py
from rest_framework import viewsets, filters, permissions, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Avg, Q, Count
from django.db import transaction
from notifications.services import NotificationService
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from datetime import timedelta
import logging
import requests
from notifications.services import NotificationService
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import Building, Unit, Lease, PropertyDocument, Township, Block, Floor, PropertyCity, AreaZone, FacilityManagerAssignment
from .serializers import (
    BuildingSerializer, BuildingCreateSerializer,
    UnitSerializer, UnitCreateSerializer, UnitBulkUpdateSerializer,
    LeaseSerializer, LeaseCreateSerializer,
    PropertyDocumentSerializer, PropertyDocumentCreateSerializer,
    BuildingStatsSerializer, UnitAvailabilitySerializer,
    # Hierarchy serializers
    TownshipSerializer, TownshipCreateSerializer,
    BlockSerializer, BlockCreateSerializer,
    FloorSerializer, FloorCreateSerializer,
    FloorDetailSerializer, ApartmentSummarySerializer,
    PropertyCitySerializer, PropertyCityCreateSerializer,
    AreaZoneSerializer, AreaZoneCreateSerializer,
    FacilityManagerAssignmentSerializer,
)

logger = logging.getLogger(__name__)


def _is_admin(user):
    """Returns True for Master Admin and Super Admin (handles both underscore/no-underscore)."""
    if not (user and getattr(user, 'is_authenticated', False)):
        return False
    role = getattr(user, 'role', None)
    return role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin')


from accounts.fm_scope import (
    is_facility_manager as _is_facility_manager,
    get_manager_building_ids as _get_manager_building_ids,
    get_manager_block_ids as _get_manager_block_ids
)

# ======================================================
# BUILDINGS
# ======================================================

class BuildingViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'properties'
    queryset = Building.objects.prefetch_related('units').all()

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]

    filterset_fields = ['building_type', 'city', 'state', 'country', 'township']
    search_fields = [
        'name',
        'address',
        'address_line1',
        'address_line2',
        'address_line3',
        'landmark',
        'city',
        'state',
        'postal_code',
    ]
    ordering_fields = ['name', 'created_at', 'total_floors', 'total_units']
    ordering = ['name']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return BuildingCreateSerializer
        return BuildingSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if not _is_admin(self.request.user):
            qs = qs.filter(is_active=True).exclude(township__is_active=False)
        
        user = self.request.user
        is_fm = _is_facility_manager(user)
        
        if is_fm:
            building_ids = _get_manager_building_ids(user)
            if building_ids is not None:
                qs = qs.filter(id__in=building_ids).distinct()
            # If no assignments, FM sees nothing (correct behavior)

        # Optimize: select_related managed_by to avoid N+1 query on manager name
        qs = qs.select_related('managed_by')

        # Optimize: annotate block counts scoped by FM if they are an FM
        if is_fm:
            block_ids = _get_manager_block_ids(user)
            if block_ids is not None:
                qs = qs.annotate(
                    num_blocks_annotated=Count('block_set', filter=Q(block_set__id__in=block_ids), distinct=True)
                )
            else:
                qs = qs.annotate(
                    num_blocks_annotated=Count('block_set', distinct=True)
                )
        else:
            qs = qs.annotate(
                num_blocks_annotated=Count('block_set', distinct=True)
            )

        # Optimize: annotate unit counts to avoid querying for counts on each building
        qs = qs.annotate(
            total_units_count_annotated=Count('units', distinct=True),
            occupied_units_count_annotated=Count('units', filter=Q(units__status='occupied'), distinct=True),
            available_units_count_annotated=Count('units', filter=Q(units__status='available'), distinct=True)
        )

        return qs

    def destroy(self, request, *args, **kwargs):
        """
        Custom destroy with proper error handling and cascade deletion
        """
        try:
            instance = self.get_object()
            building_id = instance.id
            building_name = instance.name
            
            # Get counts for logging
            units_count = instance.units.count()
            
            logger.info(
                f"Attempting to delete building '{building_name}' (ID: {building_id}) "
                f"with {units_count} units by user {request.user.email}"
            )
            
            # Use transaction to ensure atomic deletion
            with transaction.atomic():
                # Delete the building (CASCADE will handle units, leases, documents)
                instance.delete()
            
            logger.info(f"Successfully deleted building '{building_name}' and all related data")
            
            return Response(
                {
                    'success': True,
                    'message': f'Building "{building_name}" and all related data deleted successfully',
                    'deleted_units': units_count
                },
                status=status.HTTP_200_OK
            )
            
        except Building.DoesNotExist:
            logger.error(f"Building not found: {kwargs.get('pk')}")
            return Response(
                {
                    'success': False,
                    'error': 'Building not found'
                },
                status=status.HTTP_404_NOT_FOUND
            )
            
        except Exception as e:
            logger.error(
                f"Error deleting building: {str(e)}", 
                exc_info=True,
                extra={'building_id': kwargs.get('pk'), 'user': request.user.email}
            )
            return Response(
                {
                    'success': False,
                    'error': 'Failed to delete building',
                    'detail': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def units(self, request, pk=None):
        building = self.get_object()
        units = building.units.all()

        status_filter = request.query_params.get('status')
        if status_filter:
            units = units.filter(status=status_filter)

        serializer = UnitSerializer(units, many=True)
        return Response(serializer.data)

    @method_decorator(cache_page(300))
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        building = self.get_object()
        units = building.units.all()

        stats = {
            'total_units': units.count(),
            'occupied_units': units.filter(status='occupied').count(),
            'available_units': units.filter(status='available').count(),
            'maintenance_units': units.filter(status='maintenance').count(),
            'reserved_units': units.filter(status='reserved').count(),
            'total_floors': building.total_floors,
            'active_leases': Lease.objects.filter(
                unit__building=building,
                status='active'
            ).count(),
            'total_monthly_revenue': units.filter(
                status='occupied'
            ).aggregate(total=Sum('monthly_rent'))['total'] or 0
        }

        if stats['total_units'] > 0:
            stats['occupancy_rate'] = round(
                (stats['occupied_units'] / stats['total_units']) * 100, 2
            )
        else:
            stats['occupancy_rate'] = 0

        return Response(stats)

    @method_decorator(cache_page(300))
    @action(detail=False, methods=['get'])
    def overview(self, request):
        buildings = Building.objects.all()

        unit_stats = Unit.objects.aggregate(
            total_units=Count('id'),
            occupied_units=Count('id', filter=Q(status='occupied')),
            available_units=Count('id', filter=Q(status='available')),
            maintenance_units=Count('id', filter=Q(status='maintenance')),
            total_monthly_revenue=Sum('monthly_rent', filter=Q(status='occupied'))
        )

        total_units = unit_stats['total_units'] or 0
        occupancy_rate = 0
        if total_units > 0:
            occupancy_rate = round(( (unit_stats['occupied_units'] or 0) / total_units) * 100, 2)

        stats = {
            'total_buildings': buildings.count(),
            'total_units': total_units,
            'occupied_units': unit_stats['occupied_units'] or 0,
            'available_units': unit_stats['available_units'] or 0,
            'maintenance_units': unit_stats['maintenance_units'] or 0,
            'occupancy_rate': occupancy_rate,
            'total_monthly_revenue': unit_stats['total_monthly_revenue'] or 0
        }

        serializer = BuildingStatsSerializer(stats)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def cities(self, request):
        """Return distinct cities from all buildings, for location filter."""
        cities = (
            self.get_queryset()
            .exclude(city='')
            .values_list('city', flat=True)
            .distinct()
            .order_by('city')
        )
        return Response(list(cities))

    @action(detail=False, methods=['get'], url_path='postal-lookup')
    def postal_lookup(self, request):
        """Resolve postal code to city/state/country via server-side proxy APIs."""
        postal_code = (request.query_params.get('postal_code') or '').strip()
        country = (request.query_params.get('country') or 'India').strip()

        if not postal_code:
            return Response(
                {'success': False, 'error': 'postal_code is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        def _is_india(country_name):
            return country_name.lower() in ['india', 'in']

        def _country_code(country_name):
            normalized = country_name.strip().lower()
            country_map = {
                'india': 'IN',
                'in': 'IN',
                'united states': 'US',
                'usa': 'US',
                'us': 'US',
                'united kingdom': 'GB',
                'uk': 'GB',
                'gb': 'GB',
                'canada': 'CA',
                'ca': 'CA',
                'australia': 'AU',
                'au': 'AU',
            }
            if normalized in country_map:
                return country_map[normalized]
            return normalized.upper()[:2] if normalized else ''

        def _lookup_india(postal):
            try:
                response = requests.get(
                    f'https://api.postalpincode.in/pincode/{postal}',
                    timeout=8,
                )
                response.raise_for_status()
                payload = response.json()
                result = payload[0] if isinstance(payload, list) and payload else None
                post_office = result.get('PostOffice', [None])[0] if result else None

                if result and result.get('Status') == 'Success' and post_office:
                    return {
                        'city': post_office.get('District') or post_office.get('Block') or '',
                        'state': post_office.get('State') or '',
                        'country': post_office.get('Country') or 'India',
                        'locality': post_office.get('Name') or '',
                    }
            except requests.RequestException:
                return None

            return None

        def _lookup_global(postal, country_name):
            code = _country_code(country_name)
            if not code or len(code) != 2:
                return None

            # 1. Try Nominatim (OpenStreetMap) first to get the correct County
            try:
                # Use a custom user agent as required by OpenStreetMap Nominatim usage policy
                headers = {'User-Agent': 'HOA-Connect-Hub/1.0 (contact: support@hoaconnecthub.com)'}
                url = f'https://nominatim.openstreetmap.org/search?postalcode={postal}&country={code}&format=json&addressdetails=1'
                response = requests.get(url, headers=headers, timeout=8)
                if response.status_code == 200:
                    payload = response.json()
                    if isinstance(payload, list) and payload:
                        address = payload[0].get('address', {})
                        city_val = (
                            address.get('city')
                            or address.get('town')
                            or address.get('village')
                            or address.get('hamlet')
                            or address.get('suburb')
                            or address.get('city_district')
                            or address.get('borough')
                            or address.get('neighbourhood')
                            or ''
                        )
                        return {
                            'city': city_val,
                            'state': address.get('state') or address.get('state_district') or '',
                            'country': address.get('country') or country_name,
                            'locality': city_val,
                            'district': address.get('county') or '',
                        }
            except Exception as e:
                logger.warning('Nominatim global lookup failed: %s. Falling back to Zippopotam.', str(e))

            # 2. Fallback to Zippopotam
            try:
                response = requests.get(
                    f'https://api.zippopotam.us/{code}/{postal}',
                    timeout=8,
                )

                if response.status_code == 404:
                    return None

                response.raise_for_status()
                payload = response.json()
                places = payload.get('places') if isinstance(payload, dict) else []
                place = places[0] if isinstance(places, list) and places else None

                if not place:
                    return None

                return {
                    'city': place.get('place name') or '',
                    'state': place.get('state') or place.get('state abbreviation') or '',
                    'country': payload.get('country') or country_name,
                    'locality': place.get('place name') or '',
                    'district': place.get('place name') or '',  # Fallback to city/place name
                }
            except requests.RequestException:
                return None

        try:
            address_data = None

            if _is_india(country) and postal_code.isdigit() and len(postal_code) == 6:
                address_data = _lookup_india(postal_code)
                if not address_data:
                    address_data = _lookup_global(postal_code, country)
            else:
                address_data = _lookup_global(postal_code, country)

            if not address_data:
                return Response(
                    {'success': False, 'error': 'Postal code not found.'},
                    status=status.HTTP_200_OK,
                )

            return Response({
                'success': True,
                'data': address_data,
            })

        except Exception as exc:
            logger.exception('Postal lookup error: %s', str(exc))
            return Response(
                {'success': False, 'error': 'Could not resolve postal code.'},
                status=status.HTTP_200_OK,
            )


# ======================================================
# UNITS
# ======================================================

class UnitViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'units'
    
    def get_queryset(self):
        from django.db.models import Prefetch
        from properties.models import Lease
        qs = Unit.objects.select_related('building', 'owner_user', 'floor_ref').prefetch_related(
            Prefetch('leases', queryset=Lease.objects.select_related('tenant').filter(status='active'), to_attr='active_leases_prefetched'),
            Prefetch('leases', queryset=Lease.objects.select_related('tenant'), to_attr='all_leases_prefetched')
        )
        if not _is_admin(self.request.user):
            qs = qs.filter(is_active=True, building__is_active=True)
            qs = qs.exclude(building__township__is_active=False)
        if _is_facility_manager(self.request.user):
            building_ids = _get_manager_building_ids(self.request.user)
            if building_ids is not None:
                qs = qs.filter(building_id__in=building_ids)
        return qs

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_fields = [
        'building',
        'block',
        'unit_type',
        'status',
        'floor',
        'bedrooms',
        'bathrooms',
    ]

    search_fields = [
        'unit_number',
        'building__name',
    ]

    ordering_fields = [
        'unit_number',
        'floor',
        'monthly_rent',
        'square_feet',
        'created_at',
    ]

    ordering = ['building', 'floor', 'unit_number']

    def get_permissions(self):
        """
        Facility managers can create and edit units inside their assigned scope even when
        their base role does not carry the global units permissions.
        Object-level scoping still applies via the queryset and FM scope checks.
        """
        if self.action in ['create', 'update', 'partial_update'] and _is_facility_manager(self.request.user):
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UnitCreateSerializer
        return UnitSerializer

    def create(self, request, *args, **kwargs):
        # Enforce Subscription Unit limits
        try:
            from pricing.utils import check_unit_limit
            allowed, limit_error = check_unit_limit()
            if not allowed:
                return Response({'error': limit_error}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.error(f"Subscription check failed: {str(e)}")
            # Fail open or closed depending on preference, currently continuing to not block if module not ready.

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        unit = serializer.save()
        return Response(UnitSerializer(unit).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """Delete a unit with safer error handling and clear client feedback."""
        if _is_facility_manager(request.user):
            return Response(
                {
                    'success': False,
                    'error': 'Facility manager cannot delete units.'
                },
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            unit = self.get_object()

            if unit.leases.filter(status='active').exists():
                return Response(
                    {
                        'success': False,
                        'error': 'Cannot delete unit with an active lease.',
                        'detail': 'Terminate or expire the active lease first, then delete the unit.'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            unit_number = unit.unit_number
            building_name = unit.building.name if unit.building else 'Unknown building'

            with transaction.atomic():
                unit.delete()

            return Response(
                {
                    'success': True,
                    'message': f'Unit "{unit_number}" deleted successfully from {building_name}.'
                },
                status=status.HTTP_200_OK
            )
        except Unit.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'error': 'Unit not found.'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(
                f"Error deleting unit: {str(e)}",
                exc_info=True,
                extra={'unit_id': kwargs.get('pk'), 'user': getattr(request.user, 'email', None)}
            )
            return Response(
                {
                    'success': False,
                    'error': 'Failed to delete unit.',
                    'detail': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def available(self, request):
        units = self.get_queryset().filter(status='available')

        building_id = request.query_params.get('building')
        if building_id:
            units = units.filter(building_id=building_id)

        unit_type = request.query_params.get('unit_type')
        if unit_type:
            units = units.filter(unit_type=unit_type)

        max_rent = request.query_params.get('max_rent')
        if max_rent:
            units = units.filter(monthly_rent__lte=max_rent)

        serializer = UnitSerializer(units, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def mark_occupied(self, request, pk=None):
        unit = self.get_object()
        unit.status = 'occupied'
        unit.is_occupied = True
        unit.save(update_fields=['status', 'is_occupied'])
        return Response(UnitSerializer(unit).data)

    @action(detail=True, methods=['post'])
    def mark_available(self, request, pk=None):
        unit = self.get_object()
        unit.status = 'available'
        unit.is_occupied = False
        unit.save(update_fields=['status', 'is_occupied'])
        return Response(UnitSerializer(unit).data)

    @action(detail=True, methods=['post'])
    def mark_maintenance(self, request, pk=None):
        unit = self.get_object()
        unit.status = 'maintenance'
        unit.save(update_fields=['status'])
        return Response(UnitSerializer(unit).data)

    @action(detail=False, methods=['post'])
    def bulk_update(self, request):
        serializer = UnitBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        unit_ids = serializer.validated_data['unit_ids']
        update_data = {
            k: v for k, v in serializer.validated_data.items()
            if k != 'unit_ids'
        }

        updated_count = 0
        if update_data:
            updated_count = Unit.objects.filter(
                id__in=unit_ids
            ).update(**update_data)

        return Response({
            'updated_count': updated_count
        })

    @action(detail=False, methods=['get'])
    def availability_by_building(self, request):
        buildings = Building.objects.all()
        data = []

        for building in buildings:
            units = building.units.all()
            data.append({
                'building_id': building.id,
                'building_name': building.name,
                'total_units': units.count(),
                'available_units': units.filter(status='available').count(),
                'occupied_units': units.filter(status='occupied').count(),
                'maintenance_units': units.filter(status='maintenance').count(),
                'reserved_units': units.filter(status='reserved').count(),
            })

        serializer = UnitAvailabilitySerializer(data, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def financials(self, request, pk=None):
        unit = self.get_object()
        from payments.models import Invoice, Payment
        from django.db.models import Sum
        
        invoices = Invoice.objects.filter(
            unit_number=unit.unit_number,
            building=unit.building.name if unit.building else ''
        )
        
        total_due = invoices.aggregate(total=Sum('amount_due'))['total'] or 0
        total_paid = invoices.aggregate(total=Sum('amount_paid'))['total'] or 0
        
        recent_payments = Payment.objects.filter(
            invoice__in=invoices,
            status='completed'
        ).order_by('-completed_at')[:4]
        
        payments_data = []
        for p in recent_payments:
            payments_data.append({
                'id': str(p.id),
                'payment_number': p.payment_number,
                'amount': float(p.amount),
                'completed_at': p.completed_at,
                'payment_method': p.get_payment_method_display()
            })
            
        return Response({
            'total_due': float(total_due),
            'total_paid': float(total_paid),
            'recent_payments': payments_data
        })


# ======================================================
# LEASES
# ======================================================

class LeaseViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'properties'
    
    def get_permissions(self):
        """Allow facility managers to create/update leases within their scope."""
        if self.action in ['create', 'update', 'partial_update'] and _is_facility_manager(self.request.user):
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    queryset = Lease.objects.select_related(
        'unit', 'tenant', 'unit__building'
    ).all()

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]

    filterset_fields = ['unit', 'tenant', 'status', 'unit__building']
    search_fields = [
        'tenant__first_name',
        'tenant__last_name',
        'tenant__email',
        'unit__unit_number'
    ]
    ordering_fields = ['start_date', 'end_date', 'monthly_rent', 'created_at']
    ordering = ['-start_date']

    def get_queryset(self):
        qs = super().get_queryset()
        if not _is_admin(self.request.user):
            qs = qs.filter(
                unit__is_active=True,
                unit__building__is_active=True,
                unit__building__township__is_active=True
            ).distinct()
        if _is_facility_manager(self.request.user):
            building_ids = _get_manager_building_ids(self.request.user)
            if building_ids:
                qs = qs.filter(unit__building_id__in=building_ids).distinct()
        return qs

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return LeaseCreateSerializer
        return LeaseSerializer

    def perform_create(self, serializer):
        lease = serializer.save(created_by=self.request.user)

        unit = lease.unit
        unit.status = 'occupied'
        unit.is_occupied = True
        unit.unit_type = 'tenant_occupied'
        unit.current_resident = lease.tenant.get_full_name() or lease.tenant.email
        unit.save(update_fields=['status', 'is_occupied', 'unit_type', 'current_resident'])

        tenant = lease.tenant
        tenant.unit_number = unit.unit_number
        tenant.building_name = unit.building.name
        tenant.save(update_fields=['unit_number', 'building_name'])

        # Send Notification
        NotificationService.send_lease_notification(lease, 'agreement_created')

        # Notify Master Admins if created by FM
        user = self.request.user
        if getattr(user, 'role', None) == 'facility_manager':
            from accounts.models import User
            master_admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
            for admin in master_admins:
                NotificationService.send(
                    user=admin,
                    title='FM Activity: Lease Created',
                    message=f'Facility Manager {user.get_full_name()} created a new lease for unit {unit.unit_number}.',
                    notification_type='system',
                    priority='low',
                    send_email=True,
                    action_url='/admin/properties',
                )

    def destroy(self, request, *args, **kwargs):
        lease = self.get_object()
        unit = lease.unit
        tenant = lease.tenant

        response = super().destroy(request, *args, **kwargs)

        if unit:
            unit.status = 'available'
            unit.is_occupied = False
            unit.unit_type = 'vacant'
            unit.current_resident = ''
            unit.save(update_fields=['status', 'is_occupied', 'unit_type', 'current_resident'])

        if tenant and tenant.unit_number == unit.unit_number and tenant.building_name == unit.building.name:
            tenant.unit_number = ''
            tenant.building_name = ''
            tenant.save(update_fields=['unit_number', 'building_name'])

        return response

    @action(detail=True, methods=['post'])
    def terminate(self, request, pk=None):
        lease = self.get_object()
        lease.status = 'terminated'
        lease.save(update_fields=['status'])

        unit = lease.unit
        unit.status = 'available'
        unit.is_occupied = False
        unit.unit_type = 'vacant'
        unit.current_resident = ''
        unit.save(update_fields=['status', 'is_occupied', 'unit_type', 'current_resident'])

        tenant = lease.tenant
        if tenant.unit_number == unit.unit_number and tenant.building_name == unit.building.name:
            tenant.unit_number = ''
            tenant.building_name = ''
            tenant.save(update_fields=['unit_number', 'building_name'])

        # Notify Master Admins if terminated by FM
        user = self.request.user
        if getattr(user, 'role', None) == 'facility_manager':
            from accounts.models import User
            master_admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
            for admin in master_admins:
                NotificationService.send(
                    user=admin,
                    title='FM Activity: Lease Terminated',
                    message=f'Facility Manager {user.get_full_name()} terminated the lease for unit {unit.unit_number}.',
                    notification_type='system',
                    priority='low',
                    send_email=True,
                    action_url='/admin/properties',
                )

        # Send Notification
        NotificationService.send_lease_notification(lease, 'status_update')

        return Response(LeaseSerializer(lease).data)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        lease = self.get_object()

        overlapping = Lease.objects.filter(
            unit=lease.unit,
            status='active'
        ).exclude(id=lease.id)

        if overlapping.exists():
            return Response(
                {'error': 'Unit already has an active lease'},
                status=status.HTTP_400_BAD_REQUEST
            )

        lease.status = 'active'
        lease.save(update_fields=['status'])

        unit = lease.unit
        unit.status = 'occupied'
        unit.is_occupied = True
        unit.unit_type = 'tenant_occupied'
        unit.current_resident = lease.tenant.get_full_name() or lease.tenant.email
        unit.save(update_fields=['status', 'is_occupied', 'unit_type', 'current_resident'])

        tenant = lease.tenant
        tenant.unit_number = unit.unit_number
        tenant.building_name = unit.building.name
        tenant.save(update_fields=['unit_number', 'building_name'])

        # Send Notification
        NotificationService.send_lease_notification(lease, 'status_update')

        return Response(LeaseSerializer(lease).data)

    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        days = int(request.query_params.get('days', 30))
        today = timezone.now().date()
        end_date = today + timedelta(days=days)

        leases = self.get_queryset().filter(
            status='active',
            end_date__gte=today,
            end_date__lte=end_date
        ).order_by('end_date')

        serializer = LeaseSerializer(leases, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def active(self, request):
        leases = self.get_queryset().filter(status='active')
        serializer = LeaseSerializer(leases, many=True)
        return Response(serializer.data)


# ======================================================
# PROPERTY DOCUMENTS
# ======================================================

class PropertyDocumentViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'properties'

    def get_permissions(self):
        """Allow facility managers to upload/update documents within their scope."""
        if self.action in ['create', 'update', 'partial_update'] and _is_facility_manager(self.request.user):
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    queryset = PropertyDocument.objects.select_related(
        'building', 'unit', 'lease', 'uploaded_by'
    ).all()

    def get_queryset(self):
        user = self.request.user
        qs = self.queryset
        
        if not user or not user.is_authenticated:
            return qs.none()
            
        if _is_admin(user):
            return qs

        # Non-admins should not see documents linked to deactivated hierarchy elements
        qs = qs.filter(
            Q(unit__isnull=True) | Q(unit__is_active=True, unit__building__is_active=True, unit__building__township__is_active=True),
            Q(building__isnull=True) | Q(building__is_active=True, building__township__is_active=True)
        )

        if hasattr(user, 'role') and user.role in ['property_staff']:
            return qs

        if _is_facility_manager(user):
            building_ids = _get_manager_building_ids(user)
            if not building_ids:
                return qs.none()
            return qs.filter(
                Q(building_id__in=building_ids) |
                Q(unit__building_id__in=building_ids) |
                Q(lease__unit__building_id__in=building_ids) |
                Q(uploaded_by=user)
            ).distinct()
            
        return qs.filter(
            Q(lease__tenant=user) | 
            Q(unit__leases__tenant=user, unit__leases__status='active') |
            Q(building__units__leases__tenant=user, building__units__leases__status='active')
        ).distinct()

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter
    ]

    filterset_fields = ['building', 'unit', 'lease', 'document_type']
    search_fields = ['title', 'description']
    ordering_fields = ['uploaded_at', 'title']
    ordering = ['-uploaded_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PropertyDocumentCreateSerializer
        return PropertyDocumentSerializer

    def perform_create(self, serializer):
        user = self.request.user
        
        # For facility managers, validate that the document is within their scope
        if _is_facility_manager(user):
            building_ids = _get_manager_building_ids(user)
            building = serializer.validated_data.get('building')
            unit = serializer.validated_data.get('unit')
            building_id = str(getattr(building, 'pk', building) or '')
            unit_id = getattr(unit, 'pk', unit)
            has_access = False

            if building_id and building_ids and building_id in [str(b) for b in building_ids]:
                has_access = True

            if not has_access and unit_id and building_ids:
                try:
                    unit_obj = Unit.objects.filter(
                        id=unit_id, building_id__in=building_ids
                    ).first()
                    if unit_obj:
                        has_access = True
                        if not building_id:
                            serializer.validated_data['building'] = unit_obj.building
                except (Unit.DoesNotExist, TypeError, ValueError) as e:
                    logger.error(f"Error checking FM access for unit {unit_id}: {e}")

            if not has_access:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('You cannot create documents for this building or unit.')
        
        try:
            serializer.save(uploaded_by=user)
        except Exception as e:
            logger.error(f"Error saving document: {e}", exc_info=True)
            raise


    @action(detail=False, methods=['get'])
    def by_building(self, request):
        building_id = request.query_params.get('building_id')
        if not building_id:
            return Response(
                {'error': 'building_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        documents = self.get_queryset().filter(building_id=building_id)
        serializer = PropertyDocumentSerializer(documents, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_unit(self, request):
        unit_id = request.query_params.get('unit_id')
        if not unit_id:
            return Response(
                {'error': 'unit_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        documents = self.get_queryset().filter(unit_id=unit_id)
        serializer = PropertyDocumentSerializer(documents, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_lease(self, request):
        lease_id = request.query_params.get('lease_id')
        if not lease_id:
            return Response(
                {'error': 'lease_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        documents = self.get_queryset().filter(lease_id=lease_id)
        serializer = PropertyDocumentSerializer(documents, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        from django.http import FileResponse
        document = self.get_object()
        
        if not document.file:
            return Response(
                {'error': 'No file associated with this document'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Log download activity and send notification
        try:
            from notifications.services import NotificationService
            role = getattr(request.user, 'role', 'tenant')
            action_url = '/owner/documents' if role == 'owner' else '/residents/documents'
            NotificationService.send(
                user=request.user,
                title="Document Downloaded",
                message=f"You successfully downloaded the document: {document.title or document.name or 'Document'}",
                notification_type='document',
                priority='low',
                related_object_type='document',
                related_object_id=document.id,
                action_url=action_url,
            )
        except Exception as e:
            logger.error(f"Failed to create download notification: {e}")
        
        try:
            return FileResponse(
                document.file.open('rb'),
                as_attachment=True,
                filename=document.file.name.split('/')[-1]
            )
        except Exception as e:
            return Response(
                {'error': 'Physical file not found on server.'},
                status=status.HTTP_404_NOT_FOUND
            )


# ======================================================
# DASHBOARD STATS
# ======================================================

@cache_page(300)
@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def property_dashboard_stats(request):
    building_ids = _get_manager_building_ids(request.user)

    buildings_qs = Building.objects.all()
    units_qs = Unit.objects.all()

    if _is_facility_manager(request.user):
        if not building_ids:
            buildings_qs = buildings_qs.none()
            units_qs = units_qs.none()
        else:
            buildings_qs = buildings_qs.filter(id__in=building_ids).distinct()
            units_qs = units_qs.filter(building_id__in=building_ids).distinct()

    total_buildings = buildings_qs.count()
    total_units = units_qs.count()
    occupied_units = units_qs.filter(status='occupied').count()
    available_units = units_qs.filter(status='available').count()
    maintenance_units = units_qs.filter(status='maintenance').count()

    active_leases = Lease.objects.filter(status='active')
    expiring_leases_30 = Lease.objects.filter(
        status='active',
        end_date__lte=timezone.now().date() + timedelta(days=30),
        end_date__gte=timezone.now().date()
    )

    if _is_facility_manager(request.user):
        if not building_ids:
            active_leases = active_leases.none()
            expiring_leases_30 = expiring_leases_30.none()
        else:
            active_leases = active_leases.filter(unit__building_id__in=building_ids).distinct()
            expiring_leases_30 = expiring_leases_30.filter(unit__building_id__in=building_ids).distinct()

    active_leases = active_leases.count()
    expiring_leases_30 = expiring_leases_30.count()

    occupancy_rate = 0
    if total_units > 0:
        occupancy_rate = round((occupied_units / total_units) * 100, 2)

    total_monthly_revenue = units_qs.filter(
        status='occupied'
    ).aggregate(total=Sum('monthly_rent'))['total'] or 0

    avg_rent = units_qs.filter(
        status='occupied'
    ).aggregate(avg=Avg('monthly_rent'))['avg'] or 0

    return Response({
        'total_buildings': total_buildings,
        'total_units': total_units,
        'occupied_units': occupied_units,
        'available_units': available_units,
        'maintenance_units': maintenance_units,
        'occupancy_rate': occupancy_rate,
        'active_leases': active_leases,
        'expiring_leases_30_days': expiring_leases_30,
        'total_monthly_revenue': float(total_monthly_revenue),
        'average_rent': float(avg_rent),
    })


# ======================================================
# HIERARCHY: CITY
# ======================================================

class PropertyCityViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'properties'
    queryset = PropertyCity.objects.prefetch_related('area_zones', 'townships').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'state']
    search_fields = ['name', 'state']
    ordering_fields = ['name', 'state', 'created_at']
    ordering = ['name']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return PropertyCityCreateSerializer
        return PropertyCitySerializer


# ======================================================
# HIERARCHY: AREA / ZONE
# ======================================================

class AreaZoneViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'properties'
    queryset = AreaZone.objects.select_related('city_ref').prefetch_related('townships').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'city_ref']
    search_fields = ['name', 'city_ref__name', 'city_ref__state']
    ordering_fields = ['name', 'created_at']
    ordering = ['city_ref__name', 'name']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return AreaZoneCreateSerializer
        return AreaZoneSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        city_id = self.request.query_params.get('city_ref')
        if city_id:
            qs = qs.filter(city_ref_id=city_id)
        return qs


# ======================================================
# HIERARCHY: TOWNSHIP
# ======================================================

class TownshipViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    CRUD for townships. Supports:
      GET /townships/                   — list all
      GET /townships/<id>/              — detail
      GET /townships/<id>/buildings/    — buildings in this township
    """
    module = 'properties'
    queryset = Township.objects.select_related('city_ref', 'area_zone').prefetch_related('buildings').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['city_ref', 'area_zone', 'managed_by']
    search_fields = ['name', 'city', 'state', 'city_ref__name', 'area_zone__name']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return TownshipCreateSerializer
        return TownshipSerializer



    def get_queryset(self):
        qs = super().get_queryset()
        if not _is_admin(self.request.user):
            qs = qs.filter(is_active=True)
        if _is_facility_manager(self.request.user):
            from accounts.fm_scope import get_fm_scope
            scope = get_fm_scope(self.request.user)
            if not scope or (not scope['township_ids'] and not scope['building_ids']):
                return qs.none()
            q = Q()
            if scope['township_ids']:
                q |= Q(id__in=scope['township_ids'])
            if scope['building_ids']:
                q |= Q(buildings__id__in=scope['building_ids'])
            qs = qs.filter(q).distinct()
        return qs

    def create(self, request, *args, **kwargs):
        if _is_facility_manager(request.user):
            return Response(
                {'error': 'Facility manager cannot create colony/township.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if _is_facility_manager(request.user):
            return Response(
                {'error': 'Facility manager cannot delete colony/township.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], url_path='toggle-activation')
    def toggle_activation(self, request, pk=None):
        """Toggle the is_active status of a Township."""
        if _is_facility_manager(request.user) or request.user.role not in ['master_admin', 'super_admin']:
            return Response(
                {'error': 'Only Master/Super Admins can toggle township activation.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        
        township = self.get_object()
        
        # Toggle boolean
        township.is_active = not township.is_active
        township.save(update_fields=['is_active'])
        
        # Cascade is_active to all descendants (buildings, blocks, floors, units, leases, user roles)
        from .services import toggle_township_cascade
        toggle_township_cascade(township, township.is_active, request.user)
        
        state_label = 'activated' if township.is_active else 'deactivated'

        # Send in-app notification to Master Admins
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
            for admin in admins:
                NotificationService.send(
                    user=admin,
                    title=f"Colony {state_label.capitalize()}",
                    message=f"The colony '{township.name}' has been {state_label}.",
                    notification_type='system',
                    priority='medium',
                    send_email=True,
                    action_url='/admin/properties',
                )
        except Exception as e:
            logger.error(f"Failed to send colony toggle notification: {e}")

        return Response({
            'success': True,
            'message': (
                f"Township {state_label} successfully. "
                f"All buildings, blocks, floors, units and leases have been {state_label}."
            ),
            'is_active': township.is_active
        })

    @action(detail=True, methods=['get'])
    def buildings(self, request, pk=None):
        """Return buildings belonging to this township."""
        township = self.get_object()
        buildings = township.buildings.prefetch_related('units').all()
        if _is_facility_manager(request.user):
            building_ids = _get_manager_building_ids(request.user)
            buildings = buildings.none() if not building_ids else buildings.filter(id__in=building_ids).distinct()
        serializer = BuildingSerializer(buildings, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def blocks(self, request, pk=None):
        """Return blocks belonging to buildings in this township."""
        township = self.get_object()
        blocks = Block.objects.select_related('building').prefetch_related('floors').filter(building__township=township)
        if _is_facility_manager(request.user):
            block_ids = _get_manager_block_ids(request.user)
            if not block_ids:
                blocks = blocks.none()
            else:
                blocks = blocks.filter(id__in=block_ids)
        serializer = BlockSerializer(blocks, many=True)
        return Response(serializer.data)


# ======================================================
# HIERARCHY: BLOCK
# ======================================================

class BlockViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    CRUD for blocks. Supports:
      GET /blocks/?building=<uuid>      — blocks for a building
      GET /blocks/<id>/floors/          — floors in this block
    """
    module = 'properties'
    queryset = Block.objects.select_related('building').prefetch_related('floors').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['building']
    search_fields = ['name', 'building__name']
    ordering_fields = ['name', 'created_at']
    ordering = ['building', 'name']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return BlockCreateSerializer
        return BlockSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if not _is_admin(self.request.user):
            qs = qs.filter(is_active=True, building__is_active=True)
            qs = qs.exclude(building__township__is_active=False)
        if _is_facility_manager(self.request.user):
            # Blocks accessible: directly assigned blocks OR all blocks in assigned buildings
            block_ids = _get_manager_block_ids(self.request.user)
            if not block_ids:
                return qs.none()
            qs = qs.filter(id__in=block_ids).distinct()
        building_id = self.request.query_params.get('building')
        if building_id:
            qs = qs.filter(building_id=building_id)
        return qs

    def perform_create(self, serializer):
        """
        Auto-generate Floor records after creating a block manually from the UI.
        Without this, total_floors is just a number — no actual Floor rows exist,
        so the document hierarchy floor dropdown shows nothing.
        """
        block = serializer.save()
        total_floors = block.total_floors or 0

        if total_floors > 0:
            floors_to_create = [
                Floor(
                    block=block,
                    floor_number=i,
                    label=f'Floor {i}',
                )
                for i in range(1, total_floors + 1)
            ]
            Floor.objects.bulk_create(floors_to_create, ignore_conflicts=True)
            logger.info(
                f"Auto-created {total_floors} floor(s) for block '{block.name}' "
                f"in building '{block.building.name}'"
            )

    @action(detail=True, methods=['get'])
    def floors(self, request, pk=None):
        """Return floors belonging to this block."""
        block = self.get_object()
        floors = block.floors.prefetch_related(
            'apartments__building',
            'apartments__leases__tenant'
        ).all()
        serializer = FloorSerializer(floors, many=True)
        return Response(serializer.data)


# ======================================================
# HIERARCHY: FLOOR
# ======================================================

class FloorViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    CRUD for floors. Supports:
      GET /floors/?block=<uuid>         — floors for a block
      GET /floors/<id>/                 — detail with apartments
      GET /floors/<id>/apartments/      — apartments on this floor
    """
    module = 'properties'
    queryset = Floor.objects.select_related('block', 'block__building').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['block']
    search_fields = ['label', 'block__name', 'block__building__name']
    ordering_fields = ['floor_number', 'created_at']
    ordering = ['block', 'floor_number']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return FloorCreateSerializer
        if self.action == 'retrieve':
            return FloorDetailSerializer
        return FloorSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if not _is_admin(self.request.user):
            qs = qs.filter(is_active=True, block__is_active=True, block__building__is_active=True)
            qs = qs.exclude(block__building__township__is_active=False)
        if _is_facility_manager(self.request.user):
            block_ids = _get_manager_block_ids(self.request.user)
            if not block_ids:
                return qs.none()
            qs = qs.filter(block_id__in=block_ids).distinct()
        block_id = self.request.query_params.get('block')
        if block_id:
            qs = qs.filter(block_id=block_id)
        return qs

    def perform_create(self, serializer):
        floor = serializer.save()
        # Validate FM scope on write
        if _is_facility_manager(self.request.user):
            from accounts.fm_scope import is_block_accessible
            if not is_block_accessible(self.request.user, floor.block_id):
                floor.delete()
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('You do not have access to this block.')

    @action(detail=True, methods=['get'])
    def apartments(self, request, pk=None):
        """Return apartments (units) on this floor with full tenant/owner detail."""
        floor = self.get_object()
        units = floor.apartments.select_related('building').prefetch_related('leases__tenant')

        stats = {
            'floor_number': floor.floor_number,
            'label': floor.label or f'Floor {floor.floor_number}',
            'total_apartments': units.count(),
            'occupied': units.filter(status='occupied').count(),
            'available': units.filter(status='available').count(),
            'maintenance': units.filter(status='maintenance').count(),
            'apartments': ApartmentSummarySerializer(units, many=True).data,
        }
        return Response(stats)


# ======================================================
# HIERARCHY: APARTMENT (Unit filtered by floor_ref)
# ======================================================

class ApartmentViewSet(ModulePermissionMixin, viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of apartments linked to the hierarchy.
      GET /apartments/?floor=<uuid>     — apartments on a specific floor
      GET /apartments/<id>/             — full apartment detail
    """
    module = 'properties'
    queryset = Unit.objects.select_related(
        'building', 'floor_ref', 'floor_ref__block', 'floor_ref__block__building'
    ).prefetch_related('leases__tenant').filter(floor_ref__isnull=False)

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['floor_ref', 'status', 'unit_type']
    search_fields = ['unit_number', 'building__name']
    serializer_class = ApartmentSummarySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if not _is_admin(self.request.user):
            qs = qs.filter(is_active=True, building__is_active=True, floor_ref__is_active=True, floor_ref__block__is_active=True, floor_ref__block__building__is_active=True)
            qs = qs.exclude(building__township__is_active=False)
        if _is_facility_manager(self.request.user):
            building_ids = _get_manager_building_ids(self.request.user)
            if not building_ids:
                return qs.none()
            qs = qs.filter(building_id__in=building_ids).distinct()
        floor_id = self.request.query_params.get('floor')
        if floor_id:
            qs = qs.filter(floor_ref_id=floor_id)
        return qs


# ======================================================
# FACILITY MANAGER ASSIGNMENTS
# ======================================================

class FacilityManagerAssignmentViewSet(viewsets.ModelViewSet):
    """
    Manage Facility Manager property assignments.

    - GET  /fm-assignments/                     list assignments
    - POST /fm-assignments/                     create assignment
    - GET  /fm-assignments/<id>/                retrieve
    - PATCH/PUT /fm-assignments/<id>/           update
    - DELETE /fm-assignments/<id>/              revoke

    Access rules:
      master_admin / super_admin  → full CRUD on all assignments
      facility_manager            → read-only on their own assignments
    """
    serializer_class = FacilityManagerAssignmentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['facility_manager', 'scope_type', 'is_active', 'building', 'block', 'township']
    search_fields = ['notes', 'facility_manager__first_name', 'facility_manager__last_name', 'facility_manager__email']
    ordering_fields = ['assigned_at']
    ordering = ['-assigned_at']

    def get_queryset(self):
        user = self.request.user
        qs = FacilityManagerAssignment.objects.select_related(
            'facility_manager', 'assigned_by',
            'township', 'building', 'block__building',
        )
        if user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
            return qs.all()
        if user.role == 'facility_manager':
            return qs.filter(facility_manager=user)
        return qs.none()

    def get_permissions(self):
        from accounts.permissions import IsSuperAdminOrAbove
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [permissions.IsAuthenticated(), IsSuperAdminOrAbove()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(assigned_by=self.request.user)

    @action(detail=False, methods=['get'], url_path='my-scope')
    def my_scope(self, request):
        """
        Returns the effective property scope for the authenticated Facility Manager.
        Useful for the UI to know which townships/buildings/blocks are accessible.
        """
        if request.user.role not in ('facility_manager',):
            return Response(
                {'detail': 'Only available to facility managers.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        from accounts.fm_scope import get_fm_scope
        scope = get_fm_scope(request.user)
        return Response({
            'township_ids': list(scope['township_ids']) if scope else [],
            'building_ids': list(scope['building_ids']) if scope else [],
            'block_ids': list(scope['block_ids']) if scope else [],
        })
