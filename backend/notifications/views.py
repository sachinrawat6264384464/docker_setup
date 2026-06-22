# notifications/views.py
from rest_framework import viewsets, mixins, permissions, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import (Notification, NotificationPreference, Announcement,
                     EmailTemplate, EmailLog, UnsubscribeRecord, EmailCampaign, SMSAlert)
from .serializers import (NotificationSerializer, NotificationPreferenceSerializer,
                          AnnouncementSerializer, EmailTemplateSerializer,
                          EmailLogSerializer, UnsubscribeRecordSerializer,
                          EmailCampaignSerializer, SMSAlertSerializer)

class NotificationViewSet(ModulePermissionMixin, 
                          mixins.ListModelMixin,
                          mixins.RetrieveModelMixin,
                          mixins.DestroyModelMixin,
                          viewsets.GenericViewSet):
    module = 'notifications'
    queryset = Notification.objects.select_related('recipient').all()
    serializer_class = NotificationSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['notification_type', 'is_read', 'priority']
    
    def get_queryset(self):
        return self.queryset.filter(recipient=self.request.user)

    def list(self, request, *args, **kwargs):
        from django.db.utils import OperationalError, ProgrammingError
        try:
            return super().list(request, *args, **kwargs)
        except (OperationalError, ProgrammingError):
            return Response([])
    
    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_as_read()
        return Response({'message': 'Marked as read'})
    
    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        self.get_queryset().filter(is_read=False).update(is_read=True, read_at=timezone.now())
        return Response({'message': 'All notifications marked as read'})
    
    @action(detail=False, methods=['get'], url_path='unread-count')
    def unread_count(self, request):
        count = self.get_queryset().filter(is_read=False).count()
        return Response({'unread_count': count})

    @action(detail=False, methods=['get'], url_path='unread_count')
    def unread_count_underscore(self, request):
        return self.unread_count(request)



class NotificationPreferenceViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'notifications'
    queryset = NotificationPreference.objects.all()
    serializer_class = NotificationPreferenceSerializer
    
    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)


class AnnouncementViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'notifications'
    queryset = Announcement.objects.all()
    serializer_class = AnnouncementSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_published']
    search_fields = ['title', 'content']
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        announcement = self.get_object()
        announcement.is_published = True
        announcement.published_at = timezone.now()
        announcement.save()
        return Response({'message': 'Published successfully'})

    def perform_create(self, serializer):
        # Auto-publish for managers/admins if not specified
        is_published = self.request.data.get('is_published', True)
        serializer.save(
            created_by=self.request.user,
            is_published=is_published,
            published_at=timezone.now() if is_published else None
        )


class EmailTemplateViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'notifications'
    queryset = EmailTemplate.objects.filter(is_active=True)
    serializer_class = EmailTemplateSerializer


class EmailLogListView(ModulePermissionMixin, viewsets.ReadOnlyModelViewSet):
    module = 'notifications'
    queryset = EmailLog.objects.all()
    serializer_class = EmailLogSerializer

    def get_queryset(self):
        schema = getattr(getattr(self.request, 'tenant', None), 'schema_name', '')
        return self.queryset.filter(tenant_schema=schema)


class UnsubscribeView(viewsets.ModelViewSet):
    queryset = UnsubscribeRecord.objects.all()
    serializer_class = UnsubscribeRecordSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        email = self.request.query_params.get('email')
        if email:
            return self.queryset.filter(email=email)
        return self.queryset.none()

    def create(self, request, *args, **kwargs):
        email = request.data.get('email', '')
        category = request.data.get('category', '')
        obj, _ = UnsubscribeRecord.objects.get_or_create(email=email, category=category)
        return Response(UnsubscribeRecordSerializer(obj).data, status=201)


class EmailCampaignViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'notifications'
    queryset = EmailCampaign.objects.all()
    serializer_class = EmailCampaignSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SMSAlertViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'notifications'
    queryset = SMSAlert.objects.all()
    serializer_class = SMSAlertSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)