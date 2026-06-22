from django.core.management.base import BaseCommand
from accounts.models import User
from tenants.models import Client
from django_tenants.utils import schema_context

class Command(BaseCommand):
    help = 'Create a Master Admin for a tenant'

    def add_arguments(self, parser):
        parser.add_argument('schema', type=str, help='Tenant schema name')
        parser.add_argument('username', type=str, help='Admin username')
        parser.add_argument('email', type=str, help='Admin email')
        parser.add_argument('password', type=str, help='Admin password')

    def handle(self, *args, **options):
        schema = options['schema']
        username = options['username']
        email = options['email']
        password = options['password']

        try:
            tenant = Client.objects.get(schema_name=schema)
            with schema_context(schema):
                if User.objects.filter(username=username).exists():
                    self.stdout.write(self.style.WARNING(f"User {username} already exists. Updating password..."))
                    user = User.objects.get(username=username)
                    user.set_password(password)
                    user.save()
                else:
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        role='master_admin',
                        is_active=True,
                        is_approved=True,
                        tenant_id=schema
                    )
                    self.stdout.write(self.style.SUCCESS(f"Master Admin '{username}' created successfully in {schema}."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
