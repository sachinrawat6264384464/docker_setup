# notifications/tasks.py
from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model
from notifications.services import NotificationService

logger = get_task_logger(__name__)
User = get_user_model()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_notification_email_async(self, user_id, title, message, template_name=None):
    """
    Background Celery task to send a notification email asynchronously.
    This prevents SMTP latency from blocking the HTTP request/response cycle.
    Retries up to 3 times with a 30-second delay on failure.
    """
    try:
        from accounts.email_service import EmailService
        user = User.objects.get(pk=user_id)

        if not getattr(user, 'email', None):
            logger.warning("send_notification_email_async: user %s has no email, skipping.", user_id)
            return False

        if hasattr(EmailService, 'send_notification_email'):
            result = EmailService.send_notification_email(
                user=user,
                subject=title,
                title=title,
                message=message
            )
        else:
            from django.core.mail import send_mail
            from django.template.loader import render_to_string
            from django.utils.html import strip_tags
            from django.conf import settings

            context = {
                'user': user,
                'title': title,
                'message': message,
                'subject': title,
                'site_name': 'HOAConnectHub.com',
            }
            html_message = render_to_string('emails/notification_email.html', context)
            plain_message = strip_tags(html_message)
            sent_count = send_mail(
                subject=title,
                message=plain_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@hoaconnecthub.com'),
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            result = sent_count > 0

        logger.info("Background email sent to user %s: %s", user_id, title)
        return result

    except User.DoesNotExist:
        logger.error("send_notification_email_async: User %s not found.", user_id)
        return False
    except Exception as exc:
        logger.error("send_notification_email_async failed for user %s: %s", user_id, str(exc))
        # Retry on failure (e.g., SMTP timeout)
        raise self.retry(exc=exc)

@shared_task
def send_weekly_summary_emails():
    """
    Sends a weekly summary of activities to all active users who have the preference enabled.
    """
    logger.info("Starting weekly summary email task")
    # This is a placeholder for actual aggregation logic
    # In a real app, you'd fetch stats like payments made, maintenance status, etc.
    
    users = User.objects.filter(is_active=True)
    count = 0
    
    for user in users:
        # Check if user has weekly_digest preference (assuming it's in TenantSettings or Profile)
        # For now, we'll send it to all active users as a demo
        NotificationService.send(
            user=user,
            title="Your Weekly Community Summary",
            message="Here is a summary of what happened in your community this week. Check the app for more details!",
            notification_type='system',
            priority='low',
            send_email=True
        )
        count += 1
        
    logger.info(f"Weekly summary sent to {count} users")
    return {'sent_count': count}

@shared_task
def send_monthly_newsletter():
    """
    Sends a monthly newsletter to all residents.
    """
    logger.info("Starting monthly newsletter task")
    
    users = User.objects.filter(is_active=True)
    count = 0
    
    for user in users:
        NotificationService.send(
            user=user,
            title="Monthly Community Newsletter",
            message="Check out this month's highlights, upcoming events, and important updates in our community newsletter.",
            notification_type='announcement',
            priority='low',
            send_email=True
        )
        count += 1
        
    logger.info(f"Monthly newsletter sent to {count} users")
    return {'sent_count': count}

@shared_task
def remind_inactive_users():
    """
    Remind users who haven't logged in for 30 days.
    """
    logger.info("Starting inactive user reminder task")
    
    thirty_days_ago = timezone.now() - timedelta(days=30)
    inactive_users = User.objects.filter(
        is_active=True, 
        last_login__lt=thirty_days_ago
    )
    
    count = 0
    for user in inactive_users:
        NotificationService.send(
            user=user,
            title="We miss you!",
            message="It's been a while since you last visited HOA Connect. Come back and check out the latest updates!",
            notification_type='system',
            priority='medium',
            send_email=True
        )
        count += 1
        
    logger.info(f"Inactive reminders sent to {count} users")
    return {'sent_count': count}

@shared_task
def send_monthly_billing_summary():
    """
    Sends a monthly billing summary to all users with outstanding balances.
    """
    logger.info("Starting monthly billing summary task")
    from payments.models import Invoice
    
    users = User.objects.filter(is_active=True)
    count = 0
    
    for user in users:
        # Fetch unpaid invoices for the user
        unpaid_invoices = Invoice.objects.filter(
            user=user,
            status__in=['sent', 'viewed', 'partially_paid', 'overdue']
        )
        
        if unpaid_invoices.exists():
            total_due = sum(inv.amount_due for inv in unpaid_invoices)
            NotificationService.send(
                user=user,
                title="Monthly Billing Summary",
                message=f"You have {unpaid_invoices.count()} outstanding invoices with a total balance of ₹{total_due}. Please visit the payments section to settle your dues.",
                notification_type='payment',
                priority='medium',
                send_email=True,
                action_url='/payments/dashboard'
            )
            count += 1
            
    logger.info(f"Monthly billing summary sent to {count} users")
    return {'sent_count': count}
