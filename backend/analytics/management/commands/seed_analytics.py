from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from analytics.models import DailyMetricSnapshot
from tenants.models import Client
from properties.models import Unit, Lease
from maintenance.models import MaintenanceRequest
from django_tenants.utils import schema_context
import random

class Command(BaseCommand):
    help = 'Seeds historical analytics data for the Super Admin dashboard'

    def handle(self, *args, **options):
        self.stdout.write("Starting analytics seeding for the last 30 days...")
        
        # We want to seed data for the 'public' schema (Super Admin)
        schema = 'public'
        
        today = timezone.now().date()
        
        # Generate 30 days of data
        for i in range(30):
            target_date = today - timedelta(days=(29 - i))
            
            # Since aggregating across all tenants dynamically might be complex or slow if there's no data,
            # we will aggregate what we can and mock the rest to show a realistic trend.
            
            total_revenue = 0
            total_units = 0
            occupied_units = 0
            open_maintenance = 0
            
            # Iterate through all tenants to aggregate real data
            tenants = Client.objects.exclude(schema_name='public')
            
            for tenant in tenants:
                with schema_context(tenant.schema_name):
                    try:
                        # This works if models exist in the tenant schema
                        total_units += Unit.objects.count()
                        occupied_units += Unit.objects.filter(status='occupied').count()
                        open_maintenance += MaintenanceRequest.objects.filter(status='open').count()
                        
                        # Add up the rent of active leases
                        # We use simple aggregation or fallback
                        revenue = 0
                        leases = Lease.objects.filter(status='active')
                        for lease in leases:
                            revenue += float(lease.monthly_rent)
                        total_revenue += revenue
                        
                    except Exception as e:
                        # If a tenant hasn't been fully migrated or apps are missing, skip safely
                        pass
            
            # If no real data exists across tenants, let's create a realistic mock trend
            # so the dashboard looks good. We add a slight upward trend.
            if total_units == 0:
                base_units = 150 + (i * 2)
                total_units = base_units
                occupied_units = int(base_units * (0.80 + (random.random() * 0.1))) # 80-90% occupancy
                open_maintenance = random.randint(5, 15)
                total_revenue = occupied_units * 15000 # Assume avg rent 15000 INR
            
            # Calculate final metrics
            occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0
            
            # Generate a realistic payment collection rate (between 85% and 98%)
            payment_rate = random.uniform(85.0, 98.0)
            
            metrics = {
                'total_revenue': total_revenue,
                'payment_collection_rate': payment_rate,
                'active_residents': occupied_units * random.randint(2, 4), # Assume 2-4 residents per occupied unit
                'total_units': total_units,
                'occupancy_rate': occupancy_rate,
                'open_maintenance_requests': open_maintenance
            }
            
            for key, value in metrics.items():
                DailyMetricSnapshot.objects.update_or_create(
                    tenant_schema=schema,
                    date=target_date,
                    metric_key=key,
                    defaults={'metric_value': float(value)}
                )
                
        self.stdout.write(self.style.SUCCESS('Successfully seeded 30 days of analytics data for the public schema!'))
