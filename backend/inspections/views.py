# inspections/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Avg, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import InspectionTemplate, Inspection, InspectionPhoto
from .serializers import (
    InspectionTemplateSerializer, InspectionSerializer,
    InspectionCreateSerializer, InspectionPhotoSerializer,
)


class InspectionTemplateViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'inspections'
    queryset = InspectionTemplate.objects.all()
    serializer_class = InspectionTemplateSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['inspection_type', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'inspection_type', 'created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class InspectionViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'inspections'
    queryset = Inspection.objects.select_related('template', 'inspector', 'requested_by')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['inspection_type', 'status', 'result', 'inspector', 'follow_up_required']
    search_fields = ['inspection_number', 'location_description', 'overall_notes']
    ordering_fields = ['scheduled_date', 'created_at', 'status', 'result']

    def get_serializer_class(self):
        if self.action == 'create':
            return InspectionCreateSerializer
        return InspectionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Inspectors see only their assignments; managers see all
        if user.role in ('maintenance_staff',):
            qs = qs.filter(inspector=user)
        elif user.role == 'tenant':
            qs = qs.filter(unit_id__isnull=False)  # Residents see inspections related to units
        return qs

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    @action(detail=False, methods=['get'])
    def my_inspections(self, request):
        """Get inspections assigned to the current user."""
        qs = self.get_queryset().filter(inspector=request.user)
        page = self.paginate_queryset(qs)
        serializer = InspectionSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """Get upcoming scheduled inspections."""
        qs = self.get_queryset().filter(
            status='scheduled',
            scheduled_date__gte=timezone.now(),
        ).order_by('scheduled_date')
        page = self.paginate_queryset(qs)
        serializer = InspectionSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=['get'])
    def overdue(self, request):
        """Get overdue inspections (scheduled but past due)."""
        qs = self.get_queryset().filter(
            status='scheduled',
            scheduled_date__lt=timezone.now(),
        ).order_by('scheduled_date')
        page = self.paginate_queryset(qs)
        serializer = InspectionSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start an inspection."""
        inspection = self.get_object()
        if inspection.status != 'scheduled':
            return Response({'error': 'Only scheduled inspections can be started'}, status=status.HTTP_400_BAD_REQUEST)
        inspection.status = 'in_progress'
        inspection.save(update_fields=['status', 'updated_at'])
        return Response(InspectionSerializer(inspection).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Complete an inspection with results."""
        inspection = self.get_object()
        if inspection.status not in ('scheduled', 'in_progress'):
            return Response({'error': 'This inspection cannot be completed'}, status=status.HTTP_400_BAD_REQUEST)

        inspection.status = 'completed'
        inspection.completed_date = timezone.now()
        inspection.result = request.data.get('result', 'pending')
        inspection.checklist_results = request.data.get('checklist_results', [])
        inspection.overall_notes = request.data.get('overall_notes', inspection.overall_notes)
        inspection.score = request.data.get('score')
        inspection.follow_up_required = request.data.get('follow_up_required', False)
        inspection.follow_up_notes = request.data.get('follow_up_notes', '')
        inspection.follow_up_date = request.data.get('follow_up_date')

        inspection.save(update_fields=[
            'status', 'completed_date', 'result', 'checklist_results',
            'overall_notes', 'score', 'follow_up_required', 'follow_up_notes',
            'follow_up_date', 'updated_at',
        ])
        return Response(InspectionSerializer(inspection).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an inspection."""
        inspection = self.get_object()
        if inspection.status in ('completed', 'cancelled'):
            return Response({'error': 'This inspection cannot be cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        inspection.status = 'cancelled'
        inspection.save(update_fields=['status', 'updated_at'])
        return Response(InspectionSerializer(inspection).data)


class InspectionPhotoViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'inspections'
    queryset = InspectionPhoto.objects.select_related('inspection', 'uploaded_by')
    serializer_class = InspectionPhotoSerializer
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['inspection']

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def inspections_dashboard(request):
    """Inspections dashboard statistics."""
    now = timezone.now()
    qs = Inspection.objects.all()

    stats = {
        'total_inspections': qs.count(),
        'scheduled': qs.filter(status='scheduled').count(),
        'in_progress': qs.filter(status='in_progress').count(),
        'completed': qs.filter(status='completed').count(),
        'overdue': qs.filter(status='scheduled', scheduled_date__lt=now).count(),
        'follow_up_required': qs.filter(follow_up_required=True, status='completed').count(),
        'by_result': {
            'pass': qs.filter(result='pass').count(),
            'fail': qs.filter(result='fail').count(),
            'partial': qs.filter(result='partial').count(),
        },
        'by_type': dict(
            qs.values_list('inspection_type')
            .annotate(count=Count('id'))
            .values_list('inspection_type', 'count')
        ),
        'average_score': qs.filter(score__isnull=False).aggregate(avg=Avg('score'))['avg'],
        'templates_count': InspectionTemplate.objects.filter(is_active=True).count(),
    }
    return Response(stats)
