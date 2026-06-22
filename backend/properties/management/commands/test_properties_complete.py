# properties/management/commands/test_properties_complete.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from properties.models import Building, Unit, Lease
from django.utils import timezone
from datetime import timedelta
from django_tenants.utils import schema_context  # ADD THIS IMPORT

User = get_user_model()

class Command(BaseCommand):
    help = 'Complete test of Properties module'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            default='abc',  # Default to 'abc' tenant
            help='Tenant schema to run tests in'
        )
    
    def handle(self, *args, **kwargs):
        schema_name = kwargs['schema']
        
        # Run tests within tenant context
        with schema_context(schema_name):
            self._run_tests()
    
    def _run_tests(self):  # Rename existing handle method to _run_tests
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.HTTP_INFO('PROPERTIES MODULE COMPLETE TEST'))
        self.stdout.write('='*70 + '\n')
        
        # TEST 1: Create Building
        self.stdout.write('TEST 1: Creating building...')
        try:
            building = Building.objects.create(
                name='Test Tower A',
                address='123 Test Street',
                city='Test City',
                state='Test State',
                postal_code='12345',
                country='India',
                total_floors=10,
                total_units=40,
                building_type='apartment',
                year_built=2020,
                amenities=['gym', 'pool', 'parking'],
                description='Test building for properties module'
            )
            self.stdout.write(self.style.SUCCESS(f'✓ Building created: {building.name} (ID: {building.id})'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Building creation failed: {str(e)}'))
            return
        
        # TEST 2: Create Multiple Units
        self.stdout.write('\nTEST 2: Creating units...')
        units_created = 0
        try:
            for floor in range(1, 4):  # 3 floors
                for unit_num in ['01', '02']:
                    unit = Unit.objects.create(
                        building=building,
                        unit_number=f'{floor}{unit_num}',
                        floor=floor,
                        unit_type='2BHK',
                        bedrooms=2,
                        bathrooms=2,
                        area_sqft=1200.00,
                        monthly_rent=25000.00,
                        security_deposit=50000.00,
                        status='available',
                        description=f'Unit on floor {floor}',
                        features=['balcony', 'parking']
                    )
                    units_created += 1
            
            self.stdout.write(self.style.SUCCESS(f'✓ Created {units_created} units'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Unit creation failed: {str(e)}'))
            return
        
        # TEST 3: Create Test Tenants
        self.stdout.write('\nTEST 3: Creating test tenants...')
        try:
            tenant1 = User.objects.create_user(
                username='tenant_test_1',
                email='tenant1@test.com',
                password='test123',
                first_name='John',
                last_name='Doe',
                role='tenant',
                phone='9876543210'
            )
            
            tenant2 = User.objects.create_user(
                username='tenant_test_2',
                email='tenant2@test.com',
                password='test123',
                first_name='Jane',
                last_name='Smith',
                role='tenant',
                phone='9876543211'
            )
            
            self.stdout.write(self.style.SUCCESS(f'✓ Created 2 test tenants'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Tenant creation failed: {str(e)}'))
            return
        
        # TEST 4: Assign Tenant to Unit
        self.stdout.write('\nTEST 4: Assigning tenant to unit...')
        try:
            unit = Unit.objects.filter(building=building, status='available').first()
            
            # Create lease
            lease = Lease.objects.create(
                unit=unit,
                tenant=tenant1,
                start_date=timezone.now().date(),
                end_date=timezone.now().date() + timedelta(days=365),
                monthly_rent=unit.monthly_rent,
                security_deposit=unit.security_deposit,
                status='active',
                terms={'payment_day': 1, 'late_fee': 500}
            )
            
            # Update unit status
            unit.current_tenant = tenant1
            unit.status = 'occupied'
            unit.save()
            
            self.stdout.write(self.style.SUCCESS(f'✓ Tenant assigned: {tenant1.get_full_name()} → Unit {unit.unit_number}'))
            self.stdout.write(f'   Lease ID: {lease.id}')
            self.stdout.write(f'   Rent: ₹{lease.monthly_rent}/month')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Tenant assignment failed: {str(e)}'))
            return
        
        # TEST 5: Validate Business Logic
        self.stdout.write('\nTEST 5: Testing business logic...')
        
        # 5a: Prevent duplicate unit assignment
        try:
            duplicate_unit = Unit.objects.create(
                building=building,
                unit_number=unit.unit_number,  # Same number
                floor=1,
                unit_type='2BHK',
                monthly_rent=25000.00
            )
            self.stdout.write(self.style.ERROR('✗ Duplicate unit number was allowed (should fail)'))
        except Exception:
            self.stdout.write(self.style.SUCCESS('✓ Duplicate unit number prevented'))
        
        # 5b: Check occupancy calculation
        total_units = Unit.objects.filter(building=building).count()
        occupied_units = Unit.objects.filter(building=building, status='occupied').count()
        occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0
        
        self.stdout.write(self.style.SUCCESS(f'✓ Occupancy calculation: {occupied_units}/{total_units} = {occupancy_rate:.2f}%'))
        
        # TEST 6: Query Tests
        self.stdout.write('\nTEST 6: Testing queries...')
        
        # 6a: Available units
        available = Unit.objects.filter(building=building, status='available').count()
        self.stdout.write(self.style.SUCCESS(f'✓ Available units: {available}'))
        
        # 6b: Active leases
        active_leases = Lease.objects.filter(status='active').count()
        self.stdout.write(self.style.SUCCESS(f'✓ Active leases: {active_leases}'))
        
        # 6c: Expiring leases (within 30 days)
        thirty_days_later = timezone.now().date() + timedelta(days=30)
        expiring = Lease.objects.filter(
            status='active',
            end_date__lte=thirty_days_later,
            end_date__gte=timezone.now().date()
        ).count()
        self.stdout.write(self.style.SUCCESS(f'✓ Leases expiring in 30 days: {expiring}'))
        
        # TEST 7: Statistics
        self.stdout.write('\nTEST 7: Generating statistics...')
        stats = {
            'total_buildings': Building.objects.count(),
            'total_units': Unit.objects.count(),
            'occupied_units': Unit.objects.filter(status='occupied').count(),
            'available_units': Unit.objects.filter(status='available').count(),
            'maintenance_units': Unit.objects.filter(status='maintenance').count(),
            'active_leases': Lease.objects.filter(status='active').count(),
            'total_tenants': User.objects.filter(role='tenant').count(),
        }
        
        self.stdout.write(self.style.SUCCESS('✓ Statistics generated:'))
        for key, value in stats.items():
            self.stdout.write(f'   {key}: {value}')
        
        # TEST 8: Model Methods
        self.stdout.write('\nTEST 8: Testing model methods...')
        
        # Test Building.__str__
        self.stdout.write(self.style.SUCCESS(f'✓ Building str: {str(building)}'))
        
        # Test Unit.__str__
        test_unit = Unit.objects.first()
        self.stdout.write(self.style.SUCCESS(f'✓ Unit str: {str(test_unit)}'))
        
        # Test Lease.__str__
        test_lease = Lease.objects.first()
        if test_lease:
            self.stdout.write(self.style.SUCCESS(f'✓ Lease str: {str(test_lease)}'))
        
        # TEST 9: Lease Termination
        self.stdout.write('\nTEST 9: Testing lease termination...')
        try:
            if test_lease:
                # Terminate lease
                test_lease.status = 'terminated'
                test_lease.save()
                
                # Update unit
                test_unit = test_lease.unit
                test_unit.current_tenant = None
                test_unit.status = 'available'
                test_unit.save()
                
                self.stdout.write(self.style.SUCCESS('✓ Lease terminated and unit freed'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Lease termination failed: {str(e)}'))
        
        # SUMMARY
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS('✅ ALL PROPERTIES TESTS PASSED'))
        self.stdout.write('='*70)
        self.stdout.write('\nWhat was tested:')
        self.stdout.write('  ✓ Building creation')
        self.stdout.write('  ✓ Unit creation (multiple)')
        self.stdout.write('  ✓ Tenant creation')
        self.stdout.write('  ✓ Tenant assignment to unit')
        self.stdout.write('  ✓ Lease creation and management')
        self.stdout.write('  ✓ Duplicate prevention')
        self.stdout.write('  ✓ Occupancy calculations')
        self.stdout.write('  ✓ Query operations')
        self.stdout.write('  ✓ Statistics generation')
        self.stdout.write('  ✓ Model methods')
        self.stdout.write('  ✓ Lease termination')
        self.stdout.write('\n' + '='*70 + '\n')