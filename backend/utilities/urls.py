# utilities/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'types', views.UtilityTypeViewSet, basename='utility-type')
router.register(r'bills', views.UtilityBillViewSet, basename='utility-bill')
router.register(r'readings', views.UtilityMeterReadingViewSet, basename='utility-reading')
router.register(r'providers', views.UtilityProviderViewSet, basename='utility-provider')
router.register(r'connections', views.BuildingUtilityConnectionViewSet, basename='utility-connection')
router.register(r'insurance-providers', views.InsuranceProviderViewSet, basename='insurance-provider')
router.register(r'building-insurances', views.BuildingInsuranceViewSet, basename='building-insurance')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/stats/', views.utility_dashboard_stats, name='utility-dashboard-stats'),
    path('reports/consumption/', views.consumption_report, name='utility-consumption-report'),
]
