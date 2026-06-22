from django.urls import path
from .views import (
    PublicPricingView,
    PricingPlanDetailView,
    TenantSubscriptionView,
    SubscribeView,
    UpgradePlanView,
    CancelSubscriptionView,
    CreateRazorpaySubscriptionView,
    VerifyRazorpaySubscriptionView,
    AllSubscriptionsView,
    RevenueSummaryView,
    SubscriptionDetailView,
    PlanServiceListCreateView,
    PlanServiceDetailView,
    PlanServicesByPlanView,
    PlanServiceMappingListCreateView,
    PlanServiceMappingDetailView,
    MyAddonsView,
    AddOnRequestListCreateView,
    AllAddOnRequestsView,
    AddOnRequestApproveView,
    AddOnRequestRejectView,
)

urlpatterns = [
    path('plans/', PublicPricingView.as_view(), name='pricing-plans'),
    path('plans/<uuid:pk>/', PricingPlanDetailView.as_view(), name='plan-detail'),
    path('subscription/', TenantSubscriptionView.as_view(), name='tenant-subscription'),
    path('subscription/subscribe/', SubscribeView.as_view(), name='subscription-subscribe'),
    path('subscription/upgrade/', UpgradePlanView.as_view(), name='subscription-upgrade'),
    path('subscription/cancel/', CancelSubscriptionView.as_view(), name='subscription-cancel'),
    path('subscription/create_razorpay_subscription/', CreateRazorpaySubscriptionView.as_view(), name='subscription-razorpay'),
    path('subscription/verify_razorpay/', VerifyRazorpaySubscriptionView.as_view(), name='subscription-verify-razorpay'),
    
    # SuperAdmin endpoints
    path('subscriptions/', AllSubscriptionsView.as_view(), name='all-subscriptions'),
    path('subscriptions/<uuid:pk>/', SubscriptionDetailView.as_view(), name='subscription-detail'),
    path('revenue/', RevenueSummaryView.as_view(), name='revenue-summary'),
    
    # Service management
    path('services/', PlanServiceListCreateView.as_view(), name='service-list'),
    path('services/<uuid:pk>/', PlanServiceDetailView.as_view(), name='service-detail'),
    path('services/by-plan/<uuid:plan_id>/', PlanServicesByPlanView.as_view(), name='plan-services'),
    
    # Mapping management
    path('service-mappings/', PlanServiceMappingListCreateView.as_view(), name='mapping-list'),
    path('service-mappings/<uuid:pk>/', PlanServiceMappingDetailView.as_view(), name='mapping-detail'),

    # Add-on request flow (MasterAdmin)
    path('my-addons/', MyAddonsView.as_view(), name='my-addons'),
    path('addon-requests/', AddOnRequestListCreateView.as_view(), name='addon-request-list'),

    # Add-on management (SuperAdmin)
    path('addon-requests/all/', AllAddOnRequestsView.as_view(), name='addon-requests-all'),
    path('addon-requests/<uuid:pk>/approve/', AddOnRequestApproveView.as_view(), name='addon-request-approve'),
    path('addon-requests/<uuid:pk>/reject/', AddOnRequestRejectView.as_view(), name='addon-request-reject'),
]
