# properties/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
# ---- Existing ----
router.register(r'buildings', views.BuildingViewSet, basename='building')
router.register(r'units', views.UnitViewSet, basename='unit')
router.register(r'leases', views.LeaseViewSet, basename='lease')
router.register(r'documents', views.PropertyDocumentViewSet, basename='property-document')
# ---- Hierarchy ----
router.register(r'cities', views.PropertyCityViewSet, basename='property-city')
router.register(r'area-zones', views.AreaZoneViewSet, basename='area-zone')
router.register(r'townships', views.TownshipViewSet, basename='township')
router.register(r'blocks', views.BlockViewSet, basename='block')
router.register(r'floors', views.FloorViewSet, basename='floor')
router.register(r'apartments', views.ApartmentViewSet, basename='apartment')
# ---- FM Assignments ----
router.register(r'fm-assignments', views.FacilityManagerAssignmentViewSet, basename='fm-assignment')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/stats/', views.property_dashboard_stats, name='property-dashboard-stats'),
]
