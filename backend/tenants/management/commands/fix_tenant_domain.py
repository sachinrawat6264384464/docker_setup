from django.core.management.base import BaseCommand
from tenants.models import Client, Domain

class Command(BaseCommand):
    help = 'Fix domains for any tenant'

    def add_arguments(self, parser):
        parser.add_argument('slug', type=str, help='The tenant slug/schema (e.g. rakhiorg)')
        parser.add_argument('domain', type=str, help='The full domain (e.g. rakhiorg.hoaconnecthub.com)')

    def handle(self, *args, **options):
        slug = options['slug']
        domain_name = options['domain']
        
        # Look for the tenant
        tenant = Client.objects.filter(schema_name__icontains=slug).first()
        if not tenant:
            self.stdout.write(self.style.ERROR(f"Tenant '{slug}' not found!"))
            return

        self.stdout.write(self.style.SUCCESS(f"Found Tenant: {tenant.name} (Schema: {tenant.schema_name})"))
        
        # Update or create domain
        domain_obj, created = Domain.objects.get_or_create(
            tenant=tenant,
            domain=domain_name,
            defaults={'is_primary': True}
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f"Domain '{domain_name}' created for {tenant.name}."))
        else:
            self.stdout.write(self.style.WARNING(f"Domain '{domain_name}' already exists for {tenant.name}."))
            if not domain_obj.is_primary:
                domain_obj.is_primary = True
                domain_obj.save()
                self.stdout.write(self.style.SUCCESS("Marked as primary domain."))
