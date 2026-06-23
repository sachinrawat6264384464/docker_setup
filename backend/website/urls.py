from django.urls import path
from .views import (
    SiteConfigView,
    SiteContentView,
    TestimonialListView,
    AdminTestimonialListCreateView,
    AdminTestimonialDetailView,
    ContactLeadCreateView,
    FAQListView,
    AdminFAQListCreateView,
    AdminFAQDetailView,
    AdminLeadsView,
    AdminLeadDetailView,
    AdminSiteContentUpdateView,
)

urlpatterns = [
    # Public endpoints
    path('config/', SiteConfigView.as_view(), name='site-config'),
    path('content/', SiteContentView.as_view(), name='site-content'),
    path('testimonials/', TestimonialListView.as_view(), name='testimonials'),
    path('contact/', ContactLeadCreateView.as_view(), name='contact-lead'),
    path('faq/', FAQListView.as_view(), name='faq'),

    # Admin endpoints
    path('admin/config/', SiteConfigView.as_view(), name='admin-site-config'),
    path('admin/content/', AdminSiteContentUpdateView.as_view(), name='admin-content'),
    path('admin/leads/', AdminLeadsView.as_view(), name='admin-leads'),
    path('admin/leads/<uuid:pk>/', AdminLeadDetailView.as_view(), name='admin-lead-detail'),
    path('admin/testimonials/', AdminTestimonialListCreateView.as_view(), name='admin-testimonials'),
    path('admin/testimonials/<uuid:pk>/', AdminTestimonialDetailView.as_view(), name='admin-testimonial-detail'),
    path('admin/faq/', AdminFAQListCreateView.as_view(), name='admin-faq'),
    path('admin/faq/<int:pk>/', AdminFAQDetailView.as_view(), name='admin-faq-detail'),
]
