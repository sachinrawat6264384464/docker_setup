from django.db import models


class DataExportRecord(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    FORMAT_CHOICES = [
        ('csv', 'CSV'),
        ('json', 'JSON'),
        ('xlsx', 'Excel'),
    ]

    requestedBy = models.CharField(max_length=150, blank=True, default='')
    dataTypes = models.JSONField(default=list)   # list of strings e.g. ["users", "payments"]
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES, default='csv')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    dateFrom = models.DateField(null=True, blank=True)
    dateTo = models.DateField(null=True, blank=True)
    file_path = models.CharField(max_length=500, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-createdAt']
        db_table = 'data_export_record'

    def __str__(self):
        return f"Export #{self.id} by {self.requestedBy} ({self.status})"
