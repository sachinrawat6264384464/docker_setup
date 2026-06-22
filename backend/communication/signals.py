# communication/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from notifications.services import NotificationService
from .models import Message, Announcement


@receiver(post_save, sender=Message)
def notify_new_message(sender, instance, created, **kwargs):
    """Send notification when new message is created"""
    if created and not instance.is_deleted:
        # Notify all conversation participants except sender
        participants = instance.conversation.participants.exclude(id=instance.sender.id)

        for participant in participants:
            NotificationService.send(
                user=participant,
                title='New Message',
                message=f'{instance.sender.get_full_name()} sent you a message',
                notification_type='message',
                related_object_id=instance.id,
                priority='medium',
                send_push=True,
            )


@receiver(post_save, sender=Announcement)
def notify_announcement(sender, instance, created, **kwargs):
    """Send notification when announcement is published"""
    if instance.is_published and instance.published_at:
        try:
            from django.contrib.auth import get_user_model
            
            User = get_user_model()
            
            # Determine target users
            if instance.target_all:
                target_users = User.objects.filter(is_active=True)
            else:
                # Filter by buildings if needed
                target_users = User.objects.filter(is_active=True)
            
            # Create notifications for each user
            for user in target_users:
                NotificationService.send(
                    user=user,
                    title=f'New Announcement: {instance.title}',
                    message=instance.content[:100],
                    notification_type='announcement',
                    related_object_id=instance.id,
                    priority='high' if instance.priority == 'urgent' else 'medium',
                    send_email=instance.priority in ['high', 'urgent'],
                    send_push=True,
                )
        except Exception:
            pass
