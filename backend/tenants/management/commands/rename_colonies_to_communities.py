from django.core.management.base import BaseCommand
from tenants.models import TenantFeature, Client
from pricing.models import PlanService
from django.db import transaction

class Command(BaseCommand):
    help = 'Renames colonies to communities in TenantFeature, PlanService, and Client JSON fields'

    def handle(self, *args, **kwargs):
        with transaction.atomic():
            # 1. Update TenantFeature
            try:
                tf = TenantFeature.objects.get(name='colonies')
                tf.name = 'communities'
                tf.display_name = 'Communities'
                tf.description = tf.description.replace('colonies', 'communities').replace('Colonies', 'Communities')
                tf.save()
                self.stdout.write(self.style.SUCCESS("Successfully renamed TenantFeature 'colonies' to 'communities'"))
            except TenantFeature.DoesNotExist:
                self.stdout.write(self.style.WARNING("TenantFeature 'colonies' does not exist."))

            # 2. Update PlanService
            try:
                ps = PlanService.objects.get(name='Colonies')
                ps.name = 'Communities'
                ps.description = ps.description.replace('colonies', 'communities').replace('Colonies', 'Communities')
                ps.save()
                self.stdout.write(self.style.SUCCESS("Successfully renamed PlanService 'Colonies' to 'Communities'"))
            except PlanService.DoesNotExist:
                self.stdout.write(self.style.WARNING("PlanService 'Colonies' does not exist."))

            # 3. Update Client feature dicts
            clients = Client.objects.all()
            updated_count = 0
            for client in clients:
                features = client.features or {}
                if 'colonies' in features:
                    features['communities'] = features.pop('colonies')
                    client.features = features
                    client.save(update_fields=['features'])
                    updated_count += 1
            
            self.stdout.write(self.style.SUCCESS(f"Successfully updated 'features' JSON for {updated_count} Clients."))
