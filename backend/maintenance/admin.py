# maintenance/admin.py
from django.contrib import admin
from .models import MaintenanceRequest, MaintenanceSchedule, Vendor


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ['request_number', 'title', 'category', 'priority', 'status', 'requested_by']
    list_filter = ['category', 'status', 'priority']
    search_fields = ['request_number', 'title', 'description']
    readonly_fields = ['request_number']


@admin.register(MaintenanceSchedule)
class MaintenanceScheduleAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'frequency', 'next_due_date', 'is_active']
    list_filter = ['category', 'frequency', 'is_active']


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ['name', 'service_type', 'contact_person', 'phone', 'rating', 'is_active']
    list_filter = ['service_type', 'is_active']
    search_fields = ['name', 'contact_person']