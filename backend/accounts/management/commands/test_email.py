# accounts/management/commands/test_email.py
from django.core.management.base import BaseCommand
from accounts.email_service import EmailService
from accounts.models import User

class Command(BaseCommand):
    help = 'Test email system'
    
    def handle(self, *args, **kwargs):
        # Get or create test user
        user, created = User.objects.get_or_create(
            username='testuser',
            defaults={
                'email': 'your-test-email@example.com',
                'first_name': 'Test',
                'last_name': 'User'
            }
        )
        
        self.stdout.write('Testing email system...')
        
        # Test welcome email
        self.stdout.write('Sending welcome email...')
        result = EmailService.send_welcome_email(user)
        if result:
            self.stdout.write(self.style.SUCCESS('Welcome email sent!'))
        else:
            self.stdout.write(self.style.ERROR('Failed to send welcome email'))
        
        # Test OTP email
        self.stdout.write('\nSending OTP email...')
        result = EmailService.send_otp_email(user, '123456')
        if result:
            self.stdout.write(self.style.SUCCESS('OTP email sent!'))
        else:
            self.stdout.write(self.style.ERROR('Failed to send OTP email'))
        
        self.stdout.write(self.style.SUCCESS('\nEmail test complete!'))