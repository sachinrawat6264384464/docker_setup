# utilities/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import UtilityMeterReading
from .billing_service import generate_bill_from_reading

@receiver(post_save, sender=UtilityMeterReading)
def auto_generate_bill(sender, instance, created, **kwargs):
    if created:
        try:
            generate_bill_from_reading(instance)
        except Exception as e:
            # In production, use logging
            print(f"Error auto-generating bill: {e}")
