from django.core.management.base import BaseCommand
from tenants.models import Client, Domain

class Command(BaseCommand):
    help = 'List all tenants and their domains'

    def handle(self, *args, **options):
        tenants = Client.objects.all()
        self.stdout.write(self.style.SUCCESS(f"Total Tenants: {tenants.count()}"))
        
        for t in tenants:
            domains = Domain.objects.filter(tenant=t)
            domain_list = ", ".join([d.domain for d in domains])
            self.stdout.write(f"Schema: {t.schema_name} | Name: {t.name} | Domains: [{domain_list}]")
