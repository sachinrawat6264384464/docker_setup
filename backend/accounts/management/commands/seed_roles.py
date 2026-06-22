from django.core.management.base import BaseCommand
from accounts.models import Role

class Command(BaseCommand):
    help = 'Seeds Essential System Roles'

    def handle(self, *args, **options):
        roles = [
            {'name': 'master_admin', 'display_name': 'Master Admin', 'level': 100, 'is_system_role': True, 'description': 'Full platform access'},
            {'name': 'super_admin', 'display_name': 'Super Admin', 'level': 90, 'is_system_role': True, 'description': 'Hub management access'},
            {'name': 'facility_manager', 'display_name': 'Facility Manager', 'level': 70, 'is_system_role': True, 'description': 'Tenant management access'},
            {'name': 'tenant', 'display_name': 'Resident', 'level': 10, 'is_system_role': True, 'description': 'Standard resident access'},
            {'name': 'property_staff', 'display_name': 'Property Staff', 'level': 50, 'is_system_role': True, 'description': 'Basic property management'},
            {'name': 'maintenance_staff', 'display_name': 'Maintenance', 'level': 30, 'is_system_role': True, 'description': 'Maintenance desk access'},
        ]
        
        count = 0
        for r in roles:
            role, created = Role.objects.get_or_create(
                name=r['name'],
                defaults={
                    'display_name': r['display_name'],
                    'level': r['level'],
                    'is_system_role': r['is_system_role'],
                    'description': r['description'],
                    'is_active': True
                }
            )
            if created:
                count += 1
                self.stdout.write(self.style.SUCCESS(f"Created Role: {r['display_name']}"))
            else:
                self.stdout.write(self.style.WARNING(f"Role already exists: {r['display_name']}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} roles."))
