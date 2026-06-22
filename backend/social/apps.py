import os
from django.apps import AppConfig

class SocialConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'social'
    path = os.path.dirname(os.path.abspath(__file__))
