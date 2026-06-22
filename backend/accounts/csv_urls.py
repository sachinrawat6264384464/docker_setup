# accounts/csv_urls.py - CSV Upload URL Configuration
from django.urls import path
from . import csv_views
from .bulk_upload_view import bulk_upload_residents, download_bulk_template

urlpatterns = [
    # ── SMART BULK UPLOAD (synchronous, auto-creates hierarchy) ──
    path('bulk-upload/', bulk_upload_residents, name='csv-bulk-upload'),
    path('template/', download_bulk_template, name='csv-bulk-template'),

    # ── Legacy CSV Upload and Processing (async/Celery) ──
    path('upload/', csv_views.upload_csv_file, name='csv-upload'),
    path('status/<uuid:upload_id>/', csv_views.get_upload_status, name='csv-upload-status'),
    path('results/<uuid:upload_id>/', csv_views.get_upload_results, name='csv-upload-results'),
    path('list/', csv_views.list_csv_uploads, name='csv-upload-list'),
    path('delete/<uuid:upload_id>/', csv_views.delete_csv_upload, name='csv-upload-delete'),
    path('retry/<uuid:upload_id>/', csv_views.retry_csv_processing, name='csv-upload-retry'),
    path('task-status/<str:task_id>/', csv_views.get_task_status, name='csv-task-status'),

    # ── Templates and Downloads ──
    path('template/download/', csv_views.download_csv_template, name='csv-template-download'),
    path('templates/', csv_views.get_csv_templates, name='csv-templates'),

    # ── Statistics ──
    path('stats/', csv_views.csv_processing_stats, name='csv-processing-stats'),
]