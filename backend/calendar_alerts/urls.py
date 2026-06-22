# calendar/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'alerts', views.CalendarAlertViewSet, basename='calendar-alert')
router.register(r'recipients', views.AlertRecipientViewSet, basename='alert-recipient')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/stats/', views.calendar_dashboard_stats, name='calendar-dashboard-stats'),
]

