from django.core.management.base import BaseCommand
from pricing.models import PricingPlan, PlanFeature
from django.utils.text import slugify

class Command(BaseCommand):
    help = 'Seeds the database with default HOAConnect Hub Pricing Plans in USD'

    def handle(self, *args, **kwargs):
        # Define the plans
        plans_data = [
            {
                'name': 'Starter',
                'description': 'For small HOAs and residential communities',
                'tagline': 'Essential tools to manage your property',
                'monthly_price': 49.00, # USD
                'annual_price': 399.00, # USD
                'unit_limit': 50,
                'manager_limit': 2,
                'display_order': 1,
                'color': '#10B981', # Green
            },
            {
                'name': 'Growth',
                'description': 'For mid-size communities needing more',
                'tagline': 'Everything you need to grow your society',
                'monthly_price': 149.00, # USD
                'annual_price': 1199.00, # USD
                'unit_limit': 200,
                'manager_limit': 10,
                'is_featured': True,
                'display_order': 2,
                'color': '#3B82F6', # Blue
            },
            {
                'name': 'Enterprise',
                'description': 'For large HOAs and property management firms',
                'tagline': 'Custom solutions for complex needs',
                'monthly_price': None, # Custom pricing
                'annual_price': None,
                'unit_limit': None, # Unlimited
                'manager_limit': None, # Unlimited
                'is_custom_pricing': True,
                'display_order': 3,
                'color': '#8B5CF6', # Purple
            }
        ]

        # Shared/Common features list
        # format: (Feature Name, Feature Key)
        features_list = [
            ('Properties & Units', 'properties'),
            ('Resident Portal', 'resident_portal'),
            ('Basic Maintenance', 'maintenance_basic'),
            ('Basic Payments', 'payments_basic'),
            ('Document Management', 'documents'),
            ('Managers', 'managers'),
            ('Email Support', 'support_email'),
            ('Amenities Booking', 'amenities'),
            ('Advanced Payments', 'payments_advanced'),
            ('Communication Suite', 'communication'),
            ('Parking Management', 'parking'),
            ('Visitor Management', 'visitors'),
            ('Vendor Management', 'vendors'),
            ('Analytics Dashboard', 'analytics'),
            ('Priority Support', 'support_priority'),
            ('White-labeling', 'whitelabel'),
            ('Custom Domain', 'custom_domain'),
            ('API Access', 'api_access'),
            ('Bulk SMS', 'bulk_sms'),
            ('Mobile App', 'mobile_app'),
            ('Dedicated Account Manager', 'account_manager'),
            ('SLA', 'sla'),
        ]

        # Plan-Feature inclusion mapping
        plan_inclusions = {
            'Starter': ['properties', 'resident_portal', 'maintenance_basic', 'payments_basic', 'documents', 'managers', 'support_email'],
            'Growth': ['properties', 'resident_portal', 'maintenance_basic', 'payments_basic', 'documents', 'managers', 'support_email', 'amenities', 'payments_advanced', 'communication', 'parking', 'visitors', 'vendors', 'analytics'],
            'Enterprise': [f[1] for f in features_list] # All features included
        }

        self.stdout.write("Deleting existing plans/features to reseed...")
        PlanFeature.objects.all().delete()
        PricingPlan.objects.all().delete()

        self.stdout.write("Seeding Pricing Plans...")
        
        for data in plans_data:
            name = data['name']
            
            # Create or update the plan
            plan = PricingPlan.objects.create(
                slug=slugify(name),
                **data
            )
            self.stdout.write(self.style.SUCCESS(f"Created Plan: {name}"))

            # Create features for this plan
            order = 1
            for feature_name, feature_key in features_list:
                is_included = feature_key in plan_inclusions[name]
                
                # Setup specific limits text for display
                limit_value = ''
                if feature_key == 'properties':
                    limit_value = f"Up to {data['unit_limit']} units" if data['unit_limit'] else "Unlimited"
                elif feature_key == 'managers':
                    limit_value = f"Up to {data['manager_limit']} managers" if data['manager_limit'] else "Unlimited"
                
                PlanFeature.objects.create(
                    plan=plan,
                    feature_name=feature_name,
                    feature_key=feature_key,
                    is_included=is_included,
                    limit_value=limit_value,
                    display_order=order
                )
                order += 1
                
        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
