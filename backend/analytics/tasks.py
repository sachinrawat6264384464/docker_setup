from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import AnalyticsEvent, DailyMetricSnapshot


@shared_task
def compute_daily_snapshots():
    """Run nightly via Celery Beat to precompute dashboard metrics."""
    yesterday = (timezone.now() - timedelta(days=1)).date()
    schemas = AnalyticsEvent.objects.values_list('tenant_schema', flat=True).distinct()

    for schema in schemas:
        events = AnalyticsEvent.objects.filter(
            tenant_schema=schema,
            created_at__date=yesterday,
        )
        metrics = {
            'total_events': events.count(),
            'logins': events.filter(event_type='user_logged_in').count(),
            'invoices_paid': events.filter(event_type='invoice_paid').count(),
            'tickets_created': events.filter(event_type='ticket_created').count(),
            'tickets_resolved': events.filter(event_type='ticket_resolved').count(),
            'messages_sent': events.filter(event_type='message_sent').count(),
            'amenity_bookings': events.filter(event_type='amenity_booked').count(),
        }
        for key, value in metrics.items():
            DailyMetricSnapshot.objects.update_or_create(
                tenant_schema=schema,
                date=yesterday,
                metric_key=key,
                defaults={'metric_value': value},
            )
