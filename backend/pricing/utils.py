from pricing.models import Subscription
from properties.models import Unit
from django.db import connection


def get_current_tenant_subscription(schema_name):
    """Fetches the active subscription for a given tenant schema."""
    try:
        return Subscription.objects.get(tenant_schema=schema_name)
    except Subscription.DoesNotExist:
        return None


def check_unit_limit():
    """
    Checks if creating a new unit would exceed the subscription limit.
    Returns (True, None) if allowed, (False, error_message) if limit reached.
    """
    schema_name = connection.schema_name

    # Bypass for public schema or testing
    if schema_name == 'public':
        return True, None

    subscription = get_current_tenant_subscription(schema_name)

    if not subscription:
        # No subscription configured — allow unlimited access (free tier / dev mode)
        return True, None

    if subscription.status not in ['active', 'trialing']:
        return False, f"Subscription is currently {subscription.status}. Please renew to add units."

    plan = subscription.plan
    if plan.unit_limit is None:  # Unlimited plan
        return True, None

    current_unit_count = Unit.objects.count()
    if current_unit_count >= plan.unit_limit:
        return False, f"Unit limit ({plan.unit_limit}) reached for the {plan.name} plan. Please upgrade your subscription."

    return True, None

def check_manager_limit():
    """
    Checks if creating a new manager would exceed the subscription limit.
    Returns (True, None) if allowed, (False, error_message) if limit reached.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    schema_name = connection.schema_name

    # Bypass for public schema or testing
    if schema_name == 'public':
        return True, None

    subscription = get_current_tenant_subscription(schema_name)

    if not subscription:
        # No subscription configured — allow unlimited access (free tier / dev mode)
        return True, None

    if subscription.status not in ['active', 'trialing']:
        return False, f"Subscription is currently {subscription.status}. Please renew to add managers."

    plan = subscription.plan
    if plan.manager_limit is None:  # Unlimited plan
        return True, None

    current_manager_count = User.objects.filter(role__in=['manager', 'admin']).count()
    if current_manager_count >= plan.manager_limit:
        return False, f"Manager limit ({plan.manager_limit}) reached for the {plan.name} plan. Please upgrade your subscription to add more managers."

    return True, None
