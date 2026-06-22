from django.core.management.base import BaseCommand
from pricing.models import PricingPlan, PlanService, PlanServiceMapping
import uuid

class Command(BaseCommand):
    help = 'Seed pricing plans and services'

    def handle(self, *args, **options):
        # 1. Keep only Basic, Premium, Enterprise
        allowed_slugs = ['basic', 'premium', 'enterprise']
        PricingPlan.objects.exclude(slug__in=allowed_slugs).delete()
        self.stdout.write(self.style.WARNING("Deleted extra plans (Starter, Growth, etc.)"))

        # 2. Sync Plans
        plans_data = [
            {'name': 'Basic', 'slug': 'basic', 'monthly_price': 2499, 'annual_price': 24990},
            {'name': 'Premium', 'slug': 'premium', 'monthly_price': 5999, 'annual_price': 59990},
            {'name': 'Enterprise', 'slug': 'enterprise', 'monthly_price': 14999, 'annual_price': 149990},
        ]
        
        plans = {}
        for p in plans_data:
            plan, _ = PricingPlan.objects.update_or_create(
                slug=p['slug'],
                defaults={'name': p['name'], 'monthly_price': p['monthly_price'], 'annual_price': p['annual_price'], 'is_active': True}
            )
            plans[p['slug']] = plan

        # 3. Create Services (Exact Sidebar Items)
        services_data = [
            # Core (Included in Basic)
            {'name': 'Dashboard', 'desc': 'Organization overview', 'price': 0},
            {'name': 'Communities', 'desc': 'Manage communities/projects', 'price': 0},
            {'name': 'Blocks/Sectors', 'desc': 'Manage blocks and sectors', 'price': 0},
            {'name': 'Units', 'desc': 'Manage individual units', 'price': 0},
            {'name': 'People Hub', 'desc': 'Resident and owner management', 'price': 0},
            {'name': 'Facility Managers', 'desc': 'Manage facility staff', 'price': 0},
            {'name': 'Documents', 'desc': 'Document storage and management', 'price': 0},
            {'name': 'Payments', 'desc': 'Fee collection and invoicing', 'price': 0},
            {'name': 'Maintenance', 'desc': 'Service requests and tracking', 'price': 0},
            
            # Management (Premium)
            {'name': 'Rental Hub', 'desc': 'Manage rentals and tenants', 'price': 799},
            {'name': 'Reports', 'desc': 'Advanced analytics and exports', 'price': 1499},
            
            # Advanced (Enterprise)
            {'name': 'Amenities', 'desc': 'Clubhouse and facility booking', 'price': 799},
            {'name': 'Security', 'desc': 'Visitor and gate management', 'price': 1200},
            {'name': 'Vendors', 'desc': 'Vendor and AMC management', 'price': 599},
            {'name': 'Message Center', 'desc': 'Broadcast messages and alerts', 'price': 499},
            {'name': 'Developer Portal', 'desc': 'API and integration access', 'price': 5000},
            {'name': 'Senior Hub Managers', 'desc': 'Higher-level staff management', 'price': 999},
            {'name': 'Support Center', 'desc': 'Priority support access', 'price': 1000},
        ]

        services = {}
        for s in services_data:
            svc, _ = PlanService.objects.update_or_create(
                name=s['name'],
                defaults={'description': s['desc'], 'price_per_unit': s['price'], 'is_active': True}
            )
            services[s['name']] = svc

        # 4. Clear old mappings and re-map
        PlanServiceMapping.objects.all().delete()
        mappings = [
            # Basic: Included
            ('basic', 'Dashboard', True),
            ('basic', 'Communities', True),
            ('basic', 'Blocks/Sectors', True),
            ('basic', 'Units', True),
            ('basic', 'People Hub', True),
            ('basic', 'Facility Managers', True),
            ('basic', 'Documents', True),
            ('basic', 'Payments', True),
            ('basic', 'Maintenance', True),
            # Basic: Add-ons (Tickable)
            ('basic', 'Rental Hub', False),
            ('basic', 'Reports', False),

            # Premium: Included
            ('premium', 'Dashboard', True),
            ('premium', 'Communities', True),
            ('premium', 'Blocks/Sectors', True),
            ('premium', 'Units', True),
            ('premium', 'People Hub', True),
            ('premium', 'Facility Managers', True),
            ('premium', 'Documents', True),
            ('premium', 'Payments', True),
            ('premium', 'Maintenance', True),
            ('premium', 'Rental Hub', True),
            ('premium', 'Reports', True),
            # Premium: Add-ons (Tickable)
            ('premium', 'Amenities', False),
            ('premium', 'Security', False),
            ('premium', 'Vendors', False),
            ('premium', 'Message Center', False),

            # Enterprise: Everything Included
            ('enterprise', 'Dashboard', True),
            ('enterprise', 'Communities', True),
            ('enterprise', 'Blocks/Sectors', True),
            ('enterprise', 'Units', True),
            ('enterprise', 'People Hub', True),
            ('enterprise', 'Facility Managers', True),
            ('enterprise', 'Rental Hub', True),
            ('enterprise', 'Documents', True),
            ('enterprise', 'Payments', True),
            ('enterprise', 'Maintenance', True),
            ('enterprise', 'Reports', True),
            ('enterprise', 'Amenities', True),
            ('enterprise', 'Security', True),
            ('enterprise', 'Vendors', True),
            ('enterprise', 'Message Center', True),
            ('enterprise', 'Developer Portal', True),
            ('enterprise', 'Senior Hub Managers', True),
            ('enterprise', 'Support Center', True),
        ]

        for plan_slug, svc_name, is_inc in mappings:
            plan = plans.get(plan_slug)
            svc = services.get(svc_name)
            if plan and svc:
                PlanServiceMapping.objects.create(plan=plan, service=svc, is_included=is_inc)

        self.stdout.write(self.style.SUCCESS("Successfully synced Plans with Included and Tickable Add-on services!"))
