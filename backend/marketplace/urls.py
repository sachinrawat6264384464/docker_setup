from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MarketItemViewSet, MarketInterestViewSet

router = DefaultRouter()
router.register(r'items', MarketItemViewSet, basename='marketitem')
router.register(r'interests', MarketInterestViewSet, basename='marketinterest')

urlpatterns = [
    path('', include(router.urls)),
]
