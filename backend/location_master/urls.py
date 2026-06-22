from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CountryViewSet, StateViewSet, DistrictViewSet,
    CityViewSet, PincodeViewSet, AreaViewSet,
)

router = DefaultRouter()
router.register(r'countries', CountryViewSet, basename='country')
router.register(r'states', StateViewSet, basename='state')
router.register(r'districts', DistrictViewSet, basename='district')
router.register(r'cities', CityViewSet, basename='city')
router.register(r'pincodes', PincodeViewSet, basename='pincode')
router.register(r'areas', AreaViewSet, basename='area')

urlpatterns = [
    path('', include(router.urls)),
]
