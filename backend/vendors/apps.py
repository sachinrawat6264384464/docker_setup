# vendors/apps.py
from django.apps import AppConfig


class VendorsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'vendors'
    verbose_name = 'Vendors'
    
    def ready(self):
        try:
            import vendors.signals  # noqa
        except ImportError:
            pass
