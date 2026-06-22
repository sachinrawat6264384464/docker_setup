# accounts/utils.py
import logging
from django.db import connection

logger = logging.getLogger(__name__)

def _create_notification(recipient, title, message, notification_type='system', priority='medium', action_url=''):
    """Helper to create in-app notifications."""
    if not recipient:
        return
        
    try:
        from notifications.models import Notification
        current_schema = getattr(connection, 'schema_name', 'public')
        
        Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            priority=priority,
            title=title,
            message=message,
            action_url=action_url,
            data={'schema': current_schema}
        )
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")

def _log_activity(user, action, description='', request=None, affected_user=None, metadata=None):
    """Helper to create activity log entries."""
    from django.db import connection
    current_schema = getattr(connection, 'schema_name', 'unknown')
    
    HUB_TEAM_ROLES = [
        'super_admin', 'super_admin_admin', 'operations_manager',
        'tech_support_lead', 'finance_billing_manager',
        'sales_marketing_admin', 'system_auditor', 'master_admin'
    ]
    
    is_public_user = False
    if user and (user.role in HUB_TEAM_ROLES) and current_schema != 'public':
        try:
            from django_tenants.utils import schema_context
            from accounts.models import User
            with schema_context('public'):
                is_public_user = User.objects.filter(pk=user.pk).exists()
        except Exception:
            is_public_user = False
    
    def _create_log():
        try:
            from accounts.models import ActivityLog
            ActivityLog.objects.create(
                user=user,
                action=action,
                description=description,
                ip_address=request.META.get('REMOTE_ADDR') if request else None,
                user_agent=request.META.get('HTTP_USER_AGENT', '') if request else '',
                tenant_schema=current_schema,
                affected_user=affected_user,
                metadata=metadata or {},
            )
        except Exception as e:
            logger.error(f"Failed to create activity log: {e}")

    if is_public_user:
        from django_tenants.utils import schema_context
        with schema_context('public'):
            _create_log()
    else:
        _create_log()
