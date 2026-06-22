# parking/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'slots', views.ParkingSlotViewSet, basename='parking-slot')
router.register(r'vehicles', views.VehicleViewSet, basename='vehicle')
router.register(r'passes', views.ParkingPassViewSet, basename='parking-pass')
router.register(r'entries', views.ParkingEntryViewSet, basename='parking-entry')

urlpatterns = [
    path('', include(router.urls)),
]