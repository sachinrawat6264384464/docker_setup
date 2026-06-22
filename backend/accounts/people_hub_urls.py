# accounts/people_hub_urls.py - People Hub URL Configuration
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import people_hub_views

# Create router for People Hub ViewSet
router = DefaultRouter()
router.register(r'residents', people_hub_views.PeopleHubViewSet, basename='residents')

urlpatterns = [
    # Include router URLs (provides full CRUD)
    path('', include(router.urls)),
    
    # Additional People Hub endpoints
    path('stats/', people_hub_views.people_hub_stats, name='people-hub-stats'),
    path('residents/<uuid:resident_id>/activity/', people_hub_views.resident_activity, name='resident-activity'),
    path('residents-by-building/', people_hub_views.residents_by_building, name='residents-by-building'),
    path('export/', people_hub_views.export_residents, name='export-residents'),
    path('send-notification/', people_hub_views.send_bulk_notification, name='send-bulk-notification'),
    path('directory/', people_hub_views.residents_directory, name='residents-directory'),
]