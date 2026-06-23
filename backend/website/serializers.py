from rest_framework import serializers
from .models import SiteContent, Testimonial, ContactLead, FAQItem


class SiteContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteContent
        fields = ['key', 'value', 'section', 'last_updated']


class TestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = ['id', 'author_name', 'role', 'company', 'content', 'avatar', 'rating']


class ContactLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactLead
        fields = ['name', 'email', 'phone', 'company', 'unit_count', 'message', 'lead_type']


class ContactLeadAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactLead
        fields = [
            'id', 'name', 'email', 'phone', 'company', 'unit_count',
            'message', 'lead_type', 'status', 'created_at',
        ]
        read_only_fields = [
            'id', 'name', 'email', 'phone', 'company', 'unit_count',
            'message', 'lead_type', 'created_at',
        ]


class FAQItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQItem
        fields = ['id', 'question', 'answer', 'category', 'order']
