# accounts/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, UserProfile
from notifications.services import NotificationService
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Auto-create UserProfile whenever a User is created."""
    if created:
        try:
            UserProfile.objects.get_or_create(user=instance)
        except Exception as e:
            logger.warning(f"Profile creation failed for {instance.username}: {e}")

        # Notify all super admins about the new user joining
        _notify_superadmins_new_user(instance)
        
        # Send Welcome Notification to the new user
        _send_welcome_notification(instance)


def _notify_superadmins_new_user(new_user):
    """
    Create an in-app notification for every super_admin user when
    a new (non-super_admin) account is created.
    Runs inside the current schema context.
    """
    if new_user.role == 'super_admin':
        return  # Don't notify about super_admin creations

    try:
        from notifications.models import Notification
        from django.db import connection

        # Only notify super_admins on the public schema
        if connection.schema_name != 'public':
            # In tenant schema — skip (super_admins live on public schema)
            return

        super_admins = User.objects.filter(role='super_admin', is_active=True)
        role_label = (new_user.role or 'user').replace('_', ' ').title()
        title = f"New {role_label} Joined"
        message = (
            f"{new_user.get_full_name() or new_user.username} "
            f"({new_user.email}) has joined the platform as {role_label}."
        )

        notifications = [
            {
                'recipient': admin,
                'notification_type': 'system',
                'priority': 'medium',
                'title': title,
                'message': message,
                'send_email': False,
                'send_sms': False,
                'send_push': True,
                'send_in_app': True,
                'action_url': '/admin/members',
            }
            for admin in super_admins
        ]
        if notifications:
            for item in notifications:
                NotificationService.send(
                    user=item['recipient'],
                    title=item['title'],
                    message=item['message'],
                    notification_type=item['notification_type'],
                    priority=item['priority'],
                    send_email=item['send_email'],
                    send_sms=item['send_sms'],
                    send_push=item['send_push'],
                    action_url=item['action_url'],
                )
    except Exception:
        pass



def _send_welcome_notification(user):
    """Send appropriate welcome notification based on user role."""
    try:
        from notifications.services import NotificationService
        
        if user.role in ['master_admin', 'masteradmin']:
            NotificationService.send_welcome_notification(user, 'master_admin_activated')
        elif user.role == 'facility_manager':
            NotificationService.send_welcome_notification(user, 'fm_appointed')
        elif user.role in ['tenant', 'owner']:
            NotificationService.send_welcome_notification(user, 'resident_onboarding')
        
    except Exception as e:
        logger.warning(f"Welcome notification failed for {user.username}: {e}")
