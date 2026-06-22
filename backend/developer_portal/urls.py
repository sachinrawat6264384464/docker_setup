from django.urls import path
from .views import (APIKeyListView, APIKeyCreateView, APIKeyRevokeView,
                    WebhookEndpointView, WebhookDeliveryView,
                    APIGuideListView, APIGuideDetailView, APIChangelogView)

urlpatterns = [
    path('keys/', APIKeyListView.as_view(), name='api-keys'),
    path('keys/create/', APIKeyCreateView.as_view(), name='api-key-create'),
    path('keys/<uuid:pk>/revoke/', APIKeyRevokeView.as_view(), name='api-key-revoke'),
    path('webhooks/', WebhookEndpointView.as_view(), name='webhooks'),
    path('webhooks/<uuid:pk>/deliveries/', WebhookDeliveryView.as_view(), name='webhook-deliveries'),
    path('guides/', APIGuideListView.as_view(), name='api-guides'),
    path('guides/<slug:slug>/', APIGuideDetailView.as_view(), name='api-guide-detail'),
    path('changelog/', APIChangelogView.as_view(), name='api-changelog'),
]
