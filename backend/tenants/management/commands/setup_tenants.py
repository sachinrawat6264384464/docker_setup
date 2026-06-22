# tenants/management/commands/setup_tenants.py
"""
Management command to setup initial tenant data and create first tenant
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from tenants.models import Client, Domain, TenantSettings, TenantSubscription
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Setup initial tenant configuration and create first tenant'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--create-demo',
            action='store_true',
            help='Create a demo tenant for testing',
        )
        parser.add_argument(
            '--tenant-name',
            type=str,
            help='Name of the tenant to create',
        )
        parser.add_argument(
            '--domain',
            type=str,
            help='Domain for the tenant (e.g., demo.localhost:8000)',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Contact email for the tenant',
        )
        parser.add_argument(
            '--plan',
            type=str,
            choices=['basic', 'premium', 'enterprise'],
            default='basic',
            help='Subscription plan (default: basic)',
        )
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('🚀 TENANT SETUP WIZARD'))
        self.stdout.write(self.style.SUCCESS('='*70 + '\n'))
        
        # Check if creating demo or custom tenant
        if options['create_demo']:
            self.create_demo_tenant()
        elif options['tenant_name'] and options['domain'] and options['email']:
            self.create_custom_tenant(
                name=options['tenant_name'],
                domain=options['domain'],
                email=options['email'],
                plan=options['plan']
            )
        else:
            self.interactive_setup()
    
    def interactive_setup(self):
        """Interactive tenant creation"""
        self.stdout.write(self.style.WARNING('\n📋 Let\'s create your first tenant!\n'))
        
        # Get tenant details
        name = input('Enter company name: ').strip()
        if not name:
            raise CommandError('❌ Company name is required')
        
        domain = input('Enter domain (e.g., abc.localhost:8000): ').strip()
        if not domain:
            raise CommandError('❌ Domain is required')
        
        email = input('Enter contact email: ').strip()
        if not email:
            raise CommandError('❌ Email is required')
        
        phone = input('Enter contact phone: ').strip() or '+91-0000000000'
        address = input('Enter address: ').strip() or 'Not provided'
        
        # Choose subscription plan
        self.stdout.write('\n💎 Choose subscription plan:')
        self.stdout.write('  1. Basic (₹999/month)')
        self.stdout.write('  2. Premium (₹2,999/month)')
        self.stdout.write('  3. Enterprise (₹9,999/month)')
        
        plan_choice = input('Enter choice (1-3, default: 1): ').strip() or '1'
        plan_map = {'1': 'basic', '2': 'premium', '3': 'enterprise'}
        plan = plan_map.get(plan_choice, 'basic')
        
        # Create tenant
        self.create_custom_tenant(name, domain, email, phone, address, plan)
    
    @transaction.atomic
    def create_custom_tenant(self, name, domain, email, phone=None, address=None, plan='basic'):
        """Create a custom tenant with all necessary setup"""
        try:
            self.stdout.write(self.style.WARNING(f'\n⏳ Creating tenant: {name}...'))
            
            # Generate schema name
            safe_name = name.lower().replace(' ', '_').replace('-', '_')
            safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
            schema_name = f"tenant_{safe_name}"
            
            # Ensure uniqueness
            counter = 1
            original_schema = schema_name
            while Client.objects.filter(schema_name=schema_name).exists():
                schema_name = f"{original_schema}_{counter}"
                counter += 1
            
            # Get default features based on plan
            features = self.get_default_features(plan)
            
            # Create or update tenant
            tenant, created = Client.objects.update_or_create(
                schema_name=schema_name,
                defaults={
                    'name': name,
                    'contact_email': email,
                    'contact_phone': phone or '+91-0000000000',
                    'address': address or 'Not provided',
                    'subscription_plan': plan,
                    'features': features,
                    'is_active': True
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✅ Tenant created: {tenant.name}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'  🔄 Tenant updated: {tenant.name}'))
            
            self.stdout.write(self.style.SUCCESS(f'  📋 Schema: {tenant.schema_name}'))
            
            # Create or update domain
            domain_obj, domain_created = Domain.objects.update_or_create(
                tenant=tenant,
                defaults={
                    'domain': domain,
                    'is_primary': True
                }
            )
            
            if domain_created:
                self.stdout.write(self.style.SUCCESS(f'  🌐 Domain created: {domain_obj.domain}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'  🌐 Domain updated: {domain_obj.domain}'))
            
            # Create or update tenant settings
            settings, settings_created = TenantSettings.objects.update_or_create(
                tenant=tenant,
                defaults={
                    'primary_color': '#14213D',
                    'secondary_color': '#C1CFEB',
                    'accent_color': '#EAB308',
                    'email_notifications': True,
                    'sms_notifications': False,
                    'push_notifications': True,
                    'otp_required': True,
                    'otp_expire_minutes': 5,
                    'payment_due_days': 5,
                    'late_fee_percentage': 5.0,
                }
            )
            
            if settings_created:
                self.stdout.write(self.style.SUCCESS(f'  ⚙️  Settings created'))
            else:
                self.stdout.write(self.style.SUCCESS(f'  ⚙️  Settings updated'))
            
            # Create subscription
            plan_amounts = {
                'basic': 999.00,
                'premium': 2999.00,
                'enterprise': 9999.00,
            }
            
            plan_limits = {
                'basic': {'users': 100, 'properties': 5, 'units': 100},
                'premium': {'users': 500, 'properties': 20, 'units': 500},
                'enterprise': {'users': 2000, 'properties': 100, 'units': 5000},
            }
            
            limits = plan_limits.get(plan, plan_limits['basic'])
            
            subscription, subscription_created = TenantSubscription.objects.update_or_create(
                tenant=tenant,
                defaults={
                    'start_date': timezone.now(),
                    'monthly_amount': plan_amounts.get(plan, 999.00),
                    'billing_cycle': 'monthly',
                    'max_users': limits['users'],
                    'max_properties': limits['properties'],
                    'max_units': limits['units'],
                    'status': 'active',
                    'is_trial': True,
                    'trial_end_date': timezone.now() + timezone.timedelta(days=30)
                }
            )
            
            if subscription_created:
                self.stdout.write(self.style.SUCCESS(f'  💎 Subscription created: {plan.upper()} (30-day trial)'))
            else:
                self.stdout.write(self.style.SUCCESS(f'  💎 Subscription updated: {plan.upper()}'))
            
            # Summary
            self.stdout.write(self.style.SUCCESS('\n' + '='*70))
            self.stdout.write(self.style.SUCCESS('🎉 TENANT CREATED SUCCESSFULLY!'))
            self.stdout.write(self.style.SUCCESS('='*70))
            self.stdout.write(f'\n📊 Summary:')
            self.stdout.write(f'  • Name: {tenant.name}')
            self.stdout.write(f'  • Schema: {tenant.schema_name}')
            self.stdout.write(f'  • Domain: {domain}')
            self.stdout.write(f'  • Email: {email}')
            self.stdout.write(f'  • Plan: {plan.upper()}')
            self.stdout.write(f'  • Features: {len([k for k, v in features.items() if v])}/{len(features)} enabled')
            
            self.stdout.write(self.style.WARNING(f'\n🔑 Next Steps:'))
            self.stdout.write(f'  1. Access tenant at: http://{domain}/')
            self.stdout.write(f'  2. Create facility manager user for this tenant')
            self.stdout.write(f'  3. Login and start adding residents!')
            
            self.stdout.write(self.style.WARNING(f'\n💡 Pro Tip:'))
            self.stdout.write(f'  Add DNS entry or hosts file mapping for production domains')
            self.stdout.write(f'  For localhost development, the domain will work automatically\n')
            
            return tenant
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Error creating tenant: {str(e)}'))
            raise CommandError(f'Failed to create tenant: {str(e)}')
    
    @transaction.atomic
    def create_demo_tenant(self):
        """Create a demo tenant for testing"""
        self.stdout.write(self.style.WARNING('\n🧪 Creating DEMO tenant...\n'))
        
        # Check if demo already exists
        if Domain.objects.filter(domain='demo.localhost:8000').exists():
            self.stdout.write(self.style.ERROR('❌ Demo tenant already exists!'))
            self.stdout.write('   Domain: demo.localhost:8000')
            return
        
        tenant = self.create_custom_tenant(
            name='Demo Property Management',
            domain='demo.localhost:8000',
            email='demo@propflow.com',
            phone='+91-9876543210',
            address='123 Demo Street, Mumbai, India',
            plan='premium'
        )
        
        self.stdout.write(self.style.SUCCESS('\n🎮 Demo tenant ready for testing!'))
    
    def get_default_features(self, plan):
        """Get default features based on subscription plan"""
        basic_features = {
            'people_hub': True,
            'csv_upload': True,
            'properties': True,
            'maintenance': True,
            'payments': True,
            'notifications': True,
        }
        
        premium_features = {
            'amenities': True,
            'visitor_management': True,
            'advanced_reports': True,
        }
        
        enterprise_features = {
            'marketplace': True,
            'analytics': True,
            'custom_integrations': True,
            'api_access': True,
            'white_labeling': True,
        }
        
        if plan == 'basic':
            return {
                **basic_features, 
                **{k: False for k in {**premium_features, **enterprise_features}}
            }
        elif plan == 'premium':
            return {
                **basic_features, 
                **premium_features, 
                **{k: False for k in enterprise_features}
            }
        elif plan == 'enterprise':
            return {
                **basic_features, 
                **premium_features, 
                **enterprise_features
            }
        else:
            return basic_features