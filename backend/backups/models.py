from django.db import models


class Backup(models.Model):
    TYPE_CHOICES = [
        ('full', 'Full'),
        ('incremental', 'Incremental'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='full')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    description = models.TextField(blank=True, default='')
    sizeBytes = models.BigIntegerField(default=0)
    file_path = models.CharField(max_length=500, blank=True, default='')
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)
    created_by = models.CharField(max_length=150, blank=True, default='system')
    error_message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-createdAt']
        db_table = 'backups_backup'

    def __str__(self):
        return f"{self.name} ({self.type}) - {self.status}"
