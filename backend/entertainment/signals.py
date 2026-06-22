# entertainment/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from notifications.services import NotificationService
from .models import EventRegistration, Event

@receiver(post_save, sender=EventRegistration)
def notify_event_registration(sender, instance, created, **kwargs):
    """Notify user when they register for an event."""
    if created:
        NotificationService.send(
            user=instance.user,
            title="Event Registration Confirmed!",
            message=f"You have successfully registered for '{instance.event.title}' on {instance.event.start_date}.",
            notification_type='event',
            priority='medium',
            send_email=True,
            action_url=f"/entertainment/events/{instance.event.id}"
        )

@receiver(post_save, sender=Event)
def notify_event_update(sender, instance, created, **kwargs):
    """Notify all registered users if an event status changes to ongoing or completed."""
    if not created:
        if instance.status == 'ongoing':
            registrations = instance.registrations.all()
            for reg in registrations:
                NotificationService.send(
                    user=reg.user,
                    title="Event is starting!",
                    message=f"'{instance.title}' has started at {instance.venue}. We're waiting for you!",
                    notification_type='event',
                    priority='high',
                    send_email=True
                )
        elif instance.status == 'completed':
            registrations = instance.registrations.all()
            for reg in registrations:
                NotificationService.send(
                    user=reg.user,
                    title="How was the event?",
                    message=f"We hope you enjoyed '{instance.title}'. Please provide your feedback in the app!",
                    notification_type='event',
                    priority='low',
                    send_email=True
                )
