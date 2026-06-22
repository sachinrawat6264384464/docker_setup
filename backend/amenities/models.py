# amenities/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from datetime import datetime
import uuid
from properties.models import Block

User = get_user_model()


class Amenity(models.Model):
    """Available amenities in the property"""
    AMENITY_TYPES = [
        ('gym', 'Gym/Fitness Center'),
        ('pool', 'Swimming Pool'),
        ('clubhouse', 'Clubhouse'),
        ('playground', 'Playground'),
        ('sports_court', 'Sports Court'),
        ('garden', 'Garden/Park'),
        ('theater', 'Theater/Auditorium'),
        ('conference_room', 'Conference Room'),
        ('game_room', 'Game Room'),
        ('library', 'Library'),
        ('spa', 'Spa/Sauna'),
        ('rooftop', 'Rooftop Terrace'),
        ('bbq_area', 'BBQ Area'),
        ('party_hall', 'Party Hall'),
        ('coworking', 'Co-working Space'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('unavailable', 'Unavailable'),
        ('maintenance', 'Under Maintenance'),
        ('closed', 'Closed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic Information
    name = models.CharField(max_length=200)
    amenity_type = models.CharField(max_length=50, choices=AMENITY_TYPES)
    description = models.TextField(blank=True)
    
    # Location
    building = models.CharField(max_length=200, blank=True)
    floor = models.CharField(max_length=50, blank=True)
    location_details = models.TextField(blank=True)
    
    # Capacity & Size
    capacity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    area_sqft = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Availability
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    is_bookable = models.BooleanField(default=True)
    requires_approval = models.BooleanField(default=False)
    
    # Operating Hours
    operating_hours = models.JSONField(default=dict, blank=True)  # {"monday": {"open": "06:00", "close": "22:00"}}
    is_24_hours = models.BooleanField(default=False)
    closed_days = models.JSONField(default=list, blank=True)  # ["sunday"]
    
    # Booking Rules
    max_booking_duration_hours = models.IntegerField(default=2, validators=[MinValueValidator(1)])
    min_advance_booking_hours = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    max_advance_booking_days = models.IntegerField(default=30, validators=[MinValueValidator(1)])
    bookings_per_user_per_day = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    bookings_per_user_per_month = models.IntegerField(default=10, validators=[MinValueValidator(1)])
    
    # Pricing
    is_paid = models.BooleanField(default=False)
    price_per_hour = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    security_deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    cancellation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Features & Facilities
    features = models.JSONField(default=list, blank=True)  # ["wifi", "ac", "projector"]
    equipment_available = models.JSONField(default=list, blank=True)
    
    # Media
    images = models.JSONField(default=list, blank=True)
    video_url = models.CharField(max_length=500, blank=True)
    
    # Rules & Guidelines
    rules = models.TextField(blank=True)
    guidelines = models.TextField(blank=True)
    
    # Contact
    manager_name = models.CharField(max_length=200, blank=True)
    manager_phone = models.CharField(max_length=20, blank=True)
    manager_email = models.EmailField(blank=True)
    
    # Statistics
    total_bookings = models.IntegerField(default=0)
    active_bookings = models.IntegerField(default=0)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=0.00, 
                                        validators=[MinValueValidator(0), MaxValueValidator(5)])
    review_count = models.IntegerField(default=0)
    
    # Maintenance
    last_maintenance = models.DateField(null=True, blank=True)
    next_maintenance = models.DateField(null=True, blank=True)
    
    # System Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                  related_name='amenities_created', blank=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Amenity'
        verbose_name_plural = 'Amenities'
        indexes = [
            models.Index(fields=['amenity_type', 'status']),
            models.Index(fields=['is_bookable']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_amenity_type_display()})"
    
    def is_available_at(self, date_time):
        """Check if amenity is available at given datetime"""
        if self.status != 'available':
            return False
        
        if not self.is_bookable:
            return False
        
        # Check if it's a closed day
        day_name = date_time.strftime('%A').lower()
        if day_name in self.closed_days:
            return False
        
        if self.is_24_hours:
            return True
        
        # Check operating hours
        if day_name in self.operating_hours:
            hours = self.operating_hours[day_name]
            current_time = date_time.time()
            open_time = datetime.strptime(hours['open'], '%H:%M').time()
            close_time = datetime.strptime(hours['close'], '%H:%M').time()
            return open_time <= current_time <= close_time
        
        return False


class AmenityBlockAssignment(models.Model):
    """Map amenities to one or more allowed property blocks."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name='block_assignments')
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='amenity_assignments')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='amenity_block_assignments_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['block__building__name', 'block__name']
        verbose_name = 'Amenity Block Assignment'
        verbose_name_plural = 'Amenity Block Assignments'
        unique_together = ('amenity', 'block')
        indexes = [
            models.Index(fields=['amenity', 'block']),
            models.Index(fields=['block']),
        ]

    def __str__(self):
        return f"{self.amenity.name} -> {self.block.building.name} / {self.block.name}"


class AmenityBooking(models.Model):
    """Bookings for amenities"""
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ]
    
    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking_number = models.CharField(max_length=50, unique=True)
    
    # Amenity & User
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name='bookings')
    booked_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='amenity_bookings')
    
    # Booking Details
    booking_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    duration_hours = models.DecimalField(max_digits=5, decimal_places=2)
    
    # Attendees
    number_of_people = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    guest_names = models.JSONField(default=list, blank=True)
    
    # Purpose
    purpose = models.TextField()
    special_requirements = models.TextField(blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                   related_name='bookings_approved', blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    # Check-in/Check-out
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                     related_name='amenity_checkins', blank=True)
    
    # Payment
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    booking_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    security_deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    payment_reference = models.CharField(max_length=200, blank=True)
    
    # Cancellation
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                    related_name='bookings_cancelled', blank=True)
    cancellation_reason = models.TextField(blank=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Notes
    notes = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True)
    
    # Reminders
    reminder_sent = models.BooleanField(default=False)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    
    # System Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-booking_date', '-start_time']
        verbose_name = 'Amenity Booking'
        verbose_name_plural = 'Amenity Bookings'
        indexes = [
            models.Index(fields=['booking_number']),
            models.Index(fields=['amenity', 'booking_date']),
            models.Index(fields=['booked_by', 'status']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.booking_number} - {self.amenity.name} - {self.booking_date}"
    
    def save(self, *args, **kwargs):
        if not self.booking_number:
            self.booking_number = self._generate_booking_number()
        
        # Calculate total amount
        if self.amenity.is_paid:
            from decimal import Decimal
            duration = Decimal(str(self.duration_hours))
            self.booking_fee = self.amenity.price_per_hour * duration
            self.security_deposit = self.amenity.security_deposit
            self.total_amount = self.booking_fee + self.security_deposit
        
        super().save(*args, **kwargs)
    
    def _generate_booking_number(self):
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        count = AmenityBooking.objects.filter(
            booking_number__startswith=f'AMN-{date_str}'
        ).count() + 1
        return f'AMN-{date_str}-{count:04d}'


class AmenityReview(models.Model):
    """Reviews and ratings for amenities"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name='reviews')
    booking = models.ForeignKey(AmenityBooking, on_delete=models.CASCADE, related_name='reviews', 
                               null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='amenity_reviews')
    
    # Rating
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    
    # Review
    title = models.CharField(max_length=300, blank=True)
    review = models.TextField()
    
    # Specific Ratings
    cleanliness_rating = models.IntegerField(null=True, blank=True, 
                                            validators=[MinValueValidator(1), MaxValueValidator(5)])
    maintenance_rating = models.IntegerField(null=True, blank=True, 
                                            validators=[MinValueValidator(1), MaxValueValidator(5)])
    staff_rating = models.IntegerField(null=True, blank=True, 
                                       validators=[MinValueValidator(1), MaxValueValidator(5)])
    
    # Media
    photos = models.JSONField(default=list, blank=True)
    
    # Moderation
    is_published = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    moderated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                    related_name='reviews_moderated', blank=True)
    
    # Interaction
    helpful_count = models.IntegerField(default=0)
    
    # Response
    management_response = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                    related_name='review_responses', blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Amenity Review'
        verbose_name_plural = 'Amenity Reviews'
        indexes = [
            models.Index(fields=['amenity', 'rating']),
            models.Index(fields=['is_published']),
        ]

    def __str__(self):
        return f"{self.amenity.name} - {self.rating} stars by {self.user.get_full_name()}"


class AmenityMaintenance(models.Model):
    """Maintenance records for amenities"""
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    MAINTENANCE_TYPES = [
        ('routine', 'Routine Maintenance'),
        ('repair', 'Repair'),
        ('inspection', 'Inspection'),
        ('cleaning', 'Deep Cleaning'),
        ('upgrade', 'Upgrade'),
        ('emergency', 'Emergency'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name='maintenance_records')
    
    # Maintenance Details
    maintenance_type = models.CharField(max_length=50, choices=MAINTENANCE_TYPES)
    title = models.CharField(max_length=300)
    description = models.TextField()
    
    # Scheduling
    scheduled_date = models.DateField()
    scheduled_start = models.TimeField()
    scheduled_end = models.TimeField()
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    
    # Personnel
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                   related_name='amenity_maintenance_assigned', blank=True)
    vendor_name = models.CharField(max_length=200, blank=True)
    vendor_contact = models.CharField(max_length=100, blank=True)
    
    # Cost
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    actual_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Work Details
    work_performed = models.TextField(blank=True)
    parts_replaced = models.JSONField(default=list, blank=True)
    issues_found = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    
    # Documentation
    before_photos = models.JSONField(default=list, blank=True)
    after_photos = models.JSONField(default=list, blank=True)
    documents = models.JSONField(default=list, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)
    
    # Closure
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                    related_name='maintenance_completed', blank=True)
    completion_notes = models.TextField(blank=True)
    
    # Next Maintenance
    next_maintenance_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                  related_name='maintenance_created', blank=True)

    class Meta:
        ordering = ['-scheduled_date']
        verbose_name = 'Amenity Maintenance'
        verbose_name_plural = 'Amenity Maintenance Records'
        indexes = [
            models.Index(fields=['amenity', 'status']),
            models.Index(fields=['scheduled_date']),
        ]

    def __str__(self):
        return f"{self.amenity.name} - {self.maintenance_type} - {self.scheduled_date}"


class AmenityUsageLog(models.Model):
    """Track actual usage of amenities"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name='usage_logs')
    booking = models.ForeignKey(AmenityBooking, on_delete=models.SET_NULL, null=True, 
                               related_name='usage_logs', blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='amenity_usage')
    
    # Usage Details
    entry_time = models.DateTimeField()
    exit_time = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(null=True, blank=True)
    
    # People Count
    people_count = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    
    # Entry Method
    entry_method = models.CharField(max_length=50)  # booking, walk-in, staff
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                   related_name='amenity_access_verified', blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    issues_reported = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-entry_time']
        verbose_name = 'Amenity Usage Log'
        verbose_name_plural = 'Amenity Usage Logs'
        indexes = [
            models.Index(fields=['amenity', 'entry_time']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.amenity.name} - {self.entry_time.strftime('%Y-%m-%d %H:%M')}"


class AmenityRule(models.Model):
    """Rules and regulations for amenities"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name='amenity_rules')
    
    title = models.CharField(max_length=300)
    description = models.TextField()
    
    # Priority & Display
    priority = models.IntegerField(default=0)
    is_mandatory = models.BooleanField(default=False)
    show_at_booking = models.BooleanField(default=True)
    requires_acknowledgment = models.BooleanField(default=False)
    
    # Penalty
    violation_penalty = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    penalty_description = models.TextField(blank=True)
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                  related_name='rules_created', blank=True)

    class Meta:
        ordering = ['-priority', 'title']
        verbose_name = 'Amenity Rule'
        verbose_name_plural = 'Amenity Rules'

    def __str__(self):
        return f"{self.amenity.name} - {self.title}"


class AmenityClass(models.Model):
    """Group classes like Yoga, Zumba, Dance, etc."""
    CLASS_TYPE_CHOICES = [
        ('yoga', 'Yoga'),
        ('zumba', 'Zumba'),
        ('dance', 'Dance'),
        ('fitness', 'Fitness/Aerobics'),
        ('swimming', 'Swimming Lessons'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name='classes')
    
    title = models.CharField(max_length=200)
    class_type = models.CharField(max_length=50, choices=CLASS_TYPE_CHOICES)
    instructor_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Schedule
    start_date = models.DateField()
    end_date = models.DateField()
    days_of_week = models.JSONField(default=list) # [0, 2, 4] for Mon, Wed, Fri
    start_time = models.TimeField()
    end_time = models.TimeField()
    
    # Capacity & Pricing
    max_participants = models.IntegerField(default=20)
    current_participants = models.IntegerField(default=0)
    price_per_session = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} by {self.instructor_name}"

    def generate_pass_id(self, user_id):
        """Generate a unique digital pass ID for a participant"""
        return f"PASS-{str(self.id)[:8]}-{str(user_id)[:4]}"