# reservations/admin.py
from django.contrib import admin
from .models import ReservableResource, Reservation


@admin.register(ReservableResource)
class ReservableResourceAdmin(admin.ModelAdmin):
    list_display = ['name', 'resource_type', 'capacity', 'is_available', 'is_free', 'hourly_rate', 'requires_approval']
    list_filter = ['resource_type', 'is_available', 'is_free', 'requires_approval']
    search_fields = ['name', 'description', 'location']
    list_editable = ['is_available', 'requires_approval']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ['reservation_number', 'resource', 'reserved_by', 'start_time', 'end_time', 'status', 'total_cost']
    list_filter = ['status', 'resource__resource_type', 'created_at']
    search_fields = ['reservation_number', 'purpose']
    readonly_fields = ['reservation_number', 'checked_in_at', 'checked_out_at', 'cancelled_at', 'created_at', 'updated_at']
    raw_id_fields = ['resource', 'reserved_by', 'approved_by']
    date_hierarchy = 'start_time'
