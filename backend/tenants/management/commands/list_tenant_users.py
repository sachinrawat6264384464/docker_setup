from django.core.management.base import BaseCommand
from tenants.models import Client
from accounts.models import User
from django_tenants.utils import schema_context

class Command(BaseCommand):
    help = 'List users in a specific tenant'

    def add_arguments(self, parser):
        parser.add_argument('schema', type=str, help='The tenant schema (e.g. tenant_rakhiorg)')

    def handle(self, *args, **options):
        schema = options['schema']
        try:
            with schema_context(schema):
                users = User.objects.all()
                self.stdout.write(self.style.SUCCESS(f"Total Users in {schema}: {users.count()}"))
                for u in users:
                    self.stdout.write(f"Username: {u.username} | Email: {u.email} | Role: {u.role}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
