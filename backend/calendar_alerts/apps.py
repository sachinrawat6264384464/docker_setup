# calendar/apps.py
from django.apps import AppConfig

class CalendarConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'calendar_alerts'
    verbose_name = 'Calendar & Alerts'
