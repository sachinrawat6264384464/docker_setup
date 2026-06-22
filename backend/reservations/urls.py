# reservations/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'resources', views.ReservableResourceViewSet, basename='reservable-resource')
router.register(r'reservations', views.ReservationViewSet, basename='reservation')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', views.reservations_dashboard, name='reservations-dashboard'),
]
