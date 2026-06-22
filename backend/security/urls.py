# security/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'guards', views.SecurityGuardViewSet, basename='security-guard')
router.register(r'incidents', views.SecurityIncidentViewSet, basename='security-incident')
router.register(r'visitors', views.VisitorLogViewSet, basename='visitor')
router.register(r'access-control', views.AccessControlViewSet, basename='access-control')
router.register(r'access-logs', views.AccessLogViewSet, basename='access-log')
router.register(r'patrols', views.PatrolLogViewSet, basename='patrol')
router.register(r'emergency-alerts', views.EmergencyAlertViewSet, basename='emergency-alert')
router.register(r'cctv-cameras', views.CCTVCameraViewSet, basename='cctv-camera')
router.register(r'announcements', views.SecurityAnnouncementViewSet, basename='security-announcement')

urlpatterns = [
    path('dashboard/', views.security_dashboard, name='security-dashboard'),
    path('', include(router.urls)),
]