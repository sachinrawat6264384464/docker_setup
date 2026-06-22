# ========================================
# FILE 1: entertainment/models.py
# ========================================
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid

User = get_user_model()


class Event(models.Model):
    """Community events and activities"""
    EVENT_TYPES = [
        ('party', 'Party'),
        ('festival', 'Festival'),
        ('workshop', 'Workshop'),
        ('movie', 'Movie Screening'),
        ('concert', 'Concert'),
        ('sports', 'Sports Event'),
        ('kids', 'Kids Activity'),
        ('fitness', 'Fitness Class'),
        ('cultural', 'Cultural Event'),
        ('community', 'Community Gathering'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    title = models.CharField(max_length=300)
    description = models.TextField()
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    
    # Timing
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    
    # Location
    venue = models.CharField(max_length=300)
    building = models.CharField(max_length=200, blank=True)
    location_details = models.TextField(blank=True)
    
    # Capacity
    max_attendees = models.IntegerField(validators=[MinValueValidator(1)])
    current_attendees = models.IntegerField(default=0)
    
    # Registration
    requires_registration = models.BooleanField(default=True)
    registration_deadline = models.DateTimeField(null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    ticket_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Media
    banner_image = models.CharField(max_length=500, blank=True)
    images = models.JSONField(default=list, blank=True)
    
    # Organization
    organized_by = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200)
    contact_phone = models.CharField(max_length=20)
    contact_email = models.EmailField()
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Features
    features = models.JSONField(default=list, blank=True)
    requirements = models.TextField(blank=True)
    rules = models.TextField(blank=True)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='events_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', '-start_time']
        indexes = [
            models.Index(fields=['start_date', 'status']),
            models.Index(fields=['event_type']),
        ]

    def __str__(self):
        return f"{self.title} - {self.start_date}"


class EventRegistration(models.Model):
    """Event registrations and attendee tracking"""
    STATUS_CHOICES = [
        ('registered', 'Registered'),
        ('confirmed', 'Confirmed'),
        ('attended', 'Attended'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_registrations')
    
    number_of_guests = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    guest_names = models.JSONField(default=list, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='registered')
    
    # Payment
    payment_status = models.CharField(max_length=20, blank=True)
    payment_reference = models.CharField(max_length=200, blank=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Check-in
    checked_in_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['event', 'user']
        indexes = [
            models.Index(fields=['event', 'status']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.event.title}"


class Club(models.Model):
    """Community clubs and interest groups"""
    CATEGORY_CHOICES = [
        ('sports', 'Sports'),
        ('arts', 'Arts & Crafts'),
        ('music', 'Music'),
        ('dance', 'Dance'),
        ('reading', 'Reading/Book Club'),
        ('fitness', 'Fitness'),
        ('cooking', 'Cooking'),
        ('tech', 'Technology'),
        ('games', 'Games'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    
    # Leadership
    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='clubs_admin')
    members = models.ManyToManyField(User, related_name='clubs_member', blank=True)
    
    # Schedule
    meeting_schedule = models.CharField(max_length=200, blank=True)
    meeting_location = models.CharField(max_length=300, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    max_members = models.IntegerField(default=50, validators=[MinValueValidator(1)])
    
    logo = models.CharField(max_length=500, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['category', 'is_active']),
        ]

    def __str__(self):
        return self.name
    
    def member_count(self):
        """Get current member count"""
        return self.members.count()
    
    def is_full(self):
        """Check if club is at capacity"""
        return self.member_count() >= self.max_members