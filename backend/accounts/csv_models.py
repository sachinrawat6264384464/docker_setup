# accounts/csv_models.py
from django.db import models
from django.conf import settings
import uuid
import json

class CSVUpload(models.Model):
    """
    Track CSV upload attempts and their status
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('partial', 'Partial Success'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='csv_uploads'
    )
    file = models.FileField(upload_to='csv_uploads/')
    original_filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Processing results
    total_rows = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    success_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    warning_count = models.IntegerField(default=0)
    
    # Processing details
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_completed_at = models.DateTimeField(null=True, blank=True)
    processing_time_seconds = models.FloatField(null=True, blank=True)
    
    # Results and errors
    summary = models.JSONField(default=dict, help_text="Processing summary and statistics")
    errors = models.JSONField(default=list, help_text="List of errors encountered")
    warnings = models.JSONField(default=list, help_text="List of warnings")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"CSV Upload: {self.original_filename} by {self.uploaded_by.username}"
    
    @property
    def success_rate(self):
        if self.total_rows > 0:
            return round((self.success_count / self.total_rows) * 100, 2)
        return 0
    
    @property
    def is_processing(self):
        return self.status in ['pending', 'processing']

class CSVRowResult(models.Model):
    """
    Track individual row processing results
    """
    RESULT_CHOICES = [
        ('success', 'Success'),
        ('error', 'Error'),
        ('warning', 'Warning'),
        ('skipped', 'Skipped'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    csv_upload = models.ForeignKey(CSVUpload, on_delete=models.CASCADE, related_name='row_results')
    row_number = models.IntegerField()
    result_type = models.CharField(max_length=20, choices=RESULT_CHOICES)
    
    # Original data
    raw_data = models.JSONField(help_text="Original row data from CSV")
    
    # Processing results
    message = models.TextField(help_text="Success/error/warning message")
    details = models.JSONField(default=dict, help_text="Additional processing details")
    
    # Related objects created
    created_user_id = models.UUIDField(null=True, blank=True, help_text="ID of created user")
    created_building_id = models.UUIDField(null=True, blank=True, help_text="ID of created building")
    created_unit_id = models.UUIDField(null=True, blank=True, help_text="ID of created unit")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['row_number']
        unique_together = ['csv_upload', 'row_number']
    
    def __str__(self):
        return f"Row {self.row_number}: {self.result_type}"

class CSVTemplate(models.Model):
    """
    Store CSV templates for different types of imports
    """
    TEMPLATE_TYPES = [
        ('residents', 'Residents/Tenants'),
        ('buildings', 'Buildings'),
        ('units', 'Units'),
        ('leases', 'Leases'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    template_type = models.CharField(max_length=50, choices=TEMPLATE_TYPES)
    description = models.TextField()
    
    # Template configuration
    required_columns = models.JSONField(help_text="List of required column names")
    optional_columns = models.JSONField(default=list, help_text="List of optional column names")
    column_descriptions = models.JSONField(default=dict, help_text="Column descriptions and examples")
    validation_rules = models.JSONField(default=dict, help_text="Validation rules for each column")
    
    # Template file
    template_file = models.FileField(upload_to='csv_templates/', help_text="Sample CSV file")
    
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['template_type', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.get_template_type_display()})"