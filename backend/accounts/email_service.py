""" """  """ """# accounts/email_service.py (NEW FILE)
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)

class EmailService:
    """
    Centralized email service for sending emails
    """
    
    @staticmethod
    def send_email(to_email, subject, template_name, context, from_email=None):
        """
        Send email using template
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            template_name: Template file name (without .html)
            context: Context dict for template
            from_email: Sender email (optional)
            
        Returns:
            bool: True if sent successfully, False otherwise
        """
        try:
            if not from_email:
                from_email = f"{settings.DEFAULT_FROM_NAME} <{settings.DEFAULT_FROM_EMAIL}>"
            
            # Render HTML content
            html_content = render_to_string(f'emails/{template_name}.html', context)
            
            # Create plain text version
            text_content = strip_tags(html_content)
            
            # Create email
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email,
                to=[to_email]
            )
            
            # Attach HTML version
            email.attach_alternative(html_content, "text/html")
            
            # Send email
            email.send(fail_silently=False)
            
            logger.info(f"Email sent successfully to {to_email}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    
    @classmethod
    def send_welcome_email(cls, user, login_url=None, raw_password=None):
        """Send welcome email to new user"""
        if not login_url:
            login_url = f"https://{settings.MAIN_DOMAIN}/login"
            
        msg = "Your account has been successfully created and is ready to use.\n\n"
        msg += "Here are your login credentials:\n"
        msg += f"• Username: {user.username}\n"
        msg += f"• Email: {user.email}"
        if raw_password:
            msg += f"\n• Password: {raw_password}"
        msg += "\n\nYou can log in using either your username or email address."

        context = {
            'user': user,
            'login_url': login_url,
            'domain': settings.MAIN_DOMAIN,
            'message': msg
        }
        return cls.send_email(
            to_email=user.email,
            subject='Welcome to HOA Connect Hub!',
            template_name='welcome_email',
            context=context
        )

    @classmethod
    def send_notification_email(cls, user, subject, title, message, action_url=None):
        """Send a standard notification email"""
        context = {
            'user': user,
            'title': title,
            'message': message,
            'action_url': action_url,
            'domain': settings.MAIN_DOMAIN,
            'subject': subject
        }
        return cls.send_email(
            to_email=user.email,
            subject=subject,
            template_name='notification_email',
            context=context
        )
    
    @classmethod
    def send_otp_email(cls, user, otp_code):
        """Send OTP verification email"""
        context = {
            'user': user,
            'otp_code': otp_code,
            'subject': 'Your Verification Code',
            'domain': settings.MAIN_DOMAIN
        }
        return cls.send_email(
            to_email=user.email,
            subject='Your Verification Code',
            template_name='otp_email',
            context=context
        )
    
    @classmethod
    def send_password_reset_email(cls, user, reset_token):
        """Send password reset email"""
        reset_url = f"https://{settings.MAIN_DOMAIN}/reset-password?token={reset_token}"
        
        context = {
            'user': user,
            'reset_url': reset_url,
            'domain': settings.MAIN_DOMAIN,
            'subject': 'Password Reset Request'
        }
        return cls.send_email(
            to_email=user.email,
            subject='Password Reset Request',
            template_name='password_reset_email',
            context=context
        )

    @classmethod
    def send_payment_receipt_email(cls, user, amount, transaction_id, date, message):
        """Send payment receipt email"""
        context = {
            'user': user,
            'amount': amount,
            'transaction_id': transaction_id,
            'date': date,
            'message': message,
            'domain': settings.MAIN_DOMAIN,
            'subject': 'Payment Receipt'
        }
        return cls.send_email(
            to_email=user.email,
            subject='Payment Receipt - HOA Connect Hub',
            template_name='payment_receipt.html',
            context=context
        )
    
    @classmethod
    def send_csv_completion_email(cls, user, csv_upload):
        """Send CSV import completion email"""
        dashboard_url = f"{settings.FRONTEND_URL}/csv-uploads/{csv_upload.id}"
        
        context = {
            'user': user,
            'filename': csv_upload.original_filename,
            'total_rows': csv_upload.total_rows,
            'success_count': csv_upload.success_count,
            'error_count': csv_upload.error_count,
            'warning_count': csv_upload.warning_count,
            'dashboard_url': dashboard_url
        }
        
        # Set subject based on status
        if csv_upload.status == 'completed':
            subject = f'CSV Import Complete - {csv_upload.original_filename}'
        elif csv_upload.status == 'partial':
            subject = f'CSV Import Partial Success - {csv_upload.original_filename}'
        else:
            subject = f'CSV Import Failed - {csv_upload.original_filename}'
        
        return cls.send_email(
            to_email=user.email,
            subject=subject,
            template_name='csv_complete',
            context=context
        )