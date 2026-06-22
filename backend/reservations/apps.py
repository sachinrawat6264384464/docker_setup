# reservations/apps.py
from django.apps import AppConfig


class ReservationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reservations'
    verbose_name = 'Reservations'
    
    def ready(self):
        try:
            import reservations.signals  # noqa
        except ImportError:
            pass
