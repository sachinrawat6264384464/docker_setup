# ========================================
# FILE 5: entertainment/urls.py
# ========================================
# (This file is already correct, keeping as-is)
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'events', views.EventViewSet, basename='event')
router.register(r'registrations', views.EventRegistrationViewSet, basename='event-registration')
router.register(r'clubs', views.ClubViewSet, basename='club')

urlpatterns = [
    path('', include(router.urls)),
]