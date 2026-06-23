# visitors/apps.py
from django.apps import AppConfig


class VisitorsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'visitors'
    verbose_name = 'Visitors'
    
    def ready(self):
        try:
            import visitors.signals  # noqa
        except ImportError:
            pass
