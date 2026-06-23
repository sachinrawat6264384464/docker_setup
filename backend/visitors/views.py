# visitors/views.py
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Count, Avg
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from datetime import datetime, timedelta
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from notifications.services import NotificationService

from .models import (
    VisitorType, Visitor, VisitorPass, VisitorLog,
    BlacklistedVisitor, VisitorFeedback
)
from .serializers import (
    VisitorTypeSerializer, VisitorSerializer, VisitorPassSerializer,
    VisitorPassCreateSerializer, VisitorLogSerializer,
    BlacklistedVisitorSerializer, VisitorFeedbackSerializer
)


class VisitorTypeViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing visitor types (guest, delivery, contractor, etc.)
    """
    module = 'visitors'
    queryset = VisitorType.objects.all()
    serializer_class = VisitorTypeSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'list':
            # Only show active types by default
            is_active = self.request.query_params.get('is_active')
            if is_active is None:
                queryset = queryset.filter(is_active=True)
        return queryset


class VisitorViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing visitor information
    """
    module = 'visitors'
    queryset = Visitor.objects.all()
    serializer_class = VisitorSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['first_name', 'last_name', 'email', 'phone', 'visitor_number', 'company_name']
    ordering_fields = ['last_visit', 'visit_count', 'first_visit']
    filterset_fields = ['is_blacklisted', 'gender']

    def get_permissions(self):
        """Allow any authenticated user to view/create visitors. Only staff can blacklist/delete."""
        from rest_framework.permissions import IsAuthenticated
        if self.action in ['blacklist', 'remove_from_blacklist', 'destroy']:
            from accounts.permissions import HasModulePermission
            return [IsAuthenticated(), HasModulePermission()]
        return [IsAuthenticated()]

    
    @action(detail=False, methods=['get'])
    def frequent_visitors(self, request):
        """Get visitors with most visits"""
        visitors = self.get_queryset().filter(
            visit_count__gt=0
        ).order_by('-visit_count')[:10]
        
        serializer = self.get_serializer(visitors, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def recent_visitors(self, request):
        """Get recent visitors"""
        days = int(request.query_params.get('days', 7))
        since_date = timezone.now() - timedelta(days=days)
        
        visitors = self.get_queryset().filter(
            last_visit__gte=since_date
        ).order_by('-last_visit')
        
        page = self.paginate_queryset(visitors)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(visitors, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def blacklist(self, request, pk=None):
        """Add visitor to blacklist"""
        visitor = self.get_object()
        reason = request.data.get('reason', '')
        is_permanent = request.data.get('is_permanent', False)
        expires_at = request.data.get('expires_at')
        
        if not reason:
            return Response(
                {'error': 'Reason is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create blacklist record
        blacklist_record, created = BlacklistedVisitor.objects.get_or_create(
            visitor=visitor,
            defaults={
                'reason': reason,
                'is_permanent': is_permanent,
                'expires_at': expires_at,
                'blacklisted_by': request.user
            }
        )
        
        # Update visitor status
        visitor.is_blacklisted = True
        visitor.blacklist_reason = reason
        visitor.blacklisted_at = timezone.now()
        visitor.blacklisted_by = request.user
        visitor.save()
        
        return Response({
            'status': 'visitor blacklisted',
            'visitor_id': str(visitor.id),
            'blacklist_id': blacklist_record.id
        })
    
    @action(detail=True, methods=['post'])
    def remove_from_blacklist(self, request, pk=None):
        """Remove visitor from blacklist"""
        visitor = self.get_object()
        
        # Delete blacklist record
        BlacklistedVisitor.objects.filter(visitor=visitor).delete()
        
        # Update visitor status
        visitor.is_blacklisted = False
        visitor.blacklist_reason = ''
        visitor.blacklisted_at = None
        visitor.blacklisted_by = None
        visitor.save()
        
        return Response({'status': 'visitor removed from blacklist'})


class VisitorPassViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing visitor passes
    """
    module = 'visitors'
    staff_actions = ['update', 'partial_update', 'destroy', 'approve', 'reject']
    queryset = VisitorPass.objects.select_related('visitor', 'visitor_type', 'host').all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['pass_number', 'visitor__first_name', 'visitor__last_name', 'building', 'unit_number']
    ordering_fields = ['created_at', 'expected_arrival', 'status']
    filterset_fields = ['status', 'building']

    def get_permissions(self):
        """Allow any authenticated user to create/view/update/approve/reject passes. Staff only for destroy."""
        from rest_framework.permissions import IsAuthenticated
        if self.action in ['destroy']:
            from accounts.permissions import HasModulePermission
            return [IsAuthenticated(), HasModulePermission()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'create':
            return VisitorPassCreateSerializer
        return VisitorPassSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by user role
        user = self.request.user
        if user.role in ['resident', 'tenant']:
            # Residents only see their own passes
            queryset = queryset.filter(host=user)
        elif user.role in ['security_guard', 'security']:
            # Security sees all passes
            pass
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by date range
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        
        if date_from:
            queryset = queryset.filter(expected_arrival__gte=date_from)
        if date_to:
            queryset = queryset.filter(expected_arrival__lte=date_to)
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def pending_approval(self, request):
        """Get passes pending approval"""
        passes = self.get_queryset().filter(
            status='pending'
        ).order_by('-created_at')
        
        page = self.paginate_queryset(passes)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(passes, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def active_passes(self, request):
        """Get currently active passes"""
        passes = self.get_queryset().filter(
            status='active',
            expected_departure__gte=timezone.now()
        ).order_by('expected_departure')
        
        serializer = self.get_serializer(passes, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def todays_passes(self, request):
        """Get today's visitor passes"""
        today = timezone.now().date()
        passes = self.get_queryset().filter(
            expected_arrival__date=today
        ).order_by('expected_arrival')
        
        serializer = self.get_serializer(passes, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a visitor pass"""
        visitor_pass = self.get_object()
        
        if visitor_pass.status != 'pending':
            return Response(
                {'error': 'Only pending passes can be approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if visitor is blacklisted
        if visitor_pass.visitor.is_blacklisted:
            return Response(
                {'error': 'Cannot approve pass for blacklisted visitor'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        visitor_pass.status = 'approved'
        visitor_pass.approved_by = request.user
        visitor_pass.approved_at = timezone.now()
        visitor_pass.save()
        
        # Generate QR code
        visitor_pass.generate_qr_code()

        # Send notification to host
        try:
            if visitor_pass.host:
                NotificationService.send(
                    user=visitor_pass.host,
                    title='Visitor Pass Approved',
                    message=f'Visitor pass for {visitor_pass.visitor.first_name} {visitor_pass.visitor.last_name} has been approved. Expected arrival: {visitor_pass.expected_arrival}',
                    notification_type='visitor',
                    priority='medium',
                    send_email=True,
                    send_push=True
                )

        except Exception:
            pass

        serializer = self.get_serializer(visitor_pass)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a visitor pass"""
        visitor_pass = self.get_object()
        reason = request.data.get('reason', '')
        
        if visitor_pass.status != 'pending':
            return Response(
                {'error': 'Only pending passes can be rejected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        visitor_pass.status = 'rejected'
        visitor_pass.rejected_by = request.user
        visitor_pass.rejected_at = timezone.now()
        visitor_pass.rejection_reason = reason
        visitor_pass.save()
        
        serializer = self.get_serializer(visitor_pass)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def check_in(self, request, pk=None):
        """Check in a visitor"""
        visitor_pass = self.get_object()
        
        if visitor_pass.status not in ['approved', 'active']:
            return Response(
                {'error': 'Pass must be approved to check in'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify access code if provided
        access_code = request.data.get('access_code')
        if access_code and access_code != visitor_pass.access_code:
            return Response(
                {'error': 'Invalid access code'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check in
        visitor_pass.check_in()
        
        # Create log entry
        VisitorLog.objects.create(
            visitor_pass=visitor_pass,
            log_type='check_in',
            security_staff=request.user,
            gate_number=request.data.get('gate_number', ''),
            entry_point=request.data.get('entry_point', ''),
            notes=request.data.get('notes', ''),
            temperature=request.data.get('temperature'),
            health_screening_passed=request.data.get('health_screening_passed', True)
        )
        
        serializer = self.get_serializer(visitor_pass)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def check_out(self, request, pk=None):
        """Check out a visitor"""
        visitor_pass = self.get_object()
        
        if visitor_pass.status != 'active':
            return Response(
                {'error': 'Pass must be active to check out'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check out
        visitor_pass.check_out()
        
        # Create log entry
        VisitorLog.objects.create(
            visitor_pass=visitor_pass,
            log_type='check_out',
            security_staff=request.user,
            gate_number=request.data.get('gate_number', ''),
            entry_point=request.data.get('entry_point', ''),
            notes=request.data.get('notes', '')
        )
        
        serializer = self.get_serializer(visitor_pass)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a visitor pass"""
        visitor_pass = self.get_object()
        
        # Only host or admin can cancel
        if visitor_pass.host != request.user and not request.user.is_staff:
            return Response(
                {'error': 'Only the host or admin can cancel this pass'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        visitor_pass.status = 'cancelled'
        visitor_pass.save()
        
        return Response({'status': 'pass cancelled'})
    
    @action(detail=True, methods=['get'])
    def verify_qr(self, request, pk=None):
        """Verify visitor pass using QR code"""
        visitor_pass = self.get_object()
        access_code = request.query_params.get('access_code')
        
        if not access_code:
            return Response(
                {'error': 'Access code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if access_code != visitor_pass.access_code:
            return Response(
                {'valid': False, 'error': 'Invalid access code'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if visitor_pass.is_expired():
            return Response(
                {'valid': False, 'error': 'Pass has expired'}
            )
        
        serializer = self.get_serializer(visitor_pass)
        return Response({
            'valid': True,
            'pass': serializer.data
        })


class VisitorLogViewSet(ModulePermissionMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing visitor logs (read-only)
    """
    module = 'visitors'
    queryset = VisitorLog.objects.all()
    serializer_class = VisitorLogSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    ordering_fields = ['timestamp']
    filterset_fields = ['log_type']
    
    def get_queryset(self):
        return super().get_queryset().select_related(
            'visitor_pass', 'visitor_pass__visitor', 'security_staff'
        ).order_by('-timestamp')
    
    @action(detail=False, methods=['get'])
    def recent_activity(self, request):
        """Get recent visitor activity"""
        hours = int(request.query_params.get('hours', 24))
        since = timezone.now() - timedelta(hours=hours)
        
        logs = self.get_queryset().filter(timestamp__gte=since)
        
        serializer = self.get_serializer(logs, many=True)
        return Response(serializer.data)


class BlacklistedVisitorViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing blacklisted visitors
    """
    module = 'visitors'
    queryset = BlacklistedVisitor.objects.all()
    serializer_class = BlacklistedVisitorSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ['blacklisted_at']
    
    def get_queryset(self):
        return super().get_queryset().select_related('visitor', 'blacklisted_by')
    
    @action(detail=False, methods=['get'])
    def active_blacklist(self, request):
        """Get currently active blacklisted visitors"""
        from django.db.models import Q
        from django.utils import timezone
        
        active = self.get_queryset().filter(
            Q(is_permanent=True) | 
            Q(expires_at__isnull=True) | 
            Q(expires_at__gt=timezone.now())
        )
        
        serializer = self.get_serializer(active, many=True)
        return Response(serializer.data)


class VisitorFeedbackViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing visitor feedback
    """
    module = 'visitors'
    queryset = VisitorFeedback.objects.all()
    serializer_class = VisitorFeedbackSerializer
    filter_backends = [filters.OrderingFilter, DjangoFilterBackend]
    ordering_fields = ['submitted_at', 'rating']
    filterset_fields = ['rating', 'would_recommend']
    
    def get_queryset(self):
        return super().get_queryset().select_related('visitor_pass')
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get feedback statistics"""
        from django.db.models import Count, Q, Avg
        
        stats = self.get_queryset().aggregate(
            total=Count('id'),
            avg_rating=Avg('rating'),
            recommend=Count('id', filter=Q(would_recommend=True)),
            positive=Count('id', filter=Q(rating__gte=4)),
            negative=Count('id', filter=Q(rating__lte=2))
        )
        
        total_count = stats['total']
        if total_count == 0:
            return Response({
                'total_responses': 0,
                'average_rating': 0,
                'recommendation_rate': 0
            })
            
        recommendation_rate = (stats['recommend'] / total_count) * 100
        
        return Response({
            'total_responses': total_count,
            'average_rating': round(stats['avg_rating'] or 0, 2),
            'recommendation_rate': round(recommendation_rate, 2),
            'positive_reviews': stats['positive'],
            'negative_reviews': stats['negative']
        })