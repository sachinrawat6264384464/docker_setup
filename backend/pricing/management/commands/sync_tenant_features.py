from django.core.management.base import BaseCommand
from tenants.models import Client
from pricing.models import PricingPlan, PlanServiceMapping

class Command(BaseCommand):
    help = 'Sync existing tenant feature dictionaries with their pricing plans and current active add-ons'

    def add_arguments(self, parser):
        parser.add_argument('--schema', type=str, help='Sync feature mapping for a specific tenant schema name only')
        parser.add_argument('--reset', action='store_true', help='Force reset features to plan defaults, disabling all un-included addons')

    def handle(self, *args, **options):
        schema_name = options.get('schema')
        force_reset = options.get('reset')

        # Define map between pricing services and tenant JSON feature keys
        SERVICE_TO_FEATURE_KEY = {
            'Dashboard': 'dashboard',
            'Communities': 'communities',
            'Blocks/Sectors': 'buildings',
            'Units': 'units',
            'People Hub': 'people_hub',
            'Facility Managers': 'facility_managers',
            'Senior Hub Managers': 'senior_managers',
            'Rental Hub': 'leases',
            'Documents': 'documents',
            'Bulk Upload': 'bulk_upload',
            'Bulk Export': 'bulk_export',
            'Payments': 'payments',
            'Maintenance': 'maintenance',
            'Amenities': 'amenities',
            'Security': 'security',
            'Vendors': 'vendors',
            'Calendar': 'calendar',
            'Message Center': 'communication',
            'Support Center': 'support',
            'Developer Portal': 'developer_portal',
            'Reports': 'reports',
        }

        # Filter tenants
        tenants = Client.objects.exclude(schema_name='public')
        if schema_name:
            tenants = tenants.filter(schema_name=schema_name)
            if not tenants.exists():
                self.stdout.write(self.style.ERROR(f"Tenant schema '{schema_name}' does not exist."))
                return

        self.stdout.write(self.style.NOTICE(f"Syncing features for {tenants.count()} tenant(s)..."))

        for tenant in tenants:
            plan_slug = tenant.subscription_plan or 'basic'
            plan = PricingPlan.objects.filter(slug__iexact=plan_slug).first()
            if not plan:
                self.stdout.write(self.style.WARNING(f"Tenant '{tenant.name}' ({tenant.schema_name}) has unknown plan '{plan_slug}'. Defaulting to basic."))
                plan = PricingPlan.objects.filter(slug='basic').first()

            # Initialize base features (all services default to False)
            target_features = {key: False for key in SERVICE_TO_FEATURE_KEY.values()}
            # Core system features are always enabled
            target_features.update({
                'property_management': True,
                'unit_database': True,
                'member_portal': True,
                'billing_engine': True,
                'communication_hub': True,
                'dashboard': True,
            })

            # Check mappings
            if plan:
                mappings = PlanServiceMapping.objects.filter(plan=plan)
                for m in mappings:
                    f_key = SERVICE_TO_FEATURE_KEY.get(m.service.name)
                    if f_key:
                        if m.is_included:
                            target_features[f_key] = True
                        else:
                            # It is an add-on. If force_reset is not set, preserve if already enabled
                            if not force_reset and tenant.features and tenant.features.get(f_key) is True:
                                target_features[f_key] = True
                            else:
                                target_features[f_key] = False

            # Update tenant features
            tenant.features = target_features
            tenant.save()
            self.stdout.write(self.style.SUCCESS(f"Successfully synced features for '{tenant.name}' ({tenant.schema_name}) on plan '{plan_slug}'."))

        self.stdout.write(self.style.SUCCESS("All feature synchronizations completed!"))
