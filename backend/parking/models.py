# parking/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
import uuid

User = get_user_model()


class ParkingSlot(models.Model):
    SLOT_TYPES = [
        ('car', 'Car'),
        ('bike', 'Motorcycle/Bike'),
        ('visitor', 'Visitor'),
        ('disabled', 'Disabled'),
        ('electric', 'Electric Vehicle'),
        ('vip', 'VIP'),
    ]
    
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('occupied', 'Occupied'),
        ('reserved', 'Reserved'),
        ('maintenance', 'Under Maintenance'),
        ('disabled', 'Disabled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    slot_number = models.CharField(max_length=50, unique=True)
    slot_type = models.CharField(max_length=50, choices=SLOT_TYPES)
    
    building = models.CharField(max_length=200, blank=True)
    floor = models.CharField(max_length=50)
    section = models.CharField(max_length=50, blank=True)
    location_details = models.TextField(blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    
    # Assignment
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='parking_slots')
    assigned_vehicle = models.ForeignKey('Vehicle', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_slot')
    
    # Features
    has_ev_charger = models.BooleanField(default=False)
    is_covered = models.BooleanField(default=False)
    has_camera = models.BooleanField(default=False)
    
    # Pricing
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['floor', 'slot_number']
        indexes = [
            models.Index(fields=['slot_number']),
            models.Index(fields=['status', 'slot_type']),
        ]

    def __str__(self):
        return f"{self.slot_number} - {self.get_slot_type_display()}"


class Vehicle(models.Model):
    VEHICLE_TYPES = [
        ('car', 'Car'),
        ('suv', 'SUV'),
        ('motorcycle', 'Motorcycle'),
        ('scooter', 'Scooter'),
        ('bicycle', 'Bicycle'),
        ('electric', 'Electric Vehicle'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vehicles')
    
    vehicle_type = models.CharField(max_length=50, choices=VEHICLE_TYPES)
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    year = models.IntegerField(validators=[MinValueValidator(1900)])
    color = models.CharField(max_length=50)
    
    license_plate = models.CharField(max_length=50, unique=True)
    
    # Registration
    registration_number = models.CharField(max_length=100)
    registration_expiry = models.DateField(null=True, blank=True)
    insurance_number = models.CharField(max_length=100, blank=True)
    insurance_expiry = models.DateField(null=True, blank=True)
    
    # Documents
    registration_document = models.CharField(max_length=500, blank=True)
    insurance_document = models.CharField(max_length=500, blank=True)
    
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.make} {self.model} - {self.license_plate}"


class ParkingPass(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('revoked', 'Revoked'),
        ('suspended', 'Suspended'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pass_number = models.CharField(max_length=50, unique=True)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='parking_passes')
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='passes')
    parking_slot = models.ForeignKey(ParkingSlot, on_delete=models.SET_NULL, null=True, blank=True)
    
    valid_from = models.DateField()
    valid_until = models.DateField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    qr_code = models.CharField(max_length=500, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.pass_number} - {self.vehicle.license_plate}"


class ParkingEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='parking_entries')
    parking_slot = models.ForeignKey(ParkingSlot, on_delete=models.SET_NULL, null=True)
    parking_pass = models.ForeignKey(ParkingPass, on_delete=models.SET_NULL, null=True, blank=True)
    
    entry_time = models.DateTimeField(auto_now_add=True)
    exit_time = models.DateTimeField(null=True, blank=True)
    
    entry_gate = models.CharField(max_length=100)
    exit_gate = models.CharField(max_length=100, blank=True)
    
    is_authorized = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-entry_time']

    def __str__(self):
        return f"{self.vehicle.license_plate} - {self.entry_time}"