# vendors/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    VendorCategoryViewSet, VendorViewSet, VendorServiceViewSet,
    VendorContractViewSet, VendorReviewViewSet, VendorPaymentViewSet,
    VendorInsuranceViewSet, VendorPortalViewSet, VendorWorkOrderViewSet
)

router = DefaultRouter()
router.register(r'categories', VendorCategoryViewSet, basename='vendor-category')
router.register(r'vendors', VendorViewSet, basename='vendor')
router.register(r'services', VendorServiceViewSet, basename='vendor-service')
router.register(r'contracts', VendorContractViewSet, basename='vendor-contract')
router.register(r'reviews', VendorReviewViewSet, basename='vendor-review')
router.register(r'payments', VendorPaymentViewSet, basename='vendor-payment')
router.register(r'insurance', VendorInsuranceViewSet, basename='vendor-insurance')
router.register(r'portal', VendorPortalViewSet, basename='vendor-portal')
router.register(r'work-orders', VendorWorkOrderViewSet, basename='vendor-work-order')

urlpatterns = [
    path('statistics/', VendorViewSet.as_view({'get': 'module_statistics'}), name='vendor-module-statistics'),
    path('', include(router.urls)),
]