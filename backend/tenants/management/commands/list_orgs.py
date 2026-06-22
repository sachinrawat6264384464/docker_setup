from django.core.management.base import BaseCommand
from tenants.models import Client

class Command(BaseCommand):
    help = 'List all organizations and their schemas'

    def handle(self, *args, **options):
        clients = Client.objects.all()
        self.stdout.write("All Organizations:")
        for c in clients:
            self.stdout.write(f"- Name: {c.name} | Schema: {c.schema_name} | Active: {c.is_active}")
