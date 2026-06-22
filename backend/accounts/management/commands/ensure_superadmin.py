from django.core.management.base import BaseCommand
from accounts.models import User
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = 'Ensure the superadmin user exists in the public schema with correct credentials'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='superadmin')
        parser.add_argument('--email', default='superadmin@hoaconnecthub.com')
        parser.add_argument('--password', default='admin123')
        parser.add_argument('--force', action='store_true', help='Reset password even if user exists')

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        password = options['password']
        force = options['force']

        with schema_context('public'):
            user = User.objects.filter(username=username).first()

            if user:
                self.stdout.write(f"Found user '{username}' (role={user.role}, is_active={user.is_active})")
                pw_ok = user.check_password(password)
                self.stdout.write(f"  Password '{password}': {'CORRECT' if pw_ok else 'WRONG'}")

                if not pw_ok or force:
                    user.set_password(password)
                    user.is_active = True
                    user.is_approved = True
                    user.role = 'super_admin'
                    user.is_staff = True
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f"  Password reset to '{password}' and user activated."))
                else:
                    self.stdout.write(self.style.SUCCESS("  Password is correct — no changes needed."))
            else:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name='Super',
                    last_name='Admin',
                    role='super_admin',
                    is_active=True,
                    is_approved=True,
                    is_staff=True,
                    is_superuser=False,
                )
                self.stdout.write(self.style.SUCCESS(f"Created superadmin: {username} / {password}"))

            # Also show all public-schema users for reference
            self.stdout.write("\nAll users in public schema:")
            for u in User.objects.all().order_by('username'):
                pw_check = u.check_password(password)
                self.stdout.write(f"  - {u.username} | {u.email} | role={u.role} | active={u.is_active} | pw_ok={pw_check}")
