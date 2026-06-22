# properties/management/commands/sync_unit_lease_status.py
"""
Tenant-aware sync command - manually iterates through tenants
Usage: python manage.py sync_unit_lease_status --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import connection
from properties.models import Unit, Lease
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Sync unit occupancy status with active leases (all tenants)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )
        parser.add_argument(
            '--fix-duplicates',
            action='store_true',
            help='Automatically fix units with multiple active leases',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        fix_duplicates = options.get('fix_duplicates', False)
        
        # Get all tenant schemas
        try:
            from django_tenants.utils import get_tenant_model, schema_context
            TenantModel = get_tenant_model()
            tenants = TenantModel.objects.exclude(schema_name='public')
            
            self.stdout.write(self.style.SUCCESS(f'Found {tenants.count()} tenant schemas\n'))
            
            total_stats = {
                'schemas': 0,
                'total_units': 0,
                'total_issues': 0,
                'total_duplicates': 0,
                'total_updated': 0,
                'total_tenants_updated': 0,
            }
            
            # Process each tenant
            for tenant in tenants:
                with schema_context(tenant.schema_name):
                    stats = self.sync_schema(tenant.schema_name, dry_run, fix_duplicates)
                    
                    total_stats['schemas'] += 1
                    total_stats['total_units'] += stats['total_units']
                    total_stats['total_issues'] += stats['issues']
                    total_stats['total_duplicates'] += stats['duplicates']
                    total_stats['total_updated'] += stats['updated']
                    total_stats['total_tenants_updated'] += stats['tenants_updated']
            
            # Overall summary
            if tenants.count() > 1:
                self.stdout.write('\n' + '='*60)
                self.stdout.write(self.style.SUCCESS('📊 OVERALL SUMMARY'))
                self.stdout.write('='*60)
                self.stdout.write(f"Schemas processed: {total_stats['schemas']}")
                self.stdout.write(f"Total units checked: {total_stats['total_units']}")
                self.stdout.write(f"Total issues found: {total_stats['total_issues']}")
                self.stdout.write(f"Total duplicates: {total_stats['total_duplicates']}")
                if not dry_run:
                    self.stdout.write(self.style.SUCCESS(f"✅ Units updated: {total_stats['total_updated']}"))
                    self.stdout.write(self.style.SUCCESS(f"✅ Tenants updated: {total_stats['total_tenants_updated']}"))
                self.stdout.write('='*60)
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error: {str(e)}'))
            import traceback
            traceback.print_exc()

    def sync_schema(self, schema_name, dry_run, fix_duplicates):
        """Sync units for a specific schema"""
        
        self.stdout.write('='*60)
        self.stdout.write(self.style.SUCCESS(f'📋 Schema: {schema_name}'))
        self.stdout.write('='*60)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 DRY RUN MODE - No changes will be made'))
        
        stats = {
            'updated': 0,
            'issues': 0,
            'duplicates': 0,
            'tenants_updated': 0,
            'total_units': 0,
        }
        
        try:
            units = Unit.objects.all().select_related('building')
            stats['total_units'] = units.count()
            
            self.stdout.write(f'📊 Checking {stats["total_units"]} units...\n')
            
            for unit in units:
                active_leases = Lease.objects.filter(
                    unit=unit,
                    status='active'
                ).select_related('tenant')
                
                active_count = active_leases.count()
                has_active_lease = active_count > 0
                
                # Issue 1: Multiple active leases
                if active_count > 1:
                    stats['duplicates'] += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f'❌ Unit {unit.building.name} - {unit.unit_number}: '
                            f'{active_count} active leases!'
                        )
                    )
                    
                    if fix_duplicates and not dry_run:
                        most_recent = active_leases.order_by('-created_at').first()
                        others = active_leases.exclude(id=most_recent.id)
                        
                        for lease in others:
                            lease.status = 'terminated'
                            lease.save()
                            self.stdout.write(
                                self.style.WARNING(f'  ⚠️  Terminated lease {lease.id}')
                            )
                        
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✅ Kept lease {most_recent.id}')
                        )
                        stats['issues'] += 1
                
                # Issue 2: Has active lease but marked available
                if has_active_lease and not unit.is_occupied:
                    stats['issues'] += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠️  Unit {unit.building.name} - {unit.unit_number}: '
                            f'Has lease but marked AVAILABLE'
                        )
                    )
                    
                    if not dry_run:
                        unit.status = 'occupied'
                        unit.is_occupied = True
                        unit.unit_type = 'tenant_occupied'
                        unit.save()
                        stats['updated'] += 1
                        self.stdout.write(self.style.SUCCESS('  ✅ Updated to OCCUPIED'))
                
                # Issue 3: Marked occupied but no active lease
                elif not has_active_lease and unit.is_occupied:
                    stats['issues'] += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠️  Unit {unit.building.name} - {unit.unit_number}: '
                            f'Marked OCCUPIED but NO lease'
                        )
                    )
                    
                    if not dry_run:
                        unit.status = 'available'
                        unit.is_occupied = False
                        unit.unit_type = 'vacant'
                        unit.save()
                        stats['updated'] += 1
                        self.stdout.write(self.style.SUCCESS('  ✅ Updated to AVAILABLE'))
                
                # Update tenant info
                if has_active_lease and active_count == 1:
                    lease = active_leases.first()
                    tenant = lease.tenant
                    
                    if (tenant.unit_number != unit.unit_number or 
                        tenant.building_name != unit.building.name):
                        
                        self.stdout.write(
                            self.style.WARNING(
                                f'⚠️  Tenant {tenant.get_full_name()} info mismatch'
                            )
                        )
                        
                        if not dry_run:
                            tenant.unit_number = unit.unit_number
                            tenant.building_name = unit.building.name
                            tenant.save()
                            stats['tenants_updated'] += 1
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'  ✅ Updated to {unit.building.name} - {unit.unit_number}'
                                )
                            )
            
            # Schema summary
            self.stdout.write('\n' + '-'*60)
            self.stdout.write(self.style.SUCCESS(f'📊 SUMMARY FOR {schema_name}'))
            self.stdout.write('-'*60)
            self.stdout.write(f'Total units: {stats["total_units"]}')
            self.stdout.write(f'Issues found: {stats["issues"]}')
            self.stdout.write(f'Duplicates: {stats["duplicates"]}')
            
            if not dry_run:
                self.stdout.write(self.style.SUCCESS(f'✅ Units updated: {stats["updated"]}'))
                self.stdout.write(self.style.SUCCESS(f'✅ Tenants updated: {stats["tenants_updated"]}'))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'Would update {stats["updated"]} units and {stats["tenants_updated"]} tenants'
                    )
                )
            self.stdout.write('-'*60 + '\n')
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error in {schema_name}: {str(e)}'))
        
        return stats
