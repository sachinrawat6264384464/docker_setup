# maintenance/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'requests', views.MaintenanceRequestViewSet, basename='maintenance-request')
router.register(r'schedules', views.MaintenanceScheduleViewSet, basename='maintenance-schedule')
router.register(r'vendors', views.VendorViewSet, basename='vendor')

urlpatterns = [
    path('', include(router.urls)),
]