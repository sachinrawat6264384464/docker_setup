# accounts/tasks.py
from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from datetime import timedelta
from .email_service import EmailService

logger = get_task_logger(__name__)

@shared_task(bind=True, max_retries=3)
def process_csv_file_async(self, csv_upload_id):
    """
    Async task to process CSV file
    
    Args:
        csv_upload_id: UUID of the CSVUpload instance
    
    Returns:
        dict: Processing result with success status and details
    """
    try:
        logger.info(f"Starting CSV processing for upload {csv_upload_id}")
        
        # Import here to avoid circular imports
        from .csv_models import CSVUpload
        from .csv_processor import CSVProcessingEngine
        
        # Get the CSV upload instance
        csv_upload = CSVUpload.objects.get(id=csv_upload_id)
        
        # Create processor and process file
        processor = CSVProcessingEngine(csv_upload)
        result = processor.process_file()
        
        logger.info(f"CSV processing completed for upload {csv_upload_id}")
        logger.info(f"Result: {result}")
        
        return result
        
    except CSVUpload.DoesNotExist:
        logger.error(f"CSVUpload {csv_upload_id} not found")
        return {
            'success': False,
            'error': 'CSV upload not found'
        }
        
    except Exception as exc:
        logger.error(f"CSV processing failed for upload {csv_upload_id}: {str(exc)}")
        
        # Retry with exponential backoff (60s, 120s, 240s)
        retry_countdown = 60 * (2 ** self.request.retries)
        
        logger.info(f"Retrying in {retry_countdown} seconds (attempt {self.request.retries + 1}/3)")
        
        raise self.retry(exc=exc, countdown=retry_countdown)


@shared_task
def cleanup_old_csv_uploads():
    """
    Periodic task to cleanup old CSV uploads (older than 30 days)
    This can be scheduled to run daily via Celery Beat
    """
    from .csv_models import CSVUpload
    
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    old_uploads = CSVUpload.objects.filter(
        created_at__lt=thirty_days_ago,
        status__in=['completed', 'failed', 'partial']
    )
    
    count = old_uploads.count()
    
    # Delete the records and associated files
    for upload in old_uploads:
        try:
            if upload.file:
                upload.file.delete()
        except Exception as e:
            logger.warning(f"Could not delete file for upload {upload.id}: {str(e)}")
    
    old_uploads.delete()
    
    logger.info(f"Cleaned up {count} old CSV uploads")
    
    return {
        'success': True,
        'cleaned': count,
        'cutoff_date': thirty_days_ago.isoformat()
    }


@shared_task(bind=True)
def test_celery_task(self, message="Hello from Celery!"):
    """
    Simple test task to verify Celery is working
    """
    logger.info(f"Test task executed with message: {message}")
    
    return {
        'success': True,
        'message': message,
        'task_id': self.request.id,
        'executed_at': timezone.now().isoformat()
    }

@shared_task
def send_welcome_email_async(user_id, raw_password=None):
    """
    Async task to send welcome email
    """
    try:
        from accounts.models import User
        user = User.objects.get(id=user_id)
        EmailService.send_welcome_email(user, raw_password=raw_password)
        logger.info(f"Welcome email sent to {user.email}")
        return {'success': True, 'email': user.email}
    except Exception as e:
        logger.error(f"Failed to send welcome email: {str(e)}")
        return {'success': False, 'error': str(e)}

@shared_task
def send_otp_email_async(user_id, otp_code):
    """
    Async task to send OTP email
    """
    try:
        from accounts.models import User
        user = User.objects.get(id=user_id)
        EmailService.send_otp_email(user, otp_code)
        logger.info(f"OTP email sent to {user.email}")
        return {'success': True, 'email': user.email}
    except Exception as e:
        logger.error(f"Failed to send OTP email: {str(e)}")
        return {'success': False, 'error': str(e)}

@shared_task
def send_password_reset_email_async(user_id, reset_token):
    """
    Async task to send password reset email
    """
    try:
        from accounts.models import User
        user = User.objects.get(id=user_id)
        EmailService.send_password_reset_email(user, reset_token)
        logger.info(f"Password reset email sent to {user.email}")
        return {'success': True, 'email': user.email}
    except Exception as e:
        logger.error(f"Failed to send password reset email: {str(e)}")
        return {'success': False, 'error': str(e)}

@shared_task
def send_csv_completion_email_async(user_id, csv_upload_id):
    """
    Async task to send CSV completion email
    """
    try:
        from accounts.models import User
        from accounts.csv_models import CSVUpload
        
        user = User.objects.get(id=user_id)
        csv_upload = CSVUpload.objects.get(id=csv_upload_id)
        
        EmailService.send_csv_completion_email(user, csv_upload)
        logger.info(f"CSV completion email sent to {user.email}")
        return {'success': True, 'email': user.email}
    except Exception as e:
        logger.error(f"Failed to send CSV completion email: {str(e)}")
        return {'success': False, 'error': str(e)}    