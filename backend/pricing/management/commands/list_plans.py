from django.core.management.base import BaseCommand
from pricing.models import PricingPlan

class Command(BaseCommand):
    help = 'List all pricing plans'

    def handle(self, *args, **options):
        plans = PricingPlan.objects.all()
        for p in plans:
            self.stdout.write(f"ID: {p.id} | Name: {p.name} | Slug: {p.slug}")
