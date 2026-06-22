# utilities/admin.py
from django.contrib import admin
from .models import (
    UtilityType, UtilityBill, UtilityMeterReading,
    UtilityProvider, BuildingUtilityConnection,
    InsuranceProvider, BuildingInsurance
)

@admin.register(UtilityType)
class UtilityTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'unit_of_measurement', 'base_rate', 'is_active', 'created_at']
    list_filter = ['category', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['category', 'name']

@admin.register(UtilityBill)
class UtilityBillAdmin(admin.ModelAdmin):
    list_display = ['bill_number', 'utility_type', 'unit', 'tenant', 'billing_period_start', 'billing_period_end', 'total_amount', 'status', 'due_date']
    list_filter = ['status', 'utility_type', 'billing_period_start', 'due_date']
    search_fields = ['bill_number', 'tenant__first_name', 'tenant__last_name', 'unit__unit_number']
    ordering = ['-billing_period_start']
    readonly_fields = ['bill_number', 'consumption', 'base_amount', 'total_amount']
    
    fieldsets = (
        ('Bill Information', {
            'fields': ('bill_number', 'utility_type', 'unit', 'tenant', 'status')
        }),
        ('Billing Period', {
            'fields': ('billing_period_start', 'billing_period_end', 'due_date')
        }),
        ('Readings', {
            'fields': ('previous_reading', 'current_reading', 'consumption')
        }),
        ('Financial Details', {
            'fields': ('rate_per_unit', 'base_amount', 'tax_amount', 'additional_charges', 'discount', 'total_amount')
        }),
        ('Payment Information', {
            'fields': ('payment_date', 'payment_reference')
        }),
        ('Additional Information', {
            'fields': ('notes', 'generated_by')
        }),
    )

@admin.register(UtilityMeterReading)
class UtilityMeterReadingAdmin(admin.ModelAdmin):
    list_display = ['utility_type', 'unit', 'reading_date', 'reading_value', 'reading_type', 'recorded_by', 'created_at']
    list_filter = ['reading_type', 'utility_type', 'reading_date']
    search_fields = ['meter_number', 'unit__unit_number', 'unit__building__name']
    ordering = ['-reading_date']
    readonly_fields = ['recorded_by']

@admin.register(UtilityProvider)
class UtilityProviderAdmin(admin.ModelAdmin):
    list_display = ['name', 'utility_category', 'contact_person', 'contact_email', 'contact_phone', 'is_active']
    list_filter = ['utility_category', 'is_active']
    search_fields = ['name', 'contact_person', 'contact_email']
    ordering = ['name']

@admin.register(BuildingUtilityConnection)
class BuildingUtilityConnectionAdmin(admin.ModelAdmin):
    list_display = ['building', 'provider', 'utility_type', 'connection_number', 'connection_date', 'is_active']
    list_filter = ['is_active', 'utility_type', 'provider']
    search_fields = ['connection_number', 'meter_number', 'building__name']
    ordering = ['building', 'utility_type']

@admin.register(InsuranceProvider)
class InsuranceProviderAdmin(admin.ModelAdmin):
    list_display = ['name', 'insurance_type', 'contact_person', 'contact_email', 'policy_number', 'is_active', 'policy_end_date']
    list_filter = ['insurance_type', 'is_active']
    search_fields = ['name', 'contact_person', 'contact_email', 'policy_number']
    ordering = ['name']

@admin.register(BuildingInsurance)
class BuildingInsuranceAdmin(admin.ModelAdmin):
    list_display = ['building', 'provider', 'policy_number', 'coverage_amount', 'premium_amount', 'policy_start_date', 'policy_end_date', 'is_active']
    list_filter = ['is_active', 'provider']
    search_fields = ['policy_number', 'building__name', 'provider__name']
    ordering = ['-policy_start_date']
