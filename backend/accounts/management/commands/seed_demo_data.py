from django.core.management.base import BaseCommand
from django.db import transaction, connection
from django.utils import timezone
from django.contrib.auth import get_user_model
from django_tenants.utils import schema_context
from datetime import date, timedelta
from decimal import Decimal

User = get_user_model()

# Super Admin Users
SUPER_ADMINS = [
    {'username': 'soham', 'email': 'soham@hoaconnecthub.com', 'password': 'Soham@271093', 'role': 'super_admin'},
    {'username': 'ashutosh', 'email': 'ashutosh@hoaconnecthub.com', 'password': 'Ashutosh@2026', 'role': 'super_admin'},
    {'username': 'krishna', 'email': 'krishna@hoaconnecthub.com', 'password': 'Krishna@2026', 'role': 'super_admin'},
]

class Command(BaseCommand):
    help = 'Seed super admins in public schema'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Wipe existing users')

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Starting Seeding Process...'))

        if options['reset']:
            with connection.cursor() as cursor:
                cursor.execute(f'TRUNCATE TABLE "{User._meta.db_table}" CASCADE')

        # Create or update Super Admins inside public context
        with schema_context('public'):
            for cred in SUPER_ADMINS:
                user, created = User.objects.get_or_create(
                    username=cred['username'], 
                    defaults={
                        'email': cred['email'],
                        'role': cred['role'],
                        'is_staff': True,
                        'is_superuser': True,
                        'is_active': True,
                        'is_approved': True,
                    }
                )
                if not created:
                    user.role = cred['role']
                    user.is_superuser = True
                    user.is_staff = True
                    user.save()
                else:
                    user.set_password(cred['password'])
                    user.save()
                    self.stdout.write(f'Created Super Admin: {cred["username"]}')

        self.stdout.write(self.style.SUCCESS('Seed complete!'))