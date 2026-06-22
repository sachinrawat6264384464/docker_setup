# vendors/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db.models import Avg
from notifications.services import NotificationService
from .models import VendorReview, VendorInsurance, VendorContract, Vendor


@receiver(post_save, sender=VendorReview)
def update_vendor_ratings(sender, instance, created, **kwargs):
    """
    Update vendor average rating when a new review is posted
    """
    if created:
        vendor = instance.vendor
        
        # Recalculate average rating
        reviews = vendor.reviews.all()
        avg_rating = reviews.aggregate(
            avg_overall=Avg('overall_rating')
        )['avg_overall'] or 0
        
        # Update vendor stats
        vendor.average_rating = round(avg_rating, 2)
        vendor.total_reviews = reviews.count()
        vendor.save(update_fields=['average_rating', 'total_reviews'])
        
        # Send notification to vendor
        try:
            from django.contrib.auth import get_user_model
            
            User = get_user_model()
            
            # Notify vendor management (users associated with vendor)
            # This would require a relationship between vendors and users
            # For now, notify all staff
            staff_users = User.objects.filter(is_staff=True)
            
            for user in staff_users:
                NotificationService.send(
                    user=user,
                    title='New Vendor Review',
                    message=f'New review for {vendor.company_name}: {instance.overall_rating}/5 stars',
                    notification_type='vendor',
                    related_object_id=instance.id,
                    priority='low',
                    send_push=True,
                )
        except Exception:
            pass


@receiver(pre_save, sender=VendorInsurance)
def check_insurance_expiry(sender, instance, **kwargs):
    """
    Send notification when insurance is about to expire
    """
    if instance.pk:  # Only for existing records
        from django.utils import timezone
        from datetime import timedelta
        
        days_until_expiry = (instance.expiry_date - timezone.now().date()).days
        
        # Notify if expiring within 30 days
        if 0 <= days_until_expiry <= 30:
            try:
                from django.contrib.auth import get_user_model
                
                User = get_user_model()
                staff_users = User.objects.filter(is_staff=True)
                
                for user in staff_users:
                    NotificationService.send(
                        user=user,
                        title='Vendor Insurance Expiring Soon',
                        message=f'{instance.vendor.company_name} - {instance.get_insurance_type_display()} expires in {days_until_expiry} days',
                        notification_type='vendor',
                        related_object_id=instance.vendor.id,
                        priority='high',
                        send_email=True,
                        send_push=True
                    )
            except ImportError:
                pass


@receiver(pre_save, sender=VendorContract)
def check_contract_expiry(sender, instance, **kwargs):
    """
    Send notification when contract is about to expire
    """
    if instance.pk and instance.end_date:
        from django.utils import timezone
        
        days_until_expiry = (instance.end_date - timezone.now().date()).days
        
        # Notify if expiring within 60 days
        if 0 <= days_until_expiry <= 60:
            try:
                from django.contrib.auth import get_user_model
                
                User = get_user_model()
                staff_users = User.objects.filter(is_staff=True)
                
                for user in staff_users:
                    NotificationService.send(
                        user=user,
                        title='Vendor Contract Expiring Soon',
                        message=f'Contract {instance.contract_number} with {instance.vendor.company_name} expires in {days_until_expiry} days',
                        notification_type='vendor',
                        related_object_id=instance.id,
                        priority='high',
                        send_email=True,
                        send_push=True
                    )
            except ImportError:
                pass


@receiver(post_save, sender=VendorContract)
def notify_contract_activation(sender, instance, created, **kwargs):
    """
    Notify when contract becomes active
    """
    if instance.status == 'active' and not created:
        tracker = getattr(instance, 'tracker', None)
        status_changed = True if tracker is None else tracker.has_changed('status')
        if status_changed:
            try:
                from django.contrib.auth import get_user_model
                
                User = get_user_model()
                staff_users = User.objects.filter(is_staff=True)
                
                for user in staff_users:
                    NotificationService.send(
                        user=user,
                        title='Vendor Contract Activated',
                        message=f'Contract {instance.contract_number} with {instance.vendor.company_name} is now active',
                        notification_type='vendor',
                        related_object_id=instance.id,
                        priority='medium',
                        send_push=True
                    )
            except (ImportError, AttributeError):
                pass


@receiver(post_save, sender=Vendor)
def notify_vendor_verification(sender, instance, created, **kwargs):
    """
    Notify when vendor is verified
    """
    if instance.is_verified and not created:
        try:
            from django.contrib.auth import get_user_model
            
            User = get_user_model()
            staff_users = User.objects.filter(is_staff=True)
            
            for user in staff_users:
                NotificationService.send(
                    user=user,
                    title='Vendor Verified',
                    message=f'{instance.company_name} has been verified and is ready for work',
                    notification_type='vendor',
                    related_object_id=instance.id,
                    priority='low',
                    send_push=True,
                )
        except Exception:
            pass