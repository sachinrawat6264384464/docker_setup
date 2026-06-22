from django.contrib import admin
from .models import PricingPlan, PlanFeature, Subscription

admin.site.register(PricingPlan)
admin.site.register(PlanFeature)
admin.site.register(Subscription)
