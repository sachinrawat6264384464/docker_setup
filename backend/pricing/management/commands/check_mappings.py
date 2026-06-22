from django.core.management.base import BaseCommand
from pricing.models import PricingPlan, PlanServiceMapping

class Command(BaseCommand):
    help = 'Check service mappings for plans'

    def handle(self, *args, **options):
        plans = PricingPlan.objects.all()
        for p in plans:
            mappings = PlanServiceMapping.objects.filter(plan=p)
            self.stdout.write(self.style.SUCCESS(f"Plan: {p.name} ({p.slug}) | Services: {mappings.count()}"))
            for m in mappings:
                self.stdout.write(f"  - {m.service.name}")
