from django.contrib import admin
from .models import Backup


@admin.register(Backup)
class BackupAdmin(admin.ModelAdmin):
    list_display = ['name', 'type', 'status', 'sizeBytes', 'createdAt', 'created_by']
    list_filter = ['type', 'status']
    search_fields = ['name', 'description', 'created_by']
    readonly_fields = ['createdAt', 'updatedAt', 'sizeBytes', 'file_path', 'error_message']
