# tenants/signals.py - OPTIONAL BUT USEFUL
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import Client, Domain, TenantSettings, TenantSubscription
from .utils import update_hosts_file
import logging

logger = logging.getLogger(__name__)

_PLAN_AMOUNTS = {'basic': 99.99, 'premium': 1879.99, 'enterprise': 199.99}

@receiver(post_save, sender=Client)
def create_tenant_defaults(sender, instance, created, **kwargs):
    """
    Create default settings, subscription, KYC, and invoice when a new tenant is created.
    """
    if created:
        # --- TenantSettings ---
        TenantSettings.objects.get_or_create(
            tenant=instance,
            defaults={
                'primary_color': '#14213D',
                'secondary_color': '#C1CFEB',
                'accent_color': '#EAB308',
                'email_notifications': True,
                'sms_notifications': False,
                'push_notifications': True,
                'otp_required': True,
                'otp_expire_minutes': 5,
                'payment_due_days': 5,
                'late_fee_percentage': 5.0,
                'auto_assign_maintenance': False,
            }
        )

        # --- TenantSubscription ---
        if not hasattr(instance, 'subscription'):
            from pricing.models import PricingPlan, PlanService
            from decimal import Decimal
            plan_slug = instance.subscription_plan or 'basic'
            plan = PricingPlan.objects.filter(slug=plan_slug).first()
            
            base_monthly = Decimal('0.00')
            max_units = 100
            max_properties = 5
            max_users = 100
            
            if plan:
                base_monthly = plan.monthly_price or Decimal('0.00')
                max_units = plan.unit_limit if plan.unit_limit is not None else 99999
                max_users = plan.manager_limit if plan.manager_limit is not None else 500
                max_properties = 5 if plan_slug == 'basic' else 20 if plan_slug == 'premium' else 100
                
                # If plan has unit limits and is not Enterprise / custom, add units * unit_price
                if not plan.is_custom_pricing and plan_slug != 'enterprise' and plan.unit_limit:
                    units_service = PlanService.objects.filter(name='Units').first()
                    unit_price = units_service.price_per_unit if (units_service and units_service.price_per_unit > 0) else Decimal('9.00')
                    base_monthly += Decimal(str(plan.unit_limit)) * Decimal(str(unit_price))
            else:
                base_monthly = Decimal(str(_PLAN_AMOUNTS.get(plan_slug, 99.99)))
                max_users = 5 if plan_slug == 'basic' else 15 if plan_slug == 'premium' else 99999
                max_properties = 5 if plan_slug == 'basic' else 20 if plan_slug == 'premium' else 100
                max_units = 10 if plan_slug == 'basic' else 200 if plan_slug == 'premium' else 99999

            TenantSubscription.objects.get_or_create(
                tenant=instance,
                defaults={
                    'start_date': timezone.now(),
                    'monthly_amount': base_monthly,
                    'billing_cycle': 'monthly',
                    'max_users': max_users,
                    'max_properties': max_properties,
                    'max_units': max_units,
                    'status': 'active',
                }
            )

        # --- KYC record (always create so super admin can see it in KYC Review) ---
        # Skip public schema — it's not a real organization
        if instance.schema_name != 'public':
            try:
                from .models import KYC
                KYC.objects.get_or_create(
                    tenant=instance,
                    defaults={
                        'full_name': instance.name,
                        'email': instance.contact_email or '',
                        'status': 'not_started',
                    }
                )
            except Exception as e:
                logger.warning(f"Could not create KYC for {instance.name}: {e}")

        # --- PlatformInvoice (always create so super admin can see it in Invoice page) ---
        try:
            from .models import PlatformInvoice
            from decimal import Decimal
            from pricing.models import PricingPlan, PlanService
            
            plan_slug = instance.subscription_plan or 'basic'
            plan = PricingPlan.objects.filter(slug=plan_slug).first()
            
            plan_amount = Decimal('0.00')
            if plan:
                plan_amount = plan.monthly_price or Decimal('0.00')
                if not plan.is_custom_pricing and plan_slug != 'enterprise' and plan.unit_limit:
                    units_service = PlanService.objects.filter(name='Units').first()
                    unit_price = units_service.price_per_unit if (units_service and units_service.price_per_unit > 0) else Decimal('9.00')
                    plan_amount += Decimal(str(plan.unit_limit)) * Decimal(str(unit_price))
            else:
                plan_amount = Decimal(str(_PLAN_AMOUNTS.get(plan_slug, 999.00)))

            PlatformInvoice.objects.get_or_create(
                tenant=instance,
                defaults={
                    'amount': plan_amount,
                    'plan_name': instance.subscription_plan or 'basic',
                    'status': 'pending',
                    'billing_email': instance.contact_email or 'billing@hoaconnecthub.com',
                    'due_date': timezone.now().date() + timezone.timedelta(days=7),
                    'remarks': f'Activation Invoice for {instance.name}',
                }
            )
        except Exception as e:
            logger.warning(f"Could not create invoice for {instance.name}: {e}")

        logger.info(f"Created defaults (settings, subscription, KYC, invoice) for tenant: {instance.name}")

@receiver(post_save, sender=Client)
def log_tenant_changes(sender, instance, created, **kwargs):
    """
    Log tenant creation and updates
    """
    if created:
        logger.info(f"New tenant created: {instance.name} (Schema: {instance.schema_name})")
    else:
        logger.info(f"Tenant updated: {instance.name} (Schema: {instance.schema_name})")

@receiver(post_delete, sender=Client)
def log_tenant_deletion(sender, instance, **kwargs):
    """
    Log tenant deletion and clean up all orphaned records that reference
    this tenant via CharField (tenant_schema) instead of ForeignKey.
    """
    schema = instance.schema_name
    logger.warning(f"Tenant deleted: {instance.name} (Schema: {schema})")

    # --- Clean up pricing.Subscription (shown in Billing Overview) ---
    try:
        from pricing.models import Subscription
        deleted_count, _ = Subscription.objects.filter(tenant_schema=schema).delete()
        if deleted_count:
            logger.info(f"Deleted {deleted_count} Subscription(s) for schema '{schema}'")
    except Exception as e:
        logger.error(f"Failed to delete Subscription for schema '{schema}': {e}")

    # --- Clean up developer_portal records ---
    try:
        from developer_portal.models import APIKey, WebhookEndpoint
        del1, _ = APIKey.objects.filter(tenant_schema=schema).delete()
        del2, _ = WebhookEndpoint.objects.filter(tenant_schema=schema).delete()
        if del1 or del2:
            logger.info(f"Deleted {del1} APIKey(s) and {del2} WebhookEndpoint(s) for schema '{schema}'")
    except Exception as e:
        logger.error(f"Failed to delete developer_portal records for schema '{schema}': {e}")

    # --- Clean up notifications.EmailLog ---
    try:
        from notifications.models import EmailLog
        del_count, _ = EmailLog.objects.filter(tenant_schema=schema).delete()
        if del_count:
            logger.info(f"Deleted {del_count} EmailLog(s) for schema '{schema}'")
    except Exception as e:
        logger.error(f"Failed to delete EmailLog for schema '{schema}': {e}")

    # --- Clean up analytics records ---
    try:
        from analytics.models import AnalyticsEvent, DailyMetricSnapshot
        del1, _ = AnalyticsEvent.objects.filter(tenant_schema=schema).delete()
        del2, _ = DailyMetricSnapshot.objects.filter(tenant_schema=schema).delete()
        if del1 or del2:
            logger.info(f"Deleted {del1} AnalyticsEvent(s) and {del2} DailyMetricSnapshot(s) for schema '{schema}'")
    except Exception as e:
        logger.error(f"Failed to delete analytics records for schema '{schema}': {e}")

    # --- Clean up accounts.ActivityLog ---
    try:
        from accounts.models import ActivityLog
        del_count, _ = ActivityLog.objects.filter(tenant_schema=schema).delete()
        if del_count:
            logger.info(f"Deleted {del_count} ActivityLog(s) for schema '{schema}'")
    except Exception as e:
        logger.error(f"Failed to delete ActivityLog for schema '{schema}': {e}")

@receiver(post_save, sender=TenantSubscription)
def log_subscription_changes(sender, instance, created, **kwargs):
    """
    Log subscription changes
    """
    if created:
        logger.info(f"Subscription created for {instance.tenant.name}: {instance.status}")
    else:
        logger.info(f"Subscription updated for {instance.tenant.name}: {instance.status}")

# Optional: Add webhook notifications for tenant events
def send_tenant_webhook(event_type, tenant, data=None):
    """
    Send webhook notifications for tenant events
    This is a placeholder - implement actual webhook logic
    """
    webhook_data = {
        'event': event_type,
        'tenant_id': str(tenant.id),
        'tenant_name': tenant.name,
        'schema_name': tenant.schema_name,
        'timestamp': timezone.now().isoformat(),
        'data': data or {}
    }
    
    # TODO: Implement actual webhook sending logic
    logger.info(f"Webhook event: {event_type} for tenant {tenant.name}")
    
@receiver(post_save, sender=Client)
def trigger_tenant_webhook(sender, instance, created, **kwargs):
    """
    Trigger webhook for tenant events
    """
    if created:
        send_tenant_webhook('tenant.created', instance)
    else:
        send_tenant_webhook('tenant.updated', instance)

# --- Domain / Hosts File Sync ---

@receiver(post_save, sender=Domain)
def sync_domain_to_hosts(sender, instance, created, **kwargs):
    """
    Automatically add domain to local hosts file for easier development.
    Requires running the server as Administrator on Windows.
    """
    update_hosts_file(instance.domain, action='add')

@receiver(post_delete, sender=Domain)
def remove_domain_from_hosts(sender, instance, **kwargs):
    """
    Remove domain from local hosts file when the domain record is deleted.
    """
    update_hosts_file(instance.domain, action='remove')