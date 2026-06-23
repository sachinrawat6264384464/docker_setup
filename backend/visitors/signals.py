# visitors/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from notifications.services import NotificationService
from .models import VisitorPass, VisitorLog


@receiver(post_save, sender=VisitorPass)
def handle_pass_approval(sender, instance, created, **kwargs):
    """
    Handle visitor pass approval - generate QR code and send notifications
    """
    if instance.status == 'approved' and not created:
        # Generate QR code if not already generated
        if not instance.qr_code:
            instance.generate_qr_code()
        
        # Send notification to host
        try:
            NotificationService.send(
                user=instance.host,
                title='Visitor Pass Approved',
                message=f'Visitor pass for {instance.visitor.get_full_name()} has been approved.',
                notification_type='visitor',
                related_object_id=instance.id,
                priority='medium',
                send_push=True,
                send_email=True
            )
        except Exception:
            pass


@receiver(post_save, sender=VisitorPass)
def notify_pass_rejection(sender, instance, created, **kwargs):
    """
    Notify host when visitor pass is rejected
    """
    if instance.status == 'rejected' and not created:
        try:
            NotificationService.send(
                user=instance.host,
                title='Visitor Pass Rejected',
                message=f'Visitor pass for {instance.visitor.get_full_name()} was rejected. Reason: {instance.rejection_reason}',
                notification_type='visitor',
                related_object_id=instance.id,
                priority='high',
                send_push=True,
                send_email=True
            )
        except ImportError:
            pass


@receiver(pre_save, sender=VisitorPass)
def check_expired_passes(sender, instance, **kwargs):
    """
    Auto-expire passes that are past their departure time
    """
    if instance.status in ['approved', 'active']:
        if instance.expected_departure and timezone.now() > instance.expected_departure:
            if instance.status == 'active' and not instance.actual_departure:
                # Auto checkout if not manually checked out
                instance.actual_departure = timezone.now()
            instance.status = 'expired'


@receiver(post_save, sender=VisitorLog)
def update_visitor_stats(sender, instance, created, **kwargs):
    """
    Update visitor statistics when check-in/out happens
    """
    if created and instance.log_type == 'check_in':
        visitor = instance.visitor_pass.visitor
        visitor.last_visit = instance.timestamp
        visitor.save(update_fields=['last_visit'])


@receiver(post_save, sender=VisitorPass)
def send_checkin_reminder(sender, instance, created, **kwargs):
    """
    Send reminder to security when visitor is expected to arrive soon
    """
    if instance.status == 'approved' and created:
        # Schedule reminder notification (this would typically use Celery)
        # For now, we'll just create an immediate notification if arrival is within next hour
        from datetime import timedelta
        
        if instance.expected_arrival:
            time_until_arrival = instance.expected_arrival - timezone.now()
            
            if timedelta(minutes=0) <= time_until_arrival <= timedelta(hours=1):
                try:
                    from notifications.models import Notification
                    from django.contrib.auth import get_user_model
                    
                    User = get_user_model()
                    
                    # Notify security staff
                    security_staff = User.objects.filter(role__in=['security', 'security_guard'])
                    
                    for staff in security_staff:
                        NotificationService.send(
                            user=staff,
                            title='Visitor Arriving Soon',
                            message=f'{instance.visitor.get_full_name()} is expected to arrive at {instance.building} in {int(time_until_arrival.total_seconds() / 60)} minutes.',
                            notification_type='visitor',
                            related_object_id=instance.id,
                            priority='medium',
                            send_push=True
                        )
                except Exception:
                    pass