# properties/admin.py
from django.contrib import admin
from .models import Building, Unit, Lease, PropertyDocument

@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ['name', 'building_type', 'city', 'state', 'total_floors', 'total_units', 'created_at']
    list_filter = ['building_type', 'city', 'state', 'country']
    search_fields = ['name', 'address', 'city', 'state']
    ordering = ['name']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'building_type', 'description')
        }),
        ('Location', {
            'fields': ('address', 'city', 'state', 'postal_code', 'country')
        }),
        ('Building Details', {
            'fields': ('total_floors', 'total_units', 'year_built', 'amenities')
        }),
    )

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ['unit_number', 'building', 'floor', 'unit_type', 'status', 'monthly_rent', 'created_at']
    list_filter = ['status', 'unit_type', 'building', 'floor']
    search_fields = ['unit_number', 'building__name']
    ordering = ['building', 'floor', 'unit_number']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('building', 'unit_number', 'floor', 'unit_type', 'status')
        }),
        ('Owner Info', {
            'fields': ('owner_user', 'owner_first_name', 'owner_last_name', 'owner_email', 'owner_phone', 'owner_address')
        }),
        ('Unit Details', {
            'fields': ('area_sqft', 'bedrooms', 'bathrooms', 'balconies', 'features', 'description')
        }),
        ('Pricing', {
            'fields': ('monthly_rent', 'security_deposit', 'maintenance_charge')
        }),
    )

@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = ['unit', 'tenant', 'start_date', 'end_date', 'status', 'monthly_rent', 'created_at']
    list_filter = ['status', 'start_date', 'end_date']
    search_fields = ['tenant__first_name', 'tenant__last_name', 'tenant__email', 'unit__unit_number']
    ordering = ['-start_date']
    
    fieldsets = (
        ('Lease Information', {
            'fields': ('unit', 'tenant', 'status')
        }),
        ('Duration', {
            'fields': ('start_date', 'end_date')
        }),
        ('Financial Terms', {
            'fields': ('monthly_rent', 'security_deposit', 'maintenance_charge')
        }),
        ('Additional Information', {
            'fields': ('terms_and_conditions', 'notes', 'created_by')
        }),
    )
    
    readonly_fields = ['created_by']

@admin.register(PropertyDocument)
class PropertyDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'document_type', 'building', 'unit', 'uploaded_by', 'uploaded_at']
    list_filter = ['document_type', 'uploaded_at']
    search_fields = ['title', 'description', 'building__name', 'unit__unit_number']
    ordering = ['-uploaded_at']
    
    fieldsets = (
        ('Document Information', {
            'fields': ('title', 'document_type', 'file', 'description')
        }),
        ('Associated With', {
            'fields': ('building', 'unit', 'lease')
        }),
        ('Metadata', {
            'fields': ('uploaded_by',)
        }),
    )
    
    readonly_fields = ['uploaded_by']
