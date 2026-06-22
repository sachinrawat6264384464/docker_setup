from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)

class EmailService:
    """
    Email service for OTP and notifications
    """
    
    @staticmethod
    def send_otp_email(user, otp_code):
        """Send OTP email to user"""
        try:
            subject = 'Verify Your Email - HOAConnect Hub'
            # HTML template context
            context = {
                'user': user,
                'otp_code': otp_code,
                'site_name': 'HOAConnect Hub',
                'expire_minutes': getattr(settings, 'OTP_EXPIRE_TIME', 300) // 60,
                'subject': subject,
            }
            
            html_message = render_to_string('emails/otp_email.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"OTP email sent successfully to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send OTP email to {user.email}: {str(e)}")
            return False
    
    @staticmethod
    def send_user_registration_notification(user):
        """Send notification to super admin about new user registration"""
        try:
            super_admin_email = getattr(settings, 'SUPER_ADMIN_EMAIL', None)
            if not super_admin_email:
                logger.warning("SUPER_ADMIN_EMAIL not configured")
                return False
            
            subject = f'New User Registration - {user.get_full_name()}'
            
            message = f"""
            New user has registered on PropFlow MVP:
            
            Name: {user.get_full_name()}
            Email: {user.email}
            Username: {user.username}
            Role: {user.get_role_display()}
            Phone: {user.phone or 'Not provided'}
            Unit: {user.unit_number or 'Not assigned'}
            Registration Time: {user.created_at.strftime('%Y-%m-%d %H:%M:%S')}
            
            Please review and approve if necessary.
            
            PropFlow MVP System
            """
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[super_admin_email],
                fail_silently=False,
            )
            
            logger.info(f"Registration notification sent to admin for user {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send registration notification for {user.email}: {str(e)}")
            return False
    
    @staticmethod
    def send_welcome_email(user, raw_password=None):
        """Send welcome email after successful verification"""
        try:
            subject = 'Welcome to HOAConnectHub.com!'
            
            msg = "Welcome to HOAConnect Hub! Your account has been created successfully.\n\n"
            msg += "Here are your login credentials:\n"
            msg += f"• Username: {user.username}\n"
            msg += f"• Email: {user.email}"
            if raw_password:
                msg += f"\n• Password: {raw_password}"
            msg += "\n\nYou can log in using either your username or email address."
            
            context = {
                'user': user,
                'title': 'Welcome aboard!',
                'message': msg,
                'subject': subject,
                'action_url': 'https://aibots.hoaconnecthub.com/login',
            }
            
            html_message = render_to_string('emails/notification_email.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Welcome email sent to {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")
            return False
    
    @staticmethod
    def send_admin_approval_required(user):
        """Send email to admin when tenant registration requires approval"""
        try:
            # Find admins in the current tenant
            from accounts.models import User
            admins = User.objects.filter(role='admin')
            
            if not admins.exists():
                logger.warning("No admins found to send approval notification")
                return False
            
            admin_emails = [admin.email for admin in admins]
            
            subject = f'New Registration Alert - {user.get_full_name()}'
            
            context = {
                'user': admins[0],  # Use the first admin as greeting
                'title': 'Approval Required',
                'message': f'A new tenant, {user.get_full_name()} ({user.email}), has registered and requires your approval to access the system.',
                'subject': subject,
                'action_url': 'https://hoaconnecthub.com/admin/members',
            }
            
            html_message = render_to_string('emails/notification_email.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=admin_emails,
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Tenant approval notification sent to admins for user {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send tenant approval notification for {user.email}: {str(e)}")
            return False

    @staticmethod
    def send_organization_credentials_email(user, password, org_name, domain):
        """Send credentials to the new Master Admin"""
        try:
            subject = f'Welcome to {org_name} - HOAConnect Hub'
            context = {
                'user': user,
                'password': password,
                'org_name': org_name,
                'login_url': f"https://{domain}/login",
                'subject': subject,
            }
            
            html_message = render_to_string('emails/organization_credentials.html', context)
            plain_message = strip_tags(html_message)
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Organization credentials email sent to {user.email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send org credentials to {user.email}: {str(e)}")
            return False