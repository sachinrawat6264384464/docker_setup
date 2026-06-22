# security/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q, Count, Avg, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from datetime import datetime, timedelta
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from notifications.services import NotificationService

from accounts.permissions import ModulePermissionMixin, HasModulePermission, IsFacilityManagerOrAbove

from .models import (
    SecurityGuard, SecurityIncident, VisitorLog, AccessControl,
    AccessLog, PatrolLog, EmergencyAlert, CCTVCamera, SecurityAnnouncement
)
from .serializers import (
    SecurityGuardSerializer, SecurityGuardCreateSerializer,
    SecurityIncidentSerializer, SecurityIncidentCreateSerializer,
    VisitorLogSerializer, VisitorPreApprovalSerializer,
    AccessControlSerializer, AccessLogSerializer,
    PatrolLogSerializer, EmergencyAlertSerializer,
    CCTVCameraSerializer, SecurityAnnouncementSerializer,
    SecurityDashboardSerializer, IncidentStatisticsSerializer,
    VisitorStatisticsSerializer
)


class SecurityGuardViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing security guards"""
    module = 'security'
    queryset = SecurityGuard.objects.all().select_related('user', 'created_by')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['shift', 'status', 'assigned_building']
    search_fields = ['user__first_name', 'user__last_name', 'employee_id', 'user__email']
    ordering_fields = ['created_at', 'joining_date', 'performance_rating']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return SecurityGuardCreateSerializer
        return SecurityGuardSerializer
    
    @action(detail=True, methods=['post'])
    def assign_shift(self, request, pk=None):
        """Assign or change guard shift"""
        guard = self.get_object()
        shift = request.data.get('shift')
        
        if shift not in dict(SecurityGuard.SHIFT_CHOICES):
            return Response({'error': 'Invalid shift'}, status=status.HTTP_400_BAD_REQUEST)
        
        guard.shift = shift
        guard.save()
        
        return Response({
            'message': 'Shift assigned successfully',
            'guard': SecurityGuardSerializer(guard).data
        })
    
    @action(detail=True, methods=['post'])
    def update_performance(self, request, pk=None):
        """Update guard performance rating"""
        guard = self.get_object()
        rating = request.data.get('performance_rating')
        
        if not rating or float(rating) < 0 or float(rating) > 5:
            return Response({'error': 'Rating must be between 0 and 5'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        guard.performance_rating = rating
        guard.save()
        
        return Response({
            'message': 'Performance rating updated',
            'guard': SecurityGuardSerializer(guard).data
        })
    
    @action(detail=False, methods=['get'])
    def on_duty(self, request):
        """Get all guards currently on duty"""
        now = timezone.now()
        current_hour = now.hour
        
        # Determine current shift
        if 6 <= current_hour < 14:
            shift = 'morning'
        elif 14 <= current_hour < 22:
            shift = 'afternoon'
        else:
            shift = 'night'
        
        guards = self.queryset.filter(
            Q(shift=shift) | Q(shift='rotating'),
            status='active'
        )
        
        serializer = self.get_serializer(guards, many=True)
        return Response({
            'current_shift': shift,
            'guards_on_duty': serializer.data
        })
    
    @action(detail=True, methods=['get'])
    def performance_report(self, request, pk=None):
        """Get detailed performance report for a guard"""
        guard = self.get_object()
        
        # Get statistics
        total_incidents = guard.assigned_incidents.count()
        resolved_incidents = guard.assigned_incidents.filter(status='resolved').count()
        patrols_completed = guard.patrols.filter(status='completed').count()
        patrols_missed = guard.patrols.filter(status='missed').count()
        
        response_times = []
        for incident in guard.assigned_incidents.filter(status='resolved'):
            if incident.resolved_at and incident.reported_at:
                delta = incident.resolved_at - incident.reported_at
                response_times.append(delta.total_seconds() / 3600)
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        return Response({
            'guard': SecurityGuardSerializer(guard).data,
            'statistics': {
                'total_incidents_assigned': total_incidents,
                'incidents_resolved': resolved_incidents,
                'resolution_rate': round((resolved_incidents / total_incidents * 100), 2) if total_incidents > 0 else 0,
                'average_response_time_hours': round(avg_response_time, 2),
                'patrols_completed': patrols_completed,
                'patrols_missed': patrols_missed,
                'patrol_completion_rate': round((patrols_completed / (patrols_completed + patrols_missed) * 100), 2) if (patrols_completed + patrols_missed) > 0 else 0
            }
        })


class SecurityIncidentViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing security incidents"""
    module = 'security'
    queryset = SecurityIncident.objects.all().select_related(
        'reported_by', 'assigned_to', 'assigned_to__user'
    ).prefetch_related('witnesses')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['incident_type', 'severity', 'status', 'building']
    search_fields = ['incident_number', 'title', 'description', 'location']
    ordering_fields = ['occurred_at', 'reported_at', 'severity']
    ordering = ['-occurred_at']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return SecurityIncidentCreateSerializer
        return SecurityIncidentSerializer
        
    def get_permissions(self):
        if self.action == 'destroy':
            return [permissions.IsAuthenticated(), IsFacilityManagerOrAbove()]
        return super().get_permissions()
    
    def perform_create(self, serializer):
        incident = serializer.save(reported_by=self.request.user)
        
        # Auto-assign to available guard if critical
        if incident.severity == 'critical':
            self._auto_assign_guard(incident)
    
    def _auto_assign_guard(self, incident):
        """Auto-assign incident to available guard"""
        # Find guard with least open incidents
        guards = SecurityGuard.objects.filter(status='active').annotate(
            open_incidents=Count('assigned_incidents', filter=Q(assigned_incidents__status__in=['reported', 'investigating']))
        ).order_by('open_incidents')
        
        if guards.exists():
            incident.assigned_to = guards.first()
            incident.save()
    
    @action(detail=True, methods=['post'])
    def assign_guard(self, request, pk=None):
        """Assign incident to a security guard"""
        incident = self.get_object()
        guard_id = request.data.get('guard_id')
        
        try:
            guard = SecurityGuard.objects.get(id=guard_id, status='active')
            incident.assigned_to = guard
            incident.status = 'investigating'
            incident.save()
            
            # Update guard's incident count
            guard.incidents_reported += 1
            guard.save()
            
            return Response({
                'message': 'Incident assigned successfully',
                'incident': SecurityIncidentSerializer(incident).data
            })
        except SecurityGuard.DoesNotExist:
            return Response({'error': 'Guard not found or inactive'}, 
                          status=status.HTTP_404_NOT_FOUND)
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update incident status"""
        incident = self.get_object()
        new_status = request.data.get('status')
        notes = request.data.get('notes', '')
        
        if new_status not in dict(SecurityIncident.STATUS_CHOICES):
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)
        
        incident.status = new_status
        
        if new_status == 'resolved':
            incident.resolved_at = timezone.now()
            incident.resolution_notes = notes
            
            # Update guard's resolved count
            if incident.assigned_to:
                incident.assigned_to.incidents_resolved += 1
                incident.assigned_to.save()
        elif new_status == 'investigating':
            incident.investigation_notes = notes
        
        incident.save()
        
        return Response({
            'message': 'Status updated successfully',
            'incident': SecurityIncidentSerializer(incident).data
        })
    
    @action(detail=False, methods=['get'])
    def critical_open(self, request):
        """Get all critical open incidents"""
        incidents = self.queryset.filter(
            severity='critical',
            status__in=['reported', 'investigating', 'escalated']
        )
        serializer = self.get_serializer(incidents, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get incident statistics"""
        # Time period filter
        period = request.query_params.get('period', '30')  # days
        start_date = timezone.now() - timedelta(days=int(period))
        
        incidents = self.queryset.filter(occurred_at__gte=start_date)
        
        # By type
        by_type = incidents.values('incident_type').annotate(count=Count('id'))
        total = incidents.count()
        
        type_stats = [
            {
                'incident_type': item['incident_type'],
                'count': item['count'],
                'percentage': round((item['count'] / total * 100), 2) if total > 0 else 0
            }
            for item in by_type
        ]
        
        # By severity
        by_severity = incidents.values('severity').annotate(count=Count('id'))
        
        # By status
        by_status = incidents.values('status').annotate(count=Count('id'))
        
        # Resolution time
        resolved = incidents.filter(status='resolved', resolved_at__isnull=False)
        response_times = []
        for inc in resolved:
            delta = inc.resolved_at - inc.reported_at
            response_times.append(delta.total_seconds() / 3600)
        
        avg_resolution_time = sum(response_times) / len(response_times) if response_times else 0
        
        return Response({
            'total_incidents': total,
            'by_type': type_stats,
            'by_severity': list(by_severity),
            'by_status': list(by_status),
            'average_resolution_time_hours': round(avg_resolution_time, 2),
            'resolution_rate': round((resolved.count() / total * 100), 2) if total > 0 else 0
        })


class VisitorLogViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing visitor logs"""
    module = 'security'
    queryset = VisitorLog.objects.all().select_related(
        'host', 'checked_in_by', 'checked_out_by', 'pre_approved_by'
    )
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['visitor_type', 'status', 'host_building', 'host_unit']
    search_fields = ['visitor_name', 'visitor_phone', 'visitor_email', 'vehicle_number']
    ordering_fields = ['expected_arrival', 'actual_checkin']
    ordering = ['-expected_arrival']
    
    def get_serializer_class(self):
        if self.action == 'pre_approve':
            return VisitorPreApprovalSerializer
        return VisitorLogSerializer
    
    @action(detail=False, methods=['post'])
    def pre_approve(self, request):
        """Pre-approve a visitor"""
        serializer = VisitorPreApprovalSerializer(data=request.data)
        if serializer.is_valid():
            visitor = serializer.save(
                is_pre_approved=True,
                pre_approved_by=request.user,
                approval_code=self._generate_approval_code(),
                status='approved'
            )
            
            # Send notification to visitor (if email provided)
            try:
                if visitor.host:
                    NotificationService.send(
                        user=visitor.host,
                        title='Visitor Pre-Approved',
                        message=f'Visitor {visitor.visitor_name} has been pre-approved with code: {visitor.approval_code}',
                        notification_type='visitor',
                        priority='medium',
                        send_email=True,
                        send_push=True
                    )
            except Exception:
                pass

            return Response({
                'message': 'Visitor pre-approved successfully',
                'approval_code': visitor.approval_code,
                'visitor': VisitorLogSerializer(visitor).data
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def _generate_approval_code(self):
        """Generate unique approval code"""
        import random
        import string
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    @action(detail=True, methods=['post'])
    def check_in(self, request, pk=None):
        """Check in a visitor"""
        visitor = self.get_object()
        
        if visitor.status == 'checked_in':
            return Response({'error': 'Visitor already checked in'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        # Get guard from request
        try:
            guard = SecurityGuard.objects.get(user=request.user, status='active')
        except SecurityGuard.DoesNotExist:
            return Response({'error': 'Only active security guards can check in visitors'}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        visitor.actual_checkin = timezone.now()
        visitor.status = 'checked_in'
        visitor.checked_in_by = guard
        visitor.save()

        # Notify host
        try:
            if visitor.host:
                NotificationService.send(
                    user=visitor.host,
                    title='Visitor Arrived',
                    message=f'Your visitor {visitor.visitor_name} has checked in at the gate.',
                    notification_type='visitor',
                    priority='medium',
                    send_push=True
                )
        except Exception:
            pass

        return Response({
            'message': 'Visitor checked in successfully',
            'visitor': VisitorLogSerializer(visitor).data
        })
    
    @action(detail=True, methods=['post'])
    def check_out(self, request, pk=None):
        """Check out a visitor"""
        visitor = self.get_object()
        
        if visitor.status != 'checked_in':
            return Response({'error': 'Visitor not checked in'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        try:
            guard = SecurityGuard.objects.get(user=request.user, status='active')
        except SecurityGuard.DoesNotExist:
            return Response({'error': 'Only active security guards can check out visitors'}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        visitor.actual_checkout = timezone.now()
        visitor.status = 'checked_out'
        visitor.checked_out_by = guard
        
        # Return access card if issued
        if visitor.access_card_issued and not visitor.access_card_returned:
            visitor.access_card_returned = request.data.get('card_returned', False)
        
        visitor.save()
        
        return Response({
            'message': 'Visitor checked out successfully',
            'visitor': VisitorLogSerializer(visitor).data
        })
    
    @action(detail=False, methods=['get'])
    def active_visitors(self, request):
        """Get all currently checked in visitors"""
        visitors = self.queryset.filter(status='checked_in')
        serializer = self.get_serializer(visitors, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def todays_visitors(self, request):
        """Get all visitors for today"""
        today = timezone.now().date()
        visitors = self.queryset.filter(expected_arrival__date=today)
        serializer = self.get_serializer(visitors, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get visitor statistics"""
        period = request.query_params.get('period', '30')
        start_date = timezone.now() - timedelta(days=int(period))
        
        visitors = self.queryset.filter(expected_arrival__gte=start_date)
        total = visitors.count()
        
        # By type
        by_type = visitors.values('visitor_type').annotate(count=Count('id'))
        type_stats = [
            {
                'visitor_type': item['visitor_type'],
                'count': item['count'],
                'percentage': round((item['count'] / total * 100), 2) if total > 0 else 0
            }
            for item in by_type
        ]
        
        # By status
        by_status = visitors.values('status').annotate(count=Count('id'))
        
        return Response({
            'total_visitors': total,
            'by_type': type_stats,
            'by_status': list(by_status),
            'pre_approved': visitors.filter(is_pre_approved=True).count(),
            'walk_ins': visitors.filter(is_pre_approved=False).count()
        })


class AccessControlViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing access controls"""
    module = 'security'
    queryset = AccessControl.objects.all().select_related('user', 'issued_by', 'revoked_by')
    serializer_class = AccessControlSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['access_type', 'status', 'user']
    search_fields = ['card_number', 'user__first_name', 'user__last_name', 'user__email']
    ordering_fields = ['created_at', 'valid_from', 'valid_until']
    ordering = ['-created_at']
    
    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        """Revoke access control"""
        access = self.get_object()
        
        if access.status == 'revoked':
            return Response({'error': 'Access already revoked'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        access.status = 'revoked'
        access.revoked_by = request.user
        access.revoke_reason = request.data.get('reason', '')
        access.save()
        
        return Response({
            'message': 'Access revoked successfully',
            'access': AccessControlSerializer(access).data
        })
    
    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        """Reactivate revoked access"""
        access = self.get_object()
        
        if access.status != 'revoked':
            return Response({'error': 'Only revoked access can be reactivated'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        access.status = 'active'
        access.revoked_by = None
        access.revoke_reason = ''
        access.save()
        
        return Response({
            'message': 'Access reactivated successfully',
            'access': AccessControlSerializer(access).data
        })
    
    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        """Get access controls expiring in next 30 days"""
        thirty_days = timezone.now() + timedelta(days=30)
        access_controls = self.queryset.filter(
            status='active',
            valid_until__lte=thirty_days,
            valid_until__gte=timezone.now()
        )
        serializer = self.get_serializer(access_controls, many=True)
        return Response(serializer.data)


class AccessLogViewSet(ModulePermissionMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing access logs (read-only)"""
    module = 'security'
    queryset = AccessLog.objects.all().select_related('access_control', 'user')
    serializer_class = AccessLogSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['access_result', 'access_point', 'is_suspicious']
    search_fields = ['card_number', 'access_point', 'access_area']
    ordering_fields = ['attempted_at']
    ordering = ['-attempted_at']
    
    @action(detail=False, methods=['get'])
    def suspicious(self, request):
        """Get all suspicious access attempts"""
        logs = self.queryset.filter(is_suspicious=True)
        serializer = self.get_serializer(logs, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def denied(self, request):
        """Get all denied access attempts"""
        logs = self.queryset.filter(access_result__in=['denied', 'invalid', 'expired'])
        serializer = self.get_serializer(logs, many=True)
        return Response(serializer.data)


class PatrolLogViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing patrol logs"""
    module = 'security'
    queryset = PatrolLog.objects.all().select_related('guard', 'guard__user').prefetch_related('incidents_found')
    serializer_class = PatrolLogSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['guard', 'status', 'patrol_route']
    search_fields = ['patrol_route', 'guard__user__first_name', 'guard__user__last_name']
    ordering_fields = ['scheduled_start', 'actual_start']
    ordering = ['-scheduled_start']
    
    @action(detail=True, methods=['post'])
    def start_patrol(self, request, pk=None):
        """Start a patrol"""
        patrol = self.get_object()
        
        if patrol.status != 'scheduled':
            return Response({'error': 'Patrol already started or completed'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        patrol.actual_start = timezone.now()
        patrol.status = 'in_progress'
        patrol.save()
        
        return Response({
            'message': 'Patrol started',
            'patrol': PatrolLogSerializer(patrol).data
        })
    
    @action(detail=True, methods=['post'])
    def complete_patrol(self, request, pk=None):
        """Complete a patrol"""
        patrol = self.get_object()
        
        if patrol.status != 'in_progress':
            return Response({'error': 'Patrol not in progress'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        patrol.actual_end = timezone.now()
        patrol.status = 'completed'
        patrol.checkpoints_completed = request.data.get('checkpoints_completed', [])
        patrol.observations = request.data.get('observations', '')
        patrol.save()
        
        return Response({
            'message': 'Patrol completed',
            'patrol': PatrolLogSerializer(patrol).data
        })
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get active patrols"""
        patrols = self.queryset.filter(status='in_progress')
        serializer = self.get_serializer(patrols, many=True)
        return Response(serializer.data)


class EmergencyAlertViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing emergency alerts"""
    module = 'security'
    queryset = EmergencyAlert.objects.all().select_related(
        'triggered_by', 'acknowledged_by', 'acknowledged_by__user'
    ).prefetch_related('responders')
    serializer_class = EmergencyAlertSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['alert_type', 'priority', 'status', 'building']
    search_fields = ['title', 'description', 'location']
    ordering_fields = ['triggered_at', 'priority']
    ordering = ['-triggered_at']
    
    def get_permissions(self):
        """Allow any authenticated user to create an emergency alert (SOS)."""
        if self.action == 'create':
            return [permissions.IsAuthenticated()]
        return super().get_permissions()
    
    def perform_create(self, serializer):
        alert = serializer.save(triggered_by=self.request.user)
        
        # Auto-notify guards for critical alerts
        if alert.priority == 'critical':
            self._notify_all_guards(alert)
    
    def _notify_all_guards(self, alert):
        """Notify all active guards and facility managers of critical alert"""
        try:
            # Notify Security Guards
            active_guards = SecurityGuard.objects.filter(status='active').select_related('user')
            for guard in active_guards:
                NotificationService.send(
                    user=guard.user,
                    title=f'EMERGENCY: {alert.title}',
                    message=f'{alert.alert_type.upper()} alert at {alert.location}: {alert.description[:200]}',
                    notification_type='security_alert',
                    priority='high',
                    send_email=True,
                    send_sms=True,
                    send_push=True
                )
            
            # Also notify Facility Managers
            from accounts.models import User
            fms = User.objects.filter(role='facility_manager', is_active=True)
            for fm in fms:
                NotificationService.send(
                    user=fm,
                    title=f'🚨 SOS ALERT: {alert.title}',
                    message=f'EMERGENCY at {alert.location} (Unit {alert.unit_number}). Triggered by {alert.triggered_by.get_full_name()}.',
                    notification_type='security_alert',
                    priority='high',
                    send_email=True,
                    send_push=True,
                    related_object_type='emergency_alert',
                    related_object_id=alert.id,
                    action_url=f'/manager/security?alert={alert.id}'
                )
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.error(f"Failed to notify guards/FMs for alert {alert.id}: {str(e)}")
    
    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        """Acknowledge an alert"""
        alert = self.get_object()
        
        if alert.status != 'active':
            return Response({'error': 'Alert already acknowledged'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        try:
            guard = SecurityGuard.objects.get(user=request.user, status='active')
        except SecurityGuard.DoesNotExist:
            return Response({'error': 'Only active security guards can acknowledge alerts'}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        alert.acknowledged_at = timezone.now()
        alert.acknowledged_by = guard
        alert.status = 'acknowledged'
        alert.save()
        
        return Response({
            'message': 'Alert acknowledged',
            'alert': EmergencyAlertSerializer(alert).data
        })
    
    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Resolve an alert"""
        alert = self.get_object()
        
        alert.resolved_at = timezone.now()
        alert.status = 'resolved'
        alert.resolution_notes = request.data.get('resolution_notes', '')
        alert.save()
        
        return Response({
            'message': 'Alert resolved',
            'alert': EmergencyAlertSerializer(alert).data
        })
    
    @action(detail=False, methods=['get'])
    def active_alerts(self, request):
        """Get all active alerts"""
        alerts = self.queryset.filter(status__in=['active', 'acknowledged', 'responding'])
        serializer = self.get_serializer(alerts, many=True)
        return Response(serializer.data)


class CCTVCameraViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing CCTV cameras"""
    module = 'security'
    queryset = CCTVCamera.objects.all()
    serializer_class = CCTVCameraSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'building', 'floor']
    search_fields = ['camera_id', 'camera_name', 'location']
    ordering_fields = ['camera_id', 'location']
    ordering = ['camera_id']
    
    @action(detail=False, methods=['get'])
    def offline_cameras(self, request):
        """Get all offline cameras"""
        cameras = self.queryset.filter(status='offline')
        serializer = self.get_serializer(cameras, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def maintenance_due(self, request):
        """Get cameras due for maintenance"""
        today = timezone.now().date()
        cameras = self.queryset.filter(next_maintenance__lte=today)
        serializer = self.get_serializer(cameras, many=True)
        return Response(serializer.data)


class SecurityAnnouncementViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing security announcements"""
    module = 'security'
    queryset = SecurityAnnouncement.objects.all().select_related('created_by')
    serializer_class = SecurityAnnouncementSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['priority', 'published']
    search_fields = ['title', 'message']
    ordering_fields = ['created_at', 'published_at']
    ordering = ['-created_at']
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish an announcement"""
        announcement = self.get_object()
        
        if announcement.published:
            return Response({'error': 'Announcement already published'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        announcement.published = True
        announcement.published_at = timezone.now()
        announcement.save()
        
        # Send notifications to all active users
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            users = User.objects.filter(is_active=True)
            for user in users:
                NotificationService.send(
                    user=user,
                    title=f'Security Announcement: {announcement.title}',
                    message=announcement.message[:300],
                    notification_type='security_announcement',
                    priority=announcement.priority,
                    send_push=True
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to send announcement notifications: {str(e)}")

        return Response({
            'message': 'Announcement published successfully',
            'announcement': SecurityAnnouncementSerializer(announcement).data
        })


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def security_dashboard(request):
    """Get security dashboard statistics"""
    
    # Guards
    total_guards = SecurityGuard.objects.count()
    active_guards = SecurityGuard.objects.filter(status='active').count()
    
    # Incidents
    total_incidents = SecurityIncident.objects.count()
    open_incidents = SecurityIncident.objects.filter(
        status__in=['reported', 'investigating', 'escalated']
    ).count()
    critical_incidents = SecurityIncident.objects.filter(
        severity='critical',
        status__in=['reported', 'investigating', 'escalated']
    ).count()
    
    # Visitors
    today = timezone.now().date()
    visitors_today = VisitorLog.objects.filter(expected_arrival__date=today).count()
    active_visitors = VisitorLog.objects.filter(status='checked_in').count()
    
    # Alerts
    active_alerts = EmergencyAlert.objects.filter(
        status__in=['active', 'acknowledged', 'responding']
    ).count()
    
    # Cameras
    cameras_total = CCTVCamera.objects.count()
    cameras_online = CCTVCamera.objects.filter(status='online').count()
    
    resolved_incidents = SecurityIncident.objects.filter(status='resolved').count()
    
    data = {
        'total_guards': total_guards,
        'active_guards': active_guards,
        'total_incidents': total_incidents,
        'open_incidents': open_incidents,
        'resolved_incidents': resolved_incidents,
        'critical_incidents': critical_incidents,
        'visitors_today': visitors_today,
        'active_visitors': active_visitors,
        'active_alerts': active_alerts,
        'cameras_online': cameras_online,
        'cameras_total': cameras_total
    }
    
    serializer = SecurityDashboardSerializer(data)
    return Response(serializer.data)