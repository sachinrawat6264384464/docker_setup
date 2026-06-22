# reservations/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import ReservableResource, Reservation
from .serializers import (
    ReservableResourceSerializer, ReservationSerializer, ReservationCreateSerializer,
)


class ReservableResourceViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'reservations'
    queryset = ReservableResource.objects.all()
    serializer_class = ReservableResourceSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['resource_type', 'is_available', 'is_free', 'requires_approval']
    search_fields = ['name', 'description', 'location']
    ordering_fields = ['name', 'resource_type', 'created_at']

    @action(detail=True, methods=['get'])
    def availability(self, request, pk=None):
        """Get availability slots for a resource on a given date."""
        resource = self.get_object()
        date_str = request.query_params.get('date')
        if not date_str:
            return Response({'error': 'date query parameter is required (YYYY-MM-DD)'}, status=status.HTTP_400_BAD_REQUEST)

        from datetime import datetime, date
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        # Get existing reservations for this date
        reservations = Reservation.objects.filter(
            resource=resource,
            status__in=['approved', 'checked_in', 'pending'],
            start_time__date=target_date,
        ).values('start_time', 'end_time', 'status', 'reserved_by__first_name')

        return Response({
            'resource': resource.name,
            'date': date_str,
            'available_from': str(resource.available_from),
            'available_until': str(resource.available_until),
            'max_duration_hours': float(resource.max_duration_hours),
            'existing_reservations': list(reservations),
        })


class ReservationViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'reservations'
    queryset = Reservation.objects.select_related('resource', 'reserved_by', 'approved_by')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'resource', 'reserved_by']
    search_fields = ['reservation_number', 'purpose']
    ordering_fields = ['start_time', 'created_at', 'status']

    def get_serializer_class(self):
        if self.action == 'create':
            return ReservationCreateSerializer
        return ReservationSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Residents see only their own reservations
        if user.role == 'tenant':
            qs = qs.filter(reserved_by=user)
        return qs

    def perform_create(self, serializer):
        resource = serializer.validated_data['resource']
        # Calculate cost
        start = serializer.validated_data['start_time']
        end = serializer.validated_data['end_time']
        duration_hours = (end - start).total_seconds() / 3600
        total_cost = 0 if resource.is_free else float(resource.hourly_rate) * duration_hours

        # Auto-approve if resource doesn't require approval
        initial_status = 'pending' if resource.requires_approval else 'approved'

        serializer.save(
            reserved_by=self.request.user,
            total_cost=round(total_cost, 2),
            status=initial_status,
        )

    @action(detail=False, methods=['get'])
    def my_reservations(self, request):
        """Get current user's reservations."""
        qs = Reservation.objects.filter(reserved_by=request.user).select_related('resource')
        page = self.paginate_queryset(qs)
        serializer = ReservationSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """Get upcoming reservations."""
        qs = self.get_queryset().filter(
            start_time__gte=timezone.now(),
            status__in=['approved', 'pending'],
        ).order_by('start_time')
        page = self.paginate_queryset(qs)
        serializer = ReservationSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a pending reservation."""
        reservation = self.get_object()
        if reservation.status != 'pending':
            return Response({'error': 'Only pending reservations can be approved'}, status=status.HTTP_400_BAD_REQUEST)
        if reservation.has_conflict():
            return Response({'error': 'This reservation conflicts with an existing approved reservation'}, status=status.HTTP_409_CONFLICT)
        reservation.status = 'approved'
        reservation.approved_by = request.user
        reservation.save(update_fields=['status', 'approved_by', 'updated_at'])
        return Response(ReservationSerializer(reservation).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a pending reservation."""
        reservation = self.get_object()
        if reservation.status != 'pending':
            return Response({'error': 'Only pending reservations can be rejected'}, status=status.HTTP_400_BAD_REQUEST)
        reservation.status = 'rejected'
        reservation.rejection_reason = request.data.get('reason', '')
        reservation.save(update_fields=['status', 'rejection_reason', 'updated_at'])
        return Response(ReservationSerializer(reservation).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a reservation."""
        reservation = self.get_object()
        if reservation.status in ('completed', 'cancelled', 'no_show'):
            return Response({'error': 'This reservation cannot be cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        reservation.status = 'cancelled'
        reservation.cancelled_at = timezone.now()
        reservation.cancellation_reason = request.data.get('reason', '')
        reservation.save(update_fields=['status', 'cancelled_at', 'cancellation_reason', 'updated_at'])
        return Response(ReservationSerializer(reservation).data)

    @action(detail=True, methods=['post'])
    def check_in(self, request, pk=None):
        """Check in for a reservation."""
        reservation = self.get_object()
        if reservation.status != 'approved':
            return Response({'error': 'Only approved reservations can be checked in'}, status=status.HTTP_400_BAD_REQUEST)
        reservation.status = 'checked_in'
        reservation.checked_in_at = timezone.now()
        reservation.save(update_fields=['status', 'checked_in_at', 'updated_at'])
        return Response(ReservationSerializer(reservation).data)

    @action(detail=True, methods=['post'])
    def check_out(self, request, pk=None):
        """Check out from a reservation."""
        reservation = self.get_object()
        if reservation.status != 'checked_in':
            return Response({'error': 'Only checked-in reservations can be checked out'}, status=status.HTTP_400_BAD_REQUEST)
        reservation.status = 'completed'
        reservation.checked_out_at = timezone.now()
        reservation.save(update_fields=['status', 'checked_out_at', 'updated_at'])
        return Response(ReservationSerializer(reservation).data)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def reservations_dashboard(request):
    """Reservations dashboard statistics."""
    now = timezone.now()
    
    res_stats = Reservation.objects.aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(status='pending')),
        approved_upcoming=Count('id', filter=Q(status='approved', start_time__gte=now)),
        checked_in=Count('id', filter=Q(status='checked_in')),
        completed_this_month=Count('id', filter=Q(status='completed', completed_at__month=now.month, completed_at__year=now.year)),
        cancelled=Count('id', filter=Q(status='cancelled'))
    )

    stats = {
        'total_resources': ReservableResource.objects.filter(is_available=True).count(),
        'total_reservations': res_stats['total'] or 0,
        'pending': res_stats['pending'] or 0,
        'approved_upcoming': res_stats['approved_upcoming'] or 0,
        'checked_in': res_stats['checked_in'] or 0,
        'completed_this_month': res_stats['completed_this_month'] or 0,
        'cancelled': res_stats['cancelled'] or 0,
        'by_resource_type': dict(
            ReservableResource.objects.values_list('resource_type')
            .annotate(count=Count('reservations'))
            .values_list('resource_type', 'count')
        ),
    }
    return Response(stats)
