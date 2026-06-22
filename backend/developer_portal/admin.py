from django.contrib import admin
from .models import APIKey, WebhookEndpoint, WebhookDelivery, APIGuide, APIChangelog

admin.site.register(APIKey)
admin.site.register(WebhookEndpoint)
admin.site.register(WebhookDelivery)
admin.site.register(APIGuide)
admin.site.register(APIChangelog)
