# properties/apps.py
from django.apps import AppConfig

class PropertiesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'properties'
    verbose_name = 'Property Management'

    def ready(self):
        import properties.signals  # noqa: F401 — registers all signal receivers
