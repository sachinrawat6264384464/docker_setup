# amenities/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'amenities', views.AmenityViewSet, basename='amenity')
router.register(r'bookings', views.AmenityBookingViewSet, basename='amenity-booking')
router.register(r'reviews', views.AmenityReviewViewSet, basename='amenity-review')
router.register(r'maintenance', views.AmenityMaintenanceViewSet, basename='amenity-maintenance')
router.register(r'usage-logs', views.AmenityUsageLogViewSet, basename='amenity-usage')
router.register(r'rules', views.AmenityRuleViewSet, basename='amenity-rule')

urlpatterns = [
    path('dashboard/', views.amenity_dashboard, name='amenity-dashboard'),
    path('', include(router.urls)),
]