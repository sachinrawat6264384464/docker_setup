# inspections/apps.py
from django.apps import AppConfig


class InspectionsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inspections'
    verbose_name = 'Inspections'
    
    def ready(self):
        try:
            import inspections.signals  # noqa
        except ImportError:
            pass
