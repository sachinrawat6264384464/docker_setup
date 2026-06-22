# parking/admin.py
from django.contrib import admin
from .models import ParkingSlot, Vehicle, ParkingPass, ParkingEntry


@admin.register(ParkingSlot)
class ParkingSlotAdmin(admin.ModelAdmin):
    list_display = ['slot_number', 'slot_type', 'status', 'building', 'floor', 'assigned_to']
    list_filter = ['slot_type', 'status', 'building', 'floor']
    search_fields = ['slot_number']


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ['license_plate', 'make', 'model', 'owner', 'vehicle_type', 'is_verified']
    list_filter = ['vehicle_type', 'is_active', 'is_verified']
    search_fields = ['license_plate', 'make', 'model']


@admin.register(ParkingPass)
class ParkingPassAdmin(admin.ModelAdmin):
    list_display = ['pass_number', 'user', 'vehicle', 'valid_from', 'valid_until', 'status']
    list_filter = ['status']
    search_fields = ['pass_number']


@admin.register(ParkingEntry)
class ParkingEntryAdmin(admin.ModelAdmin):
    list_display = ['vehicle', 'entry_time', 'exit_time', 'parking_slot', 'is_authorized']
    list_filter = ['is_authorized']