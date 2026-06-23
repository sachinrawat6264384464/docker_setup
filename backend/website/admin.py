from django.contrib import admin
from .models import SiteContent, Testimonial, ContactLead, FAQItem

admin.site.register(SiteContent)
admin.site.register(Testimonial)
admin.site.register(ContactLead)
admin.site.register(FAQItem)
