from django.urls import path
from .views import TenantAnalyticsSummaryView, RecentActivityFeedView, DailyMetricsView

urlpatterns = [
    path('summary/', TenantAnalyticsSummaryView.as_view(), name='analytics-summary'),
    path('feed/', RecentActivityFeedView.as_view(), name='analytics-feed'),
    path('daily/', DailyMetricsView.as_view(), name='analytics-daily'),
    path('snapshots/', DailyMetricsView.as_view(), name='analytics-snapshots'),
]
