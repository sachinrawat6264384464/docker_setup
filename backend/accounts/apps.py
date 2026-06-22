# accounts/apps.py
from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "User Management"
    
    def ready(self):
        try:
            from . import signals  # noqa F401
        except ImportError:
            pass