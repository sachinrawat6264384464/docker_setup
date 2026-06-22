from django.core.management.base import BaseCommand
from pricing.models import PricingPlan, PlanService, PlanServiceMapping
from decimal import Decimal

class Command(BaseCommand):
    help = 'Seeds Pricing Plans and Services'

    def handle(self, *args, **options):
        # 1. Create Services
        services_data = [
            {'name': 'Basic Maintenance', 'description': 'Track facility issues', 'price': 0},
            {'name': 'Resident Directory', 'description': 'Directory of all residents', 'price': 0},
            {'name': 'Advanced Analytics', 'description': 'Detailed reports and trends', 'price': 1499},
            {'name': 'Visitor Management', 'description': 'Digital logs for visitors', 'price': 999},
            {'name': 'Bulk Emailing', 'description': 'Send mass announcements', 'price': 499},
            {'name': 'Payment Gateway Integration', 'description': 'Online fee collection', 'price': 1999},
        ]
        
        services = {}
        for s_info in services_data:
            service, _ = PlanService.objects.get_or_create(
                name=s_info['name'],
                defaults={
                    'description': s_info['description'],
                    'price_per_unit': Decimal(s_info['price']),
                    'is_active': True
                }
            )
            services[s_info['name']] = service
            self.stdout.write(self.style.SUCCESS(f"Service ensured: {service.name}"))

        # 2. Create Plans
        plans_data = [
            {
                'name': 'Starter', 'slug': 'starter', 'monthly': 2499, 'annual': 24990, 
                'units': 50, 'managers': 2, 'order': 1, 'color': '#3B82F6',
                'included': ['Basic Maintenance', 'Resident Directory'],
                'addons': ['Bulk Emailing']
            },
            {
                'name': 'Growth', 'slug': 'growth', 'monthly': 5999, 'annual': 59990, 
                'units': 200, 'managers': 5, 'order': 2, 'color': '#8B5CF6',
                'included': ['Basic Maintenance', 'Resident Directory', 'Visitor Management', 'Bulk Emailing'],
                'addons': ['Advanced Analytics']
            },
            {
                'name': 'Enterprise', 'slug': 'enterprise', 'monthly': 14999, 'annual': 149990, 
                'units': 1000, 'managers': 20, 'order': 3, 'color': '#14213D',
                'included': ['Basic Maintenance', 'Resident Directory', 'Visitor Management', 'Bulk Emailing', 'Advanced Analytics', 'Payment Gateway Integration'],
                'addons': []
            },
        ]

        for p_info in plans_data:
            plan, _ = PricingPlan.objects.update_or_create(
                slug=p_info['slug'],
                defaults={
                    'name': p_info['name'],
                    'monthly_price': Decimal(p_info['monthly']),
                    'annual_price': Decimal(p_info['annual']),
                    'unit_limit': p_info['units'],
                    'manager_limit': p_info['managers'],
                    'display_order': p_info['order'],
                    'color': p_info['color'],
                    'is_active': True,
                    'tagline': f"Perfect for {p_info['name']} societies"
                }
            )
            
            # 3. Create Mappings
            for s_name in p_info['included']:
                PlanServiceMapping.objects.get_or_create(plan=plan, service=services[s_name], defaults={'is_included': True})
            
            for s_name in p_info['addons']:
                PlanServiceMapping.objects.get_or_create(plan=plan, service=services[s_name], defaults={'is_included': False})

            self.stdout.write(self.style.SUCCESS(f"Plan ensured: {plan.name}"))

        self.stdout.write(self.style.SUCCESS("Successfully seeded pricing plans and services."))
