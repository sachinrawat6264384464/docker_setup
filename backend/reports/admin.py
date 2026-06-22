# reports/admin.py
from django.contrib import admin
from .models import ReportTemplate, GeneratedReport, ScheduledReport


@admin.register(ReportTemplate)
class ReportTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'report_type', 'is_system', 'is_active', 'sort_order', 'created_at']
    list_filter = ['report_type', 'is_system', 'is_active']
    search_fields = ['name', 'description']
    list_editable = ['sort_order', 'is_active']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(GeneratedReport)
class GeneratedReportAdmin(admin.ModelAdmin):
    list_display = ['report_number', 'name', 'report_type', 'output_format', 'status', 'created_by', 'created_at']
    list_filter = ['status', 'report_type', 'output_format', 'created_at']
    search_fields = ['report_number', 'name']
    readonly_fields = ['report_number', 'file_size', 'row_count', 'created_at', 'updated_at']
    raw_id_fields = ['created_by', 'template']
    date_hierarchy = 'created_at'


@admin.register(ScheduledReport)
class ScheduledReportAdmin(admin.ModelAdmin):
    list_display = ['name', 'frequency', 'output_format', 'is_active', 'next_run_at', 'last_run_at']
    list_filter = ['frequency', 'is_active']
    search_fields = ['name']
    readonly_fields = ['last_run_at', 'next_run_at', 'created_at']
    raw_id_fields = ['template', 'created_by']
