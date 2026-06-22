# accounts/management/commands/view_all_users.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from tenants.models import Client
from django_tenants.utils import schema_context
from tabulate import tabulate

User = get_user_model()

class Command(BaseCommand):
    help = 'View all users across all tenant schemas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema',
            type=str,
            help='Filter by specific schema name',
        )
        parser.add_argument(
            '--role',
            type=str,
            help='Filter by specific role',
        )

    def handle(self, *args, **options):
        schema_filter = options.get('schema')
        role_filter = options.get('role')

        tenants = Client.objects.all()
        if schema_filter:
            tenants = tenants.filter(schema_name=schema_filter)

        all_user_data = []

        self.stdout.write(self.style.SUCCESS('\nFetching users across all schemas...\n'))

        # 1. Public Schema Users
        self.stdout.write(f"Checking schema: public")
        public_users = User.objects.all()
        if role_filter:
            public_users = public_users.filter(role=role_filter)
            
        for user in public_users:
            all_user_data.append([
                'public',
                user.id,
                user.username,
                user.email,
                user.role,
                'Active' if user.is_active else 'Inactive',
                user.date_joined.strftime('%Y-%m-%d')
            ])

        # 2. Tenant Schema Users
        for tenant in tenants.exclude(schema_name='public'):
            self.stdout.write(f"Checking schema: {tenant.schema_name}")
            try:
                with schema_context(tenant.schema_name):
                    users = User.objects.all()
                    if role_filter:
                        users = users.filter(role=role_filter)
                        
                    for user in users:
                        all_user_data.append([
                            tenant.schema_name,
                            user.id,
                            user.username,
                            user.email,
                            user.role,
                            'Active' if user.is_active else 'Inactive',
                            user.date_joined.strftime('%Y-%m-%d')
                        ])
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error accessing schema {tenant.schema_name}: {str(e)}"))

        if not all_user_data:
            self.stdout.write(self.style.WARNING('No users found matching the criteria.'))
            return

        headers = ['Schema', 'ID', 'Username', 'Email', 'Role', 'Status', 'Joined']
        self.stdout.write('\n' + tabulate(all_user_data, headers=headers, tablefmt='grid'))
        self.stdout.write(self.style.SUCCESS(f'\nTotal users found: {len(all_user_data)}\n'))