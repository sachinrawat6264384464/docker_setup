# amenities/admin.py
from django.contrib import admin
from .models import Amenity, AmenityBooking, AmenityReview, AmenityMaintenance, AmenityUsageLog, AmenityRule


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ['name', 'amenity_type', 'status', 'building', 'is_bookable', 'capacity', 'rating_average']
    list_filter = ['amenity_type', 'status', 'is_bookable', 'building']
    search_fields = ['name', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at', 'total_bookings', 'active_bookings', 'rating_average', 'review_count']


@admin.register(AmenityBooking)
class AmenityBookingAdmin(admin.ModelAdmin):
    list_display = ['booking_number', 'amenity', 'booked_by', 'booking_date', 'start_time', 'status', 'payment_status']
    list_filter = ['status', 'payment_status', 'booking_date', 'amenity']
    search_fields = ['booking_number', 'purpose']
    readonly_fields = ['id', 'booking_number', 'created_at', 'updated_at']
    date_hierarchy = 'booking_date'


@admin.register(AmenityReview)
class AmenityReviewAdmin(admin.ModelAdmin):
    list_display = ['amenity', 'user', 'rating', 'is_published', 'created_at']
    list_filter = ['rating', 'is_published', 'is_featured']
    search_fields = ['title', 'review']
    readonly_fields = ['id', 'created_at', 'updated_at', 'helpful_count']


@admin.register(AmenityMaintenance)
class AmenityMaintenanceAdmin(admin.ModelAdmin):
    list_display = ['amenity', 'maintenance_type', 'scheduled_date', 'status']
    list_filter = ['maintenance_type', 'status', 'scheduled_date']
    search_fields = ['title', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(AmenityUsageLog)
class AmenityUsageLogAdmin(admin.ModelAdmin):
    list_display = ['amenity', 'user', 'entry_time', 'exit_time', 'people_count']
    list_filter = ['amenity', 'entry_method']
    readonly_fields = ['id', 'created_at']


@admin.register(AmenityRule)
class AmenityRuleAdmin(admin.ModelAdmin):
    list_display = ['amenity', 'title', 'is_mandatory', 'is_active', 'priority']
    list_filter = ['is_mandatory', 'is_active']
    search_fields = ['title', 'description']