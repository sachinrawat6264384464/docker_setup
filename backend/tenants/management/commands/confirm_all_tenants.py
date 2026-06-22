from django.core.management.base import BaseCommand
from tenants.models import Client

class Command(BaseCommand):
    help = 'Confirm all organizations to show in dashboard'

    def handle(self, *args, **options):
        clients = Client.objects.filter(is_confirmed=False).exclude(schema_name='public')
        count = clients.count()
        clients.update(is_confirmed=True)
        self.stdout.write(self.style.SUCCESS(f"Successfully confirmed {count} organizations."))
