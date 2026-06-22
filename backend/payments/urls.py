# payments/urls.py - UPDATE YOUR EXISTING URLS WITH THESE ADDITIONS

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'gateways', views.PaymentGatewayViewSet, basename='payment-gateway')
router.register(r'invoices', views.InvoiceViewSet, basename='invoice')
router.register(r'payments', views.PaymentViewSet, basename='payment')
router.register(r'payment-methods', views.PaymentMethodViewSet, basename='payment-method')
router.register(r'refunds', views.RefundViewSet, basename='refund')
router.register(r'payment-plans', views.PaymentPlanViewSet, basename='payment-plan')
router.register(r'reminders', views.PaymentReminderViewSet, basename='payment-reminder')
router.register(r'installments', views.InstallmentViewSet, basename='installment')
router.register(r'transactions', views.TransactionViewSet, basename='transaction')

# AUTO-PAY ROUTES
router.register(r'autopay/enrollments', views.AutoPayEnrollmentViewSet, basename='autopay-enrollment')
router.register(r'autopay/logs', views.AutoPaymentLogViewSet, basename='autopay-log')
router.register(r'recurring-invoices', views.RecurringInvoiceViewSet, basename='recurring-invoice')

urlpatterns = [
    path('dashboard/', views.payment_dashboard, name='payment-dashboard'),
    
    # Webhook endpoints
    path('webhooks/razorpay/', views.webhook_razorpay, name='webhook-razorpay'),
    path('webhooks/stripe/', views.webhook_stripe, name='webhook-stripe'),
    
    path('', include(router.urls)),
]