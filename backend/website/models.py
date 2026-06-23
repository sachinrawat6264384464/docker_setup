from django.db import models
import uuid


class SiteContent(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField(default=dict)
    section = models.CharField(max_length=100, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.section}.{self.key}"


class Testimonial(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author_name = models.CharField(max_length=100)
    role = models.CharField(max_length=100)
    company = models.CharField(max_length=100, blank=True)
    content = models.TextField()
    avatar = models.ImageField(upload_to='website/testimonials/', null=True, blank=True)
    rating = models.IntegerField(default=5)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', '-id']

    def __str__(self):
        return f"{self.author_name} - {self.company}"


class ContactLead(models.Model):
    LEAD_TYPES = [
        ('demo', 'Demo Request'),
        ('contact', 'Contact Form'),
        ('enterprise', 'Enterprise Inquiry'),
    ]
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('qualified', 'Qualified'),
        ('converted', 'Converted'),
        ('lost', 'Lost'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    company = models.CharField(max_length=200, blank=True)
    unit_count = models.IntegerField(null=True, blank=True)
    message = models.TextField(blank=True)
    lead_type = models.CharField(max_length=20, choices=LEAD_TYPES, default='contact')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.email}) - {self.lead_type}"


class FAQItem(models.Model):
    question = models.CharField(max_length=300)
    answer = models.TextField()
    category = models.CharField(max_length=100, blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['category', 'order']

    def __str__(self):
        return self.question
