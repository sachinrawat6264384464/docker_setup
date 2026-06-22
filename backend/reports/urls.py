# reports/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

print("DEBUG: reports/urls.py (test/backend) is being loaded")
router = DefaultRouter()
router.register(r'templates', views.ReportTemplateViewSet, basename='report-template')
router.register(r'generated', views.GeneratedReportViewSet, basename='generated-report')
router.register(r'scheduled', views.ScheduledReportViewSet, basename='scheduled-report')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', views.reports_dashboard, name='reports-dashboard'),
]
