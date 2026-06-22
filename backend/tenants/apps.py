# tenants/apps.py
from django.apps import AppConfig

class TenantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tenants'
    verbose_name = 'Tenant Management'
    
    def ready(self):
        """
        Import signals when the app is ready
        """
        try:
            from . import signals  # noqa F401
        except ImportError:
            pass