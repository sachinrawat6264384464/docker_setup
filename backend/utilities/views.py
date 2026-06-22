# utilities/views.py
from rest_framework import viewsets, filters, permissions, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, Sum
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from datetime import timedelta
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import (
    UtilityType, UtilityBill, UtilityMeterReading,
    UtilityProvider, BuildingUtilityConnection,
    InsuranceProvider, BuildingInsurance
)
from .serializers import (
    UtilityTypeSerializer, UtilityTypeCreateSerializer,
    UtilityBillSerializer, UtilityBillCreateSerializer,
    UtilityMeterReadingSerializer, UtilityMeterReadingCreateSerializer,
    UtilityProviderSerializer, UtilityProviderCreateSerializer,
    BuildingUtilityConnectionSerializer, BuildingUtilityConnectionCreateSerializer,
    UtilityConsumptionReportSerializer, UtilityStatsSerializer,
    InsuranceProviderSerializer, InsuranceProviderCreateSerializer,
    BuildingInsuranceSerializer, BuildingInsuranceCreateSerializer
)

class UtilityTypeViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'utilities'
    queryset = UtilityType.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'category', 'base_rate', 'created_at']
    ordering = ['category', 'name']
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UtilityTypeCreateSerializer
        return UtilityTypeSerializer
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        active_types = self.queryset.filter(is_active=True)
        serializer = self.get_serializer(active_types, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def bills(self, request, pk=None):
        utility_type = self.get_object()
        bills = utility_type.bills.all()
        
        status_filter = request.query_params.get('status', None)
        if status_filter:
            bills = bills.filter(status=status_filter)
        
        serializer = UtilityBillSerializer(bills, many=True)
        return Response(serializer.data)

class UtilityBillViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'utilities'
    queryset = UtilityBill.objects.select_related('utility_type', 'unit', 'tenant', 'unit__building').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['utility_type', 'unit', 'tenant', 'status', 'unit__building']
    search_fields = ['bill_number', 'tenant__first_name', 'tenant__last_name', 'unit__unit_number']
    ordering_fields = ['billing_period_start', 'due_date', 'total_amount', 'created_at']
    ordering = ['-billing_period_start']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # If not staff or admin, only show bills for this resident
        if user and user.is_authenticated and not (user.is_staff or user.role in ['master_admin', 'masteradmin', 'facility_manager']):
            queryset = queryset.filter(tenant=user)
        return queryset
        
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UtilityBillCreateSerializer
        return UtilityBillSerializer
    
    def perform_create(self, serializer):
        serializer.save(generated_by=self.request.user)
    
    @action(detail=False, methods=['get'])
    def my(self, request):
        """Get bills for the current user's active lease(s)"""
        user = request.user
        bills = self.get_queryset().filter(tenant=user)
        
        status_filter = request.query_params.get('status')
        if status_filter:
            bills = bills.filter(status=status_filter)
            
        serializer = self.get_serializer(bills, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        bill = self.get_object()
        
        payment_date = request.data.get('payment_date', timezone.now().date())
        payment_reference = request.data.get('payment_reference', '')
        
        bill.status = 'paid'
        bill.payment_date = payment_date
        bill.payment_reference = payment_reference
        bill.save()
        
        return Response({
            'message': 'Bill marked as paid',
            'bill': UtilityBillSerializer(bill).data
        })
    
    @action(detail=True, methods=['post'])
    def mark_overdue(self, request, pk=None):
        bill = self.get_object()
        bill.status = 'overdue'
        bill.save()
        
        return Response({
            'message': 'Bill marked as overdue',
            'bill': UtilityBillSerializer(bill).data
        })
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        bill = self.get_object()
        bill.status = 'cancelled'
        bill.save()
        
        return Response({
            'message': 'Bill cancelled',
            'bill': UtilityBillSerializer(bill).data
        })
    
    @action(detail=False, methods=['get'])
    def pending(self, request):
        pending_bills = self.queryset.filter(status='pending')
        serializer = self.get_serializer(pending_bills, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def overdue(self, request):
        overdue_bills = self.queryset.filter(status='overdue')
        serializer = self.get_serializer(overdue_bills, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def due_soon(self, request):
        days = int(request.query_params.get('days', 7))
        today = timezone.now().date()
        due_date = today + timedelta(days=days)
        
        due_soon_bills = self.queryset.filter(
            status='pending',
            due_date__gte=today,
            due_date__lte=due_date
        ).order_by('due_date')
        
        serializer = self.get_serializer(due_soon_bills, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_tenant(self, request):
        tenant_id = request.query_params.get('tenant_id')
        if not tenant_id:
            return Response({'error': 'tenant_id parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        
        bills = self.queryset.filter(tenant_id=tenant_id)
        serializer = self.get_serializer(bills, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_unit(self, request):
        unit_id = request.query_params.get('unit_id')
        if not unit_id:
            return Response({'error': 'unit_id parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        
        bills = self.queryset.filter(unit_id=unit_id)
        serializer = self.get_serializer(bills, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def generate_bills(self, request):
        from properties.models import Unit
        
        utility_type_id = request.data.get('utility_type_id')
        building_id = request.data.get('building_id')
        billing_period_start = request.data.get('billing_period_start')
        billing_period_end = request.data.get('billing_period_end')
        due_date = request.data.get('due_date')
        
        if not all([utility_type_id, billing_period_start, billing_period_end, due_date]):
            return Response(
                {'error': 'utility_type_id, billing_period_start, billing_period_end, and due_date are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            utility_type = UtilityType.objects.get(id=utility_type_id)
        except UtilityType.DoesNotExist:
            return Response({'error': 'Utility type not found'}, status=status.HTTP_404_NOT_FOUND)
        
        units = Unit.objects.filter(status='occupied')
        if building_id:
            units = units.filter(building_id=building_id)
        
        generated_count = 0
        errors = []
        
        for unit in units:
            active_lease = unit.leases.filter(status='active').first()
            if not active_lease:
                continue
            
            existing = UtilityBill.objects.filter(
                utility_type=utility_type,
                unit=unit,
                billing_period_start=billing_period_start,
                billing_period_end=billing_period_end
            ).exists()
            
            if existing:
                continue
            
            try:
                latest_reading = UtilityMeterReading.objects.filter(
                    utility_type=utility_type,
                    unit=unit
                ).order_by('-reading_date').first()
                
                current_reading = latest_reading.reading_value if latest_reading else 0
                
                previous_bill = UtilityBill.objects.filter(
                    utility_type=utility_type,
                    unit=unit
                ).order_by('-billing_period_end').first()
                
                previous_reading = previous_bill.current_reading if previous_bill else 0
                
                bill = UtilityBill.objects.create(
                    utility_type=utility_type,
                    unit=unit,
                    tenant=active_lease.tenant,
                    billing_period_start=billing_period_start,
                    billing_period_end=billing_period_end,
                    previous_reading=previous_reading,
                    current_reading=current_reading,
                    rate_per_unit=utility_type.base_rate,
                    due_date=due_date,
                    generated_by=request.user
                )
                generated_count += 1
            except Exception as e:
                errors.append({
                    'unit': str(unit.id),
                    'error': str(e)
                })
        
        return Response({
            'message': f'{generated_count} bills generated successfully',
            'generated_count': generated_count,
            'errors': errors
        })

class UtilityMeterReadingViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'utilities'
    queryset = UtilityMeterReading.objects.select_related('utility_type', 'unit', 'unit__building', 'recorded_by').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['utility_type', 'unit', 'reading_type', 'unit__building']
    search_fields = ['meter_number', 'unit__unit_number']
    ordering_fields = ['reading_date', 'reading_value', 'created_at']
    ordering = ['-reading_date']
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UtilityMeterReadingCreateSerializer
        return UtilityMeterReadingSerializer
    
    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)
    
    @action(detail=False, methods=['get'])
    def by_unit(self, request):
        unit_id = request.query_params.get('unit_id')
        if not unit_id:
            return Response({'error': 'unit_id parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        
        readings = self.queryset.filter(unit_id=unit_id)
        serializer = self.get_serializer(readings, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def latest(self, request):
        utility_type_id = request.query_params.get('utility_type_id')
        unit_id = request.query_params.get('unit_id')
        
        if not all([utility_type_id, unit_id]):
            return Response(
                {'error': 'utility_type_id and unit_id parameters required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        latest_reading = self.queryset.filter(
            utility_type_id=utility_type_id,
            unit_id=unit_id
        ).order_by('-reading_date').first()
        
        if not latest_reading:
            return Response({'error': 'No readings found'}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = self.get_serializer(latest_reading)
        return Response(serializer.data)

class UtilityProviderViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'utilities'
    queryset = UtilityProvider.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['utility_category', 'is_active']
    search_fields = ['name', 'contact_person', 'contact_email']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return UtilityProviderCreateSerializer
        return UtilityProviderSerializer
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        active_providers = self.queryset.filter(is_active=True)
        serializer = self.get_serializer(active_providers, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def connections(self, request, pk=None):
        provider = self.get_object()
        connections = provider.building_connections.all()
        serializer = BuildingUtilityConnectionSerializer(connections, many=True)
        return Response(serializer.data)

class BuildingUtilityConnectionViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'utilities'
    queryset = BuildingUtilityConnection.objects.select_related('building', 'provider', 'utility_type').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['building', 'provider', 'utility_type', 'is_active']
    search_fields = ['connection_number', 'meter_number', 'building__name']
    ordering_fields = ['connection_date', 'created_at']
    ordering = ['building', 'utility_type']
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return BuildingUtilityConnectionCreateSerializer
        return BuildingUtilityConnectionSerializer
    
    @action(detail=False, methods=['get'])
    def by_building(self, request):
        building_id = request.query_params.get('building_id')
        building_name = request.query_params.get('building_name')
        
        if not building_id and not building_name:
            return Response({'error': 'building_id or building_name parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if building_id:
            connections = self.queryset.filter(building_id=building_id)
        else:
            connections = self.queryset.filter(building__name__iexact=building_name)
            
        serializer = self.get_serializer(connections, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        connection = self.get_object()
        connection.is_active = True
        connection.save()
        
        return Response({
            'message': 'Connection activated',
            'connection': BuildingUtilityConnectionSerializer(connection).data
        })
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        connection = self.get_object()
        connection.is_active = False
        connection.save()
        
        return Response({
            'message': 'Connection deactivated',
            'connection': BuildingUtilityConnectionSerializer(connection).data
        })

class InsuranceProviderViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'utilities'
    queryset = InsuranceProvider.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['insurance_type', 'is_active']
    search_fields = ['name', 'contact_person', 'contact_email', 'policy_number']
    ordering_fields = ['name', 'policy_end_date', 'created_at']
    ordering = ['name']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return InsuranceProviderCreateSerializer
        return InsuranceProviderSerializer

    @action(detail=False, methods=['get'])
    def active(self, request):
        active_providers = self.queryset.filter(is_active=True)
        serializer = self.get_serializer(active_providers, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def buildings(self, request, pk=None):
        provider = self.get_object()
        insurances = provider.building_insurances.all()
        serializer = BuildingInsuranceSerializer(insurances, many=True)
        return Response(serializer.data)

class BuildingInsuranceViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'utilities'
    queryset = BuildingInsurance.objects.select_related('building', 'provider').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['building', 'provider', 'is_active']
    search_fields = ['policy_number', 'building__name', 'provider__name']
    ordering_fields = ['policy_start_date', 'policy_end_date', 'created_at']
    ordering = ['-policy_start_date']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return BuildingInsuranceCreateSerializer
        return BuildingInsuranceSerializer

    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        days = int(request.query_params.get('days', 30))
        from datetime import timedelta as td
        cutoff = timezone.now().date() + td(days=days)
        expiring = self.queryset.filter(is_active=True, policy_end_date__lte=cutoff, policy_end_date__gte=timezone.now().date())
        serializer = self.get_serializer(expiring, many=True)
        return Response(serializer.data)

@cache_page(300)
@extend_schema(responses=UtilityStatsSerializer)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def utility_dashboard_stats(request):
    total_utility_types = UtilityType.objects.filter(is_active=True).count()
    total_bills = UtilityBill.objects.count()
    pending_bills = UtilityBill.objects.filter(status='pending').count()
    paid_bills = UtilityBill.objects.filter(status='paid').count()
    overdue_bills = UtilityBill.objects.filter(status='overdue').count()
    
    total_pending_amount = UtilityBill.objects.filter(status='pending').aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    
    total_collected_amount = UtilityBill.objects.filter(status='paid').aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    
    stats = {
        'total_utility_types': total_utility_types,
        'total_bills': total_bills,
        'pending_bills': pending_bills,
        'paid_bills': paid_bills,
        'overdue_bills': overdue_bills,
        'total_pending_amount': float(total_pending_amount),
        'total_collected_amount': float(total_collected_amount)
    }
    
    serializer = UtilityStatsSerializer(stats)
    return Response(serializer.data)

@extend_schema(responses=UtilityConsumptionReportSerializer(many=True))
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def consumption_report(request):
    from_date = request.query_params.get('from_date')
    to_date = request.query_params.get('to_date')
    utility_type_id = request.query_params.get('utility_type_id')
    
    if not all([from_date, to_date]):
        return Response(
            {'error': 'from_date and to_date parameters required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    bills = UtilityBill.objects.filter(
        billing_period_start__gte=from_date,
        billing_period_end__lte=to_date
    )
    
    if utility_type_id:
        bills = bills.filter(utility_type_id=utility_type_id)
    
    report_data = []
    for bill in bills:
        report_data.append({
            'utility_type': bill.utility_type.name,
            'unit_number': bill.unit.unit_number,
            'building_name': bill.unit.building.name,
            'total_consumption': bill.consumption,
            'total_amount': bill.total_amount,
            'period_start': bill.billing_period_start,
            'period_end': bill.billing_period_end
        })
    
    serializer = UtilityConsumptionReportSerializer(report_data, many=True)
    return Response(serializer.data)
