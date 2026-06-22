# notifications/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (NotificationViewSet, NotificationPreferenceViewSet, AnnouncementViewSet,
                    EmailTemplateViewSet, EmailLogListView, UnsubscribeView,
                    EmailCampaignViewSet, SMSAlertViewSet)

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'preferences', NotificationPreferenceViewSet, basename='notification-preference')
router.register(r'announcements', AnnouncementViewSet, basename='announcement')
router.register(r'email-templates', EmailTemplateViewSet, basename='email-template')
router.register(r'email-logs', EmailLogListView, basename='email-log')
router.register(r'unsubscribe', UnsubscribeView, basename='unsubscribe')
router.register(r'email-campaigns', EmailCampaignViewSet, basename='email-campaign')
router.register(r'sms-alerts', SMSAlertViewSet, basename='sms-alert')

urlpatterns = [
    path('', include(router.urls)),
]