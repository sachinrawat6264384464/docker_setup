# calendar/views.py
from rest_framework import viewsets, filters, permissions, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import CalendarAlert, AlertRecipient
from .serializers import (
    CalendarAlertSerializer, CalendarAlertCreateSerializer,
    AlertRecipientSerializer, AlertRecipientCreateSerializer,
    TodayAlertsSerializer,
)

import logging
logger = logging.getLogger(__name__)

def _is_admin(user):
    """Returns True for Master Admin and Super Admin (handles both underscore/no-underscore)."""
    if not (user and getattr(user, 'is_authenticated', False)):
        return False
    role = getattr(user, 'role', None)
    return role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin')

def _is_facility_manager(user):
    return bool(user and getattr(user, 'is_authenticated', False) and getattr(user, 'role', None) == 'facility_manager')

class CalendarAlertViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'calendar'
    queryset = CalendarAlert.objects.all().select_related('building', 'created_by')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['alert_type', 'priority', 'status', 'building']
    search_fields = ['title', 'description', 'affected_area']
    ordering_fields = ['start_datetime', 'priority', 'created_at']
    ordering = ['-start_datetime']
    
    def get_permissions(self):
        """Allow facility managers to manage calendar alerts."""
        if self.action in ['create', 'update', 'partial_update'] and _is_facility_manager(self.request.user):
            return [permissions.IsAuthenticated()]
        return super().get_permissions()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        if not user or not user.is_authenticated:
            return queryset.none()
            
        role = getattr(user, 'role', None)
        if role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
            pass # Admins see all
        elif _is_facility_manager(user):
            from accounts.fm_scope import get_fm_building_names
            building_names = get_fm_building_names(user)
            if building_names:
                queryset = queryset.filter(
                    Q(building__name__in=list(building_names)) |
                    Q(building__isnull=True)
                )
            else:
                queryset = queryset.filter(building__isnull=True)
        else:
            # Residents/others
            building_name = getattr(user, 'building_name', None)
            if building_name:
                queryset = queryset.filter(
                    Q(building__name__iexact=building_name) |
                    Q(building__isnull=True)
                )
            else:
                queryset = queryset.filter(building__isnull=True)

        if self.request.query_params.get('upcoming') == 'true':
            queryset = queryset.filter(start_datetime__gte=timezone.now(), status='scheduled')

        # Filter by month and year if provided
        month = self.request.query_params.get('month')
        year = self.request.query_params.get('year')
        if month and year:
            try:
                month = int(month)
                year = int(year)
                queryset = queryset.filter(
                    start_datetime__year=year,
                    start_datetime__month=month
                )
            except ValueError:
                pass

        return queryset
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CalendarAlertCreateSerializer
        return CalendarAlertSerializer
    
    def perform_create(self, serializer):
        alert = serializer.save(created_by=self.request.user)
        
        if alert.notify_tenants:
            from accounts.models import User
            
            if alert.building:
                tenants = User.objects.filter(
                    role='tenant',
                    building_name=alert.building.name
                )
            else:
                tenants = User.objects.filter(role='tenant')
            
            for tenant in tenants:
                AlertRecipient.objects.create(alert=alert, user=tenant)
    
    @action(detail=False, methods=['get'])
    def today(self, request):
        from datetime import datetime, time
        now = timezone.now()
        today = now.date()
        
        # Safer way to get start and end of day with timezone awareness
        start_of_day = timezone.make_aware(datetime.combine(today, time.min))
        end_of_day = timezone.make_aware(datetime.combine(today, time.max))
        
        active_alerts = self.get_queryset().filter(
            start_datetime__lte=end_of_day,
            end_datetime__gte=start_of_day,
            status='active'
        )
        
        upcoming_alerts = self.get_queryset().filter(
            start_datetime__gt=now,
            start_datetime__lte=end_of_day,
            status='scheduled'
        )
        
        data = {
            'active_alerts': CalendarAlertSerializer(active_alerts, many=True).data,
            'upcoming_alerts': CalendarAlertSerializer(upcoming_alerts, many=True).data,
            'total_active': active_alerts.count(),
            'total_upcoming': upcoming_alerts.count()
        }
        
        return Response(data)
    
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        days = int(request.query_params.get('days', 7))
        now = timezone.now()
        end_date = now + timedelta(days=days)
        
        upcoming_alerts = self.get_queryset().filter(
            start_datetime__gte=now,
            start_datetime__lte=end_date,
            status='scheduled'
        ).order_by('start_datetime')
        
        serializer = self.get_serializer(upcoming_alerts, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        now = timezone.now()
        active_alerts = self.get_queryset().filter(
            start_datetime__lte=now,
            end_datetime__gte=now,
            status='active'
        )
        
        serializer = self.get_serializer(active_alerts, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_building(self, request):
        building_id = request.query_params.get('building_id')
        if not building_id:
            return Response({'error': 'building_id parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        
        alerts = self.queryset.filter(building_id=building_id)
        serializer = self.get_serializer(alerts, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def mark_completed(self, request, pk=None):
        alert = self.get_object()
        alert.status = 'completed'
        alert.save()
        
        return Response({
            'message': 'Alert marked as completed',
            'alert': CalendarAlertSerializer(alert).data
        })
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        alert = self.get_object()
        alert.status = 'cancelled'
        alert.save()
        
        return Response({
            'message': 'Alert cancelled',
            'alert': CalendarAlertSerializer(alert).data
        })
    
    @action(detail=True, methods=['post'])
    def send_notifications(self, request, pk=None):
        alert = self.get_object()
        
        recipients = alert.recipients.filter(notification_sent=False)
        
        sent_count = 0
        for recipient in recipients:
            recipient.notification_sent = True
            recipient.notification_sent_at = timezone.now()
            recipient.save()
            sent_count += 1
        
        alert.notification_sent = True
        alert.notification_sent_at = timezone.now()
        alert.save()
        
        return Response({
            'message': f'Notifications sent to {sent_count} recipients',
            'sent_count': sent_count
        })
    
    @action(detail=False, methods=['get'])
    def my_alerts(self, request):
        user = request.user
        
        # Alerts where user is an explicit recipient
        recipient_alert_ids = AlertRecipient.objects.filter(user=user).values_list('alert_id', flat=True)
        
        # Build query for relevant alerts
        q = Q(id__in=recipient_alert_ids)
        
        # Add building-level and global alerts
        if user.building_name:
            q |= Q(building__name__iexact=user.building_name)
        q |= Q(building__isnull=True)  # Global alerts
        
        relevant_alerts = CalendarAlert.objects.filter(q).select_related('building', 'created_by').distinct()
        
        now = timezone.now()
        active_alerts = []
        upcoming_alerts = []
        
        for alert in relevant_alerts:
            if alert.start_datetime <= now <= alert.end_datetime and alert.status == 'active':
                active_alerts.append(alert)
            elif alert.start_datetime > now and alert.status == 'scheduled':
                upcoming_alerts.append(alert)

        data = {
            'active_alerts': CalendarAlertSerializer(active_alerts, many=True).data,
            'upcoming_alerts': CalendarAlertSerializer(upcoming_alerts, many=True).data,
            'total_active': len(active_alerts),
            'total_upcoming': len(upcoming_alerts),
        }
        return Response(data)

class AlertRecipientViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'calendar'
    queryset = AlertRecipient.objects.select_related('alert', 'user').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['alert', 'user', 'is_read', 'notification_sent']
    search_fields = ['alert__title', 'user__first_name', 'user__last_name']
    ordering_fields = ['created_at', 'notification_sent_at', 'read_at']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return AlertRecipientCreateSerializer
        return AlertRecipientSerializer
    
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        recipient = self.get_object()
        recipient.is_read = True
        recipient.read_at = timezone.now()
        recipient.save()
        
        return Response({
            'message': 'Alert marked as read',
            'recipient': AlertRecipientSerializer(recipient).data
        })
    
    @action(detail=False, methods=['get'])
    def unread(self, request):
        unread_recipients = self.queryset.filter(user=request.user, is_read=False)
        serializer = self.get_serializer(unread_recipients, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        updated_count = self.queryset.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        
        return Response({
            'message': f'{updated_count} alerts marked as read',
            'updated_count': updated_count
        })

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def calendar_dashboard_stats(request):
    now = timezone.now()
    today = now.date()
    start_of_day = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    end_of_day = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.max.time()))
    
    total_alerts = CalendarAlert.objects.count()
    
    active_now = CalendarAlert.objects.filter(
        start_datetime__lte=now,
        end_datetime__gte=now,
        status='active'
    ).count()
    
    today_alerts = CalendarAlert.objects.filter(
        start_datetime__lte=end_of_day,
        end_datetime__gte=start_of_day
    ).count()
    
    upcoming_7_days = CalendarAlert.objects.filter(
        start_datetime__gte=now,
        start_datetime__lte=now + timedelta(days=7),
        status='scheduled'
    ).count()
    
    high_priority = CalendarAlert.objects.filter(
        priority__in=['high', 'urgent'],
        status__in=['scheduled', 'active']
    ).count()
    
    stats = {
        'total_alerts': total_alerts,
        'active_now': active_now,
        'today_alerts': today_alerts,
        'upcoming_7_days': upcoming_7_days,
        'high_priority': high_priority
    }
    
    return Response(stats)

