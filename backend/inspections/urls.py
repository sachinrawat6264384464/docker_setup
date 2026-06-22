# inspections/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'templates', views.InspectionTemplateViewSet, basename='inspection-template')
router.register(r'inspections', views.InspectionViewSet, basename='inspection')
router.register(r'photos', views.InspectionPhotoViewSet, basename='inspection-photo')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', views.inspections_dashboard, name='inspections-dashboard'),
]
