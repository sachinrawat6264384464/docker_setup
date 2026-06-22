from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count
from django.db.utils import OperationalError, ProgrammingError
from .models import AnalyticsEvent, DailyMetricSnapshot
from .serializers import AnalyticsEventSerializer, DailyMetricSnapshotSerializer
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema


class TenantAnalyticsSummaryView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AnalyticsEventSerializer

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        days = int(request.query_params.get('days', 30))
        since = timezone.now() - timedelta(days=days)
        try:
            events = AnalyticsEvent.objects.filter(tenant_schema=schema, created_at__gte=since)
            total_events = events.count()
        except (OperationalError, ProgrammingError):
            return Response({'total_events': 0, 'events_by_type': []})

        summary = {
            'total_events': total_events,
            'logins': events.filter(event_type='user_logged_in').count(),
            'invoices_paid': events.filter(event_type='invoice_paid').count(),
            'tickets_created': events.filter(event_type='ticket_created').count(),
            'tickets_resolved': events.filter(event_type='ticket_resolved').count(),
            'amenity_bookings': events.filter(event_type='amenity_booked').count(),
            'messages_sent': events.filter(event_type='message_sent').count(),
            'events_by_type': list(
                events.values('event_type').annotate(count=Count('id')).order_by('-count')[:20]
            ),
        }
        return Response(summary)


class RecentActivityFeedView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AnalyticsEventSerializer

    @extend_schema(responses=AnalyticsEventSerializer(many=True))
    def get(self, request):
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', '')
        try:
            events = AnalyticsEvent.objects.filter(tenant_schema=schema).order_by('-created_at')[:50]
            return Response(AnalyticsEventSerializer(events, many=True).data)
        except (OperationalError, ProgrammingError):
            return Response([])


class DailyMetricsView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DailyMetricSnapshotSerializer

    @extend_schema(responses=DailyMetricSnapshotSerializer(many=True))
    def get(self, request):
        """Returns pivoted data: one object per date containing all metrics"""
        import logging
        from django.db.models.functions import TruncDate
        from django.db.models import Sum
        from django_tenants.utils import schema_context
        from tenants.models import Client, PlatformInvoice
        from payments.models import Payment, Invoice
        from properties.models import Unit
        from accounts.models import User
        from maintenance.models import MaintenanceRequest
        from decimal import Decimal

        logger = logging.getLogger(__name__)

        schema = getattr(getattr(request, 'tenant', None), 'schema_name', 'public')
        days = int(request.query_params.get('days', 30))
        since = (timezone.now() - timedelta(days=days)).date()
        today = timezone.now().date()

        try:
            if schema == 'public':
                # Superadmin view - aggregate across all active schemas
                tenants = Client.objects.filter(is_active=True).exclude(schema_name='public')
                # Count total organizations dynamically (both active and inactive)
                total_orgs = Client.objects.exclude(schema_name='public').count()
            else:
                # Tenant view - only use the current schema
                tenants = []
                total_orgs = 0

            # Initialize pivoted data dictionary for the dates
            pivoted_data = {}
            for x in range((today - since).days + 1):
                d = since + timedelta(days=x)
                d_str = d.isoformat()
                pivoted_data[d_str] = {
                    'date': d_str, 
                    'tenant_schema': schema,
                    'total_revenue': 0.0,
                    'payment_collection_rate': 100.0,
                    'active_residents': 0,
                    'total_units': 0,
                    'total_organizations': total_orgs,
                    'occupancy_rate': 0.0,
                    'open_maintenance_requests': 0
                }

            # Helper lists to compute totals
            total_occupied_units = 0
            total_units = 0
            total_billed = Decimal('0.00')
            total_collected = Decimal('0.00')
            total_residents = 0
            total_open_maintenance = 0

            if schema == 'public':
                # 1. Total revenue by date from paid/verified PlatformInvoices in the public schema
                platform_revenues = PlatformInvoice.objects.filter(
                    status__in=['paid', 'verified'],
                    paid_at__isnull=False,
                    paid_at__date__gte=since
                ).annotate(date_only=TruncDate('paid_at')) \
                 .values('date_only') \
                 .annotate(daily_sum=Sum('amount'))

                for entry in platform_revenues:
                    entry_date_str = entry['date_only'].isoformat()
                    if entry_date_str in pivoted_data:
                        pivoted_data[entry_date_str]['total_revenue'] += float(entry['daily_sum'] or 0.0)

                # 2. Latest/Current metrics from tenant schemas
                for tenant in tenants:
                    try:
                        with schema_context(tenant.schema_name):
                            t_units = Unit.objects.filter(is_active=True).count()
                            t_occupied = Unit.objects.filter(is_active=True, is_occupied=True).count()
                            t_residents = User.objects.filter(role__in=['master_admin', 'masteradmin'], is_active=True).count()
                            t_open_maint = MaintenanceRequest.objects.exclude(status__in=['completed', 'cancelled']).count()

                            t_invoices = Invoice.objects.filter(created_at__date__gte=since).exclude(status='cancelled')
                            t_billed = t_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
                            t_collected = t_invoices.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')

                            total_units += t_units
                            total_occupied_units += t_occupied
                            total_residents += t_residents
                            total_open_maintenance += t_open_maint
                            total_billed += t_billed
                            total_collected += t_collected
                    except Exception as e:
                        logger.error(f"Error computing analytics for schema {tenant.schema_name}: {e}")
            else:
                # Tenant specific calculations (resident payments and units in tenant schema)
                try:
                    daily_revenues = Payment.objects.filter(
                        status='completed',
                        created_at__date__gte=since
                    ).annotate(date_only=TruncDate('created_at')) \
                     .values('date_only') \
                     .annotate(daily_sum=Sum('amount'))
                    
                    for entry in daily_revenues:
                        entry_date_str = entry['date_only'].isoformat()
                        if entry_date_str in pivoted_data:
                            pivoted_data[entry_date_str]['total_revenue'] = float(entry['daily_sum'] or 0.0)

                    total_units = Unit.objects.filter(is_active=True).count()
                    total_occupied_units = Unit.objects.filter(is_active=True, is_occupied=True).count()
                    total_residents = User.objects.filter(role__in=['master_admin', 'masteradmin'], is_active=True).count()
                    total_open_maintenance = MaintenanceRequest.objects.exclude(status__in=['completed', 'cancelled']).count()

                    t_invoices = Invoice.objects.filter(created_at__date__gte=since).exclude(status='cancelled')
                    total_billed = t_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
                    total_collected = t_invoices.aggregate(Sum('amount_paid'))['amount_paid__sum'] or Decimal('0.00')
                except Exception as e:
                    logger.error(f"Error computing analytics for current schema {schema}: {e}")

            # Calculate final rate/percentage values
            global_occupancy = (total_occupied_units / total_units * 100) if total_units > 0 else 0.0
            global_collection_rate = (float(total_collected) / float(total_billed) * 100) if total_billed > 0 else 100.0

            # Fill state variables for all date snapshots
            for d_str in pivoted_data:
                pivoted_data[d_str]['active_residents'] = total_residents
                pivoted_data[d_str]['total_units'] = total_units
                pivoted_data[d_str]['total_organizations'] = total_orgs
                pivoted_data[d_str]['occupancy_rate'] = global_occupancy
                pivoted_data[d_str]['payment_collection_rate'] = global_collection_rate
                pivoted_data[d_str]['open_maintenance_requests'] = total_open_maintenance

            return Response(list(pivoted_data.values()))
        except (OperationalError, ProgrammingError) as e:
            logger.error(f"Operational/Programming error in DailyMetricsView: {e}")
            return Response([])

    def post(self, request):
        """Allows seeding multiple metrics for a date via Postman"""
        schema = getattr(getattr(request, 'tenant', None), 'schema_name', 'public')
        date_val = request.data.get('date', timezone.now().date().isoformat())
        metrics = request.data.get('metrics', {})
        
        results = []
        for key, value in metrics.items():
            snap, created = DailyMetricSnapshot.objects.update_or_create(
                tenant_schema=schema,
                date=date_val,
                metric_key=key,
                defaults={'metric_value': float(value)}
            )
            results.append({
                'id': snap.id,
                'metric_key': key,
                'metric_value': value
            })
            
        return Response({
            "status": "success",
            "message": f"Updated {len(results)} metrics for {date_val} in schema '{schema}'",
            "data": results
        })
