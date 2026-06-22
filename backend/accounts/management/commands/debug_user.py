from django.core.management.base import BaseCommand
from accounts.models import User
from django_tenants.utils import schema_context
from tenants.models import Client

class Command(BaseCommand):
    help = 'Debug user login issues in a specific schema'

    def add_arguments(self, parser):
        parser.add_argument('schema', type=str, help='Schema name (e.g. tenant_aparna)')
        parser.add_argument('identifier', type=str, help='Email or Username')
        parser.add_argument('--password', type=str, default='Propra@123', help='Password to test')

    def handle(self, *args, **options):
        schema_name = options['schema']
        identifier = options['identifier']
        test_pass = options['password']

        try:
            with schema_context(schema_name):
                if identifier == 'ALL':
                    self.stdout.write(f"Listing all users in schema '{schema_name}':")
                    users = User.objects.all()
                    for u in users:
                        self.stdout.write(f"- Username: {u.username} | Email: {u.email} | Role: {u.role}")
                    return

                user = User.objects.filter(email=identifier).first() or User.objects.filter(username=identifier).first()
                if user:
                    self.stdout.write(self.style.SUCCESS(f"User found!"))
                    self.stdout.write(f"Username: {user.username}")
                    self.stdout.write(f"Email: {user.email}")
                    self.stdout.write(f"Role: {user.role}")
                    if user.check_password(test_pass):
                        self.stdout.write(self.style.SUCCESS(f"Password CORRECT."))
                    else:
                        self.stdout.write(self.style.ERROR(f"Password INCORRECT."))
                else:
                    self.stdout.write(self.style.ERROR(f"User '{identifier}' not found."))
                    self.stdout.write("All users in this schema:")
                    for u in User.objects.all():
                        self.stdout.write(f"  - {u.username} ({u.email})")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
