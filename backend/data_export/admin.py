from django.contrib import admin
from .models import DataExportRecord


@admin.register(DataExportRecord)
class DataExportAdmin(admin.ModelAdmin):
    list_display = ['id', 'requestedBy', 'format', 'status', 'createdAt']
    list_filter = ['format', 'status']
    search_fields = ['requestedBy']
    readonly_fields = ['createdAt', 'updatedAt', 'file_path', 'error_message']
