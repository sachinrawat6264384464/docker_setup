# visitors/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    VisitorTypeViewSet, VisitorViewSet, VisitorPassViewSet,
    VisitorLogViewSet, BlacklistedVisitorViewSet, VisitorFeedbackViewSet
)

router = DefaultRouter()
router.register(r'visitor-types', VisitorTypeViewSet, basename='visitor-type')
router.register(r'visitors', VisitorViewSet, basename='visitor')
router.register(r'passes', VisitorPassViewSet, basename='visitor-pass')
router.register(r'logs', VisitorLogViewSet, basename='visitor-log')
router.register(r'blacklist', BlacklistedVisitorViewSet, basename='blacklisted-visitor')
router.register(r'feedback', VisitorFeedbackViewSet, basename='visitor-feedback')

urlpatterns = [
    path('', include(router.urls)),
]
