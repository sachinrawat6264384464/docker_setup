from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from tenants.models import Client, KYC
from accounts.models import User
from accounts.utils import _create_notification
from django_tenants.utils import schema_context

class Command(BaseCommand):
    help = 'Check KYC compliance and send reminders or lock accounts'

    def handle(self, *args, **options):
        now = timezone.now()
        tenants = Client.objects.exclude(schema_name='public')
        
        for tenant in tenants:
            kyc, created = KYC.objects.get_or_create(tenant=tenant)
            if kyc.status == 'approved': continue
            
            age = now - tenant.created_on
            with schema_context(tenant.schema_name):
                master_admin = User.objects.filter(role='master_admin').first()
                if not master_admin: continue
                    
                if kyc.status in ['not_started', 'draft']:
                    if age > timedelta(hours=72):
                        self.lock_account(tenant, kyc, master_admin)
                    elif age > timedelta(hours=48):
                        self.send_reminder(tenant, master_admin, "Final Warning: Complete KYC within 24h to avoid account suspension.")
                    elif age > timedelta(hours=24):
                        self.send_reminder(tenant, master_admin, "Reminder: Please complete your organization KYC verification.")
                
                elif kyc.status == 'resubmission_required':
                    if kyc.updated_at < now - timedelta(hours=24):
                        self.send_reminder(tenant, master_admin, "Action Required: Please resubmit your KYC documents as requested.")

    def send_reminder(self, tenant, user, message):
        _create_notification(recipient=user, title="KYC Reminder", message=message, notification_type='warning')
        self.stdout.write(self.style.SUCCESS(f"Reminder sent to {tenant.name}"))

    def lock_account(self, tenant, kyc, user):
        _create_notification(recipient=user, title="Account Suspended", message="KYC non-compliance suspension.", notification_type='error')
        self.stdout.write(self.style.ERROR(f"Account locked for {tenant.name}"))
