from django.apps import AppConfig


class EntertainmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "entertainment"

    def ready(self):
        import entertainment.signals
