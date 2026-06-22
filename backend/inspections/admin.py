# inspections/admin.py
from django.contrib import admin
from .models import InspectionTemplate, Inspection, InspectionPhoto


@admin.register(InspectionTemplate)
class InspectionTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'inspection_type', 'is_active', 'created_at']
    list_filter = ['inspection_type', 'is_active']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ['inspection_number', 'inspection_type', 'status', 'result', 'inspector', 'scheduled_date', 'follow_up_required']
    list_filter = ['status', 'result', 'inspection_type', 'follow_up_required', 'scheduled_date']
    search_fields = ['inspection_number', 'location_description', 'overall_notes']
    readonly_fields = ['inspection_number', 'completed_date', 'created_at', 'updated_at']
    raw_id_fields = ['template', 'inspector', 'requested_by']
    date_hierarchy = 'scheduled_date'


@admin.register(InspectionPhoto)
class InspectionPhotoAdmin(admin.ModelAdmin):
    list_display = ['inspection', 'caption', 'checklist_item_index', 'uploaded_by', 'created_at']
    list_filter = ['created_at']
    raw_id_fields = ['inspection', 'uploaded_by']
    readonly_fields = ['created_at']
