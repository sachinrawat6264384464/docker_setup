from django.core.management.base import BaseCommand
from pricing.models import PricingPlan, PlanService, PlanServiceMapping
import uuid

class Command(BaseCommand):
    help = 'Seed pricing plans and services'

    def handle(self, *args, **options):
        # 1. Create Plans if missing
        plans_data = [
            {'name': 'Starter', 'slug': 'starter', 'monthly_price': 2499, 'annual_price': 24990},
            {'name': 'Growth', 'slug': 'growth', 'monthly_price': 5999, 'annual_price': 59990},
            {'name': 'Enterprise', 'slug': 'enterprise', 'monthly_price': 14999, 'annual_price': 149990},
        ]
        
        plans = {}
        for p in plans_data:
            plan, created = PricingPlan.objects.get_or_create(
                slug=p['slug'],
                defaults={'name': p['name'], 'monthly_price': p['monthly_price'], 'annual_price': p['annual_price'], 'is_active': True}
            )
            plans[p['slug']] = plan
            if created: self.stdout.write(f"Created plan: {p['name']}")

        # 2. Create Services
        services_data = [
            {'name': 'Dashboard Analytics', 'description': 'Basic dashboard views'},
            {'name': 'Property Management', 'description': 'Manage buildings and units'},
            {'name': 'User Management', 'description': 'Staff and resident accounts'},
            {'name': 'Billing & Payments', 'description': 'Collect maintenance fees'},
            {'name': 'Advanced Reporting', 'description': 'Custom report generation'},
            {'name': 'API Access', 'description': 'Developer portal access'},
        ]

        services = {}
        for s in services_data:
            svc, created = PlanService.objects.get_or_create(
                name=s['name'],
                defaults={'description': s['description'], 'is_active': True}
            )
            services[s['name']] = svc
            if created: self.stdout.write(f"Created service: {s['name']}")

        # 3. Map Services to Plans
        mappings = [
            # Basic gets first 3
            ('basic', 'Dashboard Analytics'),
            ('basic', 'Property Management'),
            ('basic', 'User Management'),
            # Premium gets 4
            ('premium', 'Dashboard Analytics'),
            ('premium', 'Property Management'),
            ('premium', 'User Management'),
            ('premium', 'Billing & Payments'),
            # Enterprise gets all
            ('enterprise', 'Dashboard Analytics'),
            ('enterprise', 'Property Management'),
            ('enterprise', 'User Management'),
            ('enterprise', 'Billing & Payments'),
            ('enterprise', 'Advanced Reporting'),
            ('enterprise', 'API Access'),
        ]

        for plan_slug, svc_name in mappings:
            plan = plans.get(plan_slug)
            svc = services.get(svc_name)
            if plan and svc:
                PlanServiceMapping.objects.get_or_create(
                    plan=plan,
                    service=svc,
                    defaults={'is_included': True}
                )

        self.stdout.write(self.style.SUCCESS("Successfully seeded plans and services!"))
