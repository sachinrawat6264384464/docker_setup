# accounts/csv_admin.py - Admin interface for CSV management
from django.contrib import admin
from django.utils.html import format_html
from django.db import models
from django.forms import Textarea
from .csv_models import CSVUpload, CSVRowResult, CSVTemplate

@admin.register(CSVUpload)
class CSVUploadAdmin(admin.ModelAdmin):
    list_display = [
        'original_filename', 'uploaded_by', 'status_display', 'file_size_display',
        'processing_summary', 'success_rate_display', 'created_at'
    ]
    list_filter = ['status', 'created_at', 'processing_completed_at']
    search_fields = ['original_filename', 'uploaded_by__username', 'uploaded_by__email']
    readonly_fields = [
        'file_size', 'status', 'total_rows', 'processed_rows', 'success_count',
        'error_count', 'warning_count', 'processing_started_at', 'processing_completed_at',
        'processing_time_seconds', 'summary', 'errors', 'warnings', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    fieldsets = (
        ('File Information', {
            'fields': ('uploaded_by', 'file', 'original_filename', 'file_size_display')
        }),
        ('Processing Status', {
            'fields': ('status', 'processing_started_at', 'processing_completed_at', 'processing_time_seconds')
        }),
        ('Results Summary', {
            'fields': ('total_rows', 'processed_rows', 'success_count', 'error_count', 'warning_count'),
            'classes': ('collapse',)
        }),
        ('Detailed Results', {
            'fields': ('summary', 'errors', 'warnings'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    formfield_overrides = {
        models.JSONField: {'widget': Textarea(attrs={'rows': 8, 'cols': 80})},
    }
    
    def status_display(self, obj):
        status_colors = {
            'pending': '#ffc107',
            'processing': '#17a2b8',
            'completed': '#28a745',
            'failed': '#dc3545',
            'partial': '#fd7e14',
        }
        color = status_colors.get(obj.status, '#6c757d')
        
        icon_map = {
            'pending': '⏳',
            'processing': '🔄',
            'completed': '✅',
            'failed': '❌',
            'partial': '⚠️',
        }
        icon = icon_map.get(obj.status, '❓')
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            color, icon, obj.get_status_display()
        )
    status_display.short_description = 'Status'
    
    def file_size_display(self, obj):
        if obj.file_size:
            if obj.file_size < 1024:
                return f"{obj.file_size} B"
            elif obj.file_size < 1024*1024:
                return f"{obj.file_size/1024:.1f} KB"
            else:
                return f"{obj.file_size/(1024*1024):.1f} MB"
        return "Unknown"
    file_size_display.short_description = 'File Size'
    
    def processing_summary(self, obj):
        if obj.total_rows > 0:
            return format_html(
                '<span style="color: #28a745;">✓ {}</span> | '
                '<span style="color: #dc3545;">✗ {}</span> | '
                '<span style="color: #ffc107;">⚠ {}</span> | '
                '<strong>Total: {}</strong>',
                obj.success_count, obj.error_count, obj.warning_count, obj.total_rows
            )
        return "Not processed"
    processing_summary.short_description = 'Results Summary'
    
    def success_rate_display(self, obj):
        rate = obj.success_rate
        if rate >= 90:
            color = '#28a745'
        elif rate >= 70:
            color = '#ffc107'
        else:
            color = '#dc3545'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color, rate
        )
    success_rate_display.short_description = 'Success Rate'
    
    def has_delete_permission(self, request, obj=None):
        # Only allow deletion of completed/failed uploads
        if obj and obj.status in ['pending', 'processing']:
            return False
        return super().has_delete_permission(request, obj)

@admin.register(CSVRowResult)
class CSVRowResultAdmin(admin.ModelAdmin):
    list_display = [
        'csv_upload_filename', 'row_number', 'result_type_display', 
        'message_truncated', 'created_objects', 'created_at'
    ]
    list_filter = ['result_type', 'csv_upload__status', 'created_at']
    search_fields = ['csv_upload__original_filename', 'message', 'raw_data']
    readonly_fields = [
        'csv_upload', 'row_number', 'result_type', 'raw_data', 'message',
        'details', 'created_user_id', 'created_building_id', 'created_unit_id', 'created_at'
    ]
    ordering = ['csv_upload', 'row_number']
    
    fieldsets = (
        ('Upload Information', {
            'fields': ('csv_upload', 'row_number', 'result_type')
        }),
        ('Processing Result', {
            'fields': ('message', 'details')
        }),
        ('Original Data', {
            'fields': ('raw_data',),
            'classes': ('collapse',)
        }),
        ('Created Objects', {
            'fields': ('created_user_id', 'created_building_id', 'created_unit_id'),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )
    
    formfield_overrides = {
        models.JSONField: {'widget': Textarea(attrs={'rows': 6, 'cols': 80})},
    }
    
    def csv_upload_filename(self, obj):
        return obj.csv_upload.original_filename
    csv_upload_filename.short_description = 'CSV File'
    
    def result_type_display(self, obj):
        type_colors = {
            'success': '#28a745',
            'error': '#dc3545',
            'warning': '#ffc107',
            'skipped': '#6c757d',
        }
        color = type_colors.get(obj.result_type, '#6c757d')
        
        type_icons = {
            'success': '✅',
            'error': '❌',
            'warning': '⚠️',
            'skipped': '⏭️',
        }
        icon = type_icons.get(obj.result_type, '❓')
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            color, icon, obj.get_result_type_display()
        )
    result_type_display.short_description = 'Result'
    
    def message_truncated(self, obj):
        if len(obj.message) > 100:
            return obj.message[:100] + '...'
        return obj.message
    message_truncated.short_description = 'Message'
    
    def created_objects(self, obj):
        objects = []
        if obj.created_user_id:
            objects.append('👤 User')
        if obj.created_building_id:
            objects.append('🏢 Building')
        if obj.created_unit_id:
            objects.append('🏠 Unit')
        
        return ', '.join(objects) if objects else 'None'
    created_objects.short_description = 'Created Objects'

@admin.register(CSVTemplate)
class CSVTemplateAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'template_type', 'is_active', 'columns_summary', 
        'created_by', 'created_at'
    ]
    list_filter = ['template_type', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['template_type', 'name']
    
    fieldsets = (
        ('Template Information', {
            'fields': ('name', 'template_type', 'description', 'is_active')
        }),
        ('Column Configuration', {
            'fields': ('required_columns', 'optional_columns', 'column_descriptions')
        }),
        ('Validation Rules', {
            'fields': ('validation_rules',),
            'classes': ('collapse',)
        }),
        ('Template File', {
            'fields': ('template_file',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    formfield_overrides = {
        models.JSONField: {'widget': Textarea(attrs={'rows': 8, 'cols': 80})},
    }
    
    def columns_summary(self, obj):
        required_count = len(obj.required_columns) if obj.required_columns else 0
        optional_count = len(obj.optional_columns) if obj.optional_columns else 0
        
        return format_html(
            '<span style="color: #dc3545; font-weight: bold;">{} required</span> | '
            '<span style="color: #28a745;">{} optional</span>',
            required_count, optional_count
        )
    columns_summary.short_description = 'Columns'
    
    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)