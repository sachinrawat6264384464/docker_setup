from django.core.management.base import BaseCommand
from django.utils import timezone
from tenants.models import KYC, Client
import random

class Command(BaseCommand):
    help = 'Seeds KYC data for all existing tenants'

    def handle(self, *args, **options):
        tenants = Client.objects.exclude(schema_name='public')
        if not tenants.exists():
            self.stdout.write(self.style.WARNING("No tenants found to create KYC for."))
            return

        statuses = ['submitted', 'under_review', 'approved', 'rejected']
        count = 0
        
        for i, tenant in enumerate(tenants):
            # If KYC already exists, just update it, else create
            status = random.choice(statuses)
            kyc, created = KYC.objects.get_or_create(
                tenant=tenant,
                defaults={
                    'full_name': f"{tenant.name} Administrator",
                    'email': tenant.contact_email or f"admin@{tenant.schema_name}.com",
                    'status': status,
                    'pan_number': f'ABCDE{random.randint(1000, 9999)}F',
                    'gst_number': f'22AAAAA{random.randint(1000, 9999)}A1Z5',
                    'submitted_at': timezone.now() - timezone.timedelta(days=random.randint(1, 10)),
                    'updated_at': timezone.now()
                }
            )
            
            if not created:
                kyc.status = status
                kyc.updated_at = timezone.now()
                kyc.save()
            
            count += 1
            self.stdout.write(self.style.SUCCESS(f"Processed KYC for {tenant.name} -> {status}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} KYC records."))
