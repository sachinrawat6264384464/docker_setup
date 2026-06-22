# support/apps.py
from django.apps import AppConfig


class SupportConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'support'
    verbose_name = 'Support'
    
    def ready(self):
        try:
            import support.signals  # noqa
        except ImportError:
            pass
