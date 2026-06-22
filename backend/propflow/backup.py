# propflow/backup.py - Database backup and restore API
"""
Provides backup and restore functionality for the tenant database.

Backup strategies:
  1. Django dumpdata (JSON) — portable, schema-level backup
  2. pg_dump (SQL) — full PostgreSQL dump (requires pg_dump binary)

Security:
  - Only master_admin / super_admin can trigger backups and restores
  - Backups are stored in MEDIA_ROOT/backups/
  - Files are named with schema + timestamp for isolation
"""

import json
import os
import subprocess
import time
from datetime import datetime
from io import BytesIO, StringIO

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from accounts.permissions import IsSuperAdminOrAbove

# ── Tenant app labels to backup ───────────────────────────────────────────────
BACKUP_APPS = [
    'accounts', 'properties', 'utilities', 'calendar_alerts',
    'maintenance', 'amenities', 'payments', 'notifications',
    'security', 'parking', 'entertainment', 'communication',
    'visitors', 'vendors', 'support', 'reports', 'reservations',
    'inspections',
]


def _get_backup_dir():
    """Get or create the backups directory."""
    backup_dir = os.path.join(settings.MEDIA_ROOT, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP
# ═══════════════════════════════════════════════════════════════════════════════

@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated, IsSuperAdminOrAbove])
def create_backup(request):
    """
    Create a JSON backup of the current tenant's data using Django dumpdata.

    Returns backup metadata and download URL.
    """
    schema = getattr(connection, 'schema_name', 'unknown')
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    filename = f'backup_{schema}_{timestamp}.json'
    backup_dir = _get_backup_dir()
    filepath = os.path.join(backup_dir, filename)

    try:
        start_time = time.monotonic()

        # Use dumpdata management command
        output = StringIO()
        call_command(
            'dumpdata',
            *BACKUP_APPS,
            '--indent', '2',
            '--natural-foreign',
            '--natural-primary',
            stdout=output,
        )

        data = output.getvalue()
        duration = round(time.monotonic() - start_time, 2)

        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(data)

        file_size = os.path.getsize(filepath)

        # Parse to count records
        parsed = json.loads(data)
        record_count = len(parsed) if isinstance(parsed, list) else 0

        return Response({
            'status': 'completed',
            'schema': schema,
            'filename': filename,
            'file_size_bytes': file_size,
            'record_count': record_count,
            'duration_seconds': duration,
            'created_at': timezone.now().isoformat(),
            'download_url': f'{settings.MEDIA_URL}backups/{filename}',
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({
            'status': 'failed',
            'error': str(e),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated, IsSuperAdminOrAbove])
def list_backups(request):
    """List all available backups for the current tenant."""
    schema = getattr(connection, 'schema_name', 'unknown')
    backup_dir = _get_backup_dir()

    backups = []
    if os.path.exists(backup_dir):
        for f in sorted(os.listdir(backup_dir), reverse=True):
            if f.startswith(f'backup_{schema}_') and f.endswith('.json'):
                filepath = os.path.join(backup_dir, f)
                stat = os.stat(filepath)
                backups.append({
                    'filename': f,
                    'size_bytes': stat.st_size,
                    'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    'download_url': f'{settings.MEDIA_URL}backups/{f}',
                })

    return Response({
        'schema': schema,
        'backups': backups,
        'count': len(backups),
    })


@extend_schema(responses=OpenApiTypes.BINARY)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated, IsSuperAdminOrAbove])
def download_backup(request, filename):
    """Download a specific backup file."""
    schema = getattr(connection, 'schema_name', 'unknown')

    # Security: only allow downloading backups for current tenant
    if not filename.startswith(f'backup_{schema}_'):
        return Response(
            {'error': 'Access denied'},
            status=status.HTTP_403_FORBIDDEN,
        )

    filepath = os.path.join(_get_backup_dir(), filename)
    if not os.path.exists(filepath):
        return Response(
            {'error': 'Backup file not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    with open(filepath, 'rb') as f:
        response = HttpResponse(f.read(), content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# ═══════════════════════════════════════════════════════════════════════════════
# RESTORE
# ═══════════════════════════════════════════════════════════════════════════════

@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated, IsSuperAdminOrAbove])
def restore_backup(request):
    """
    Restore data from a previously created backup.

    Body: {"filename": "backup_tenant1_20240101_120000.json"}

    WARNING: This will load data into the current schema. Existing data
    for conflicting primary keys will be updated (loaddata default behaviour).
    """
    filename = request.data.get('filename')
    if not filename:
        return Response(
            {'error': 'filename is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    schema = getattr(connection, 'schema_name', 'unknown')

    # Security: only allow restoring backups from current tenant
    if not filename.startswith(f'backup_{schema}_'):
        return Response(
            {'error': 'Access denied — can only restore backups from this tenant'},
            status=status.HTTP_403_FORBIDDEN,
        )

    filepath = os.path.join(_get_backup_dir(), filename)
    if not os.path.exists(filepath):
        return Response(
            {'error': 'Backup file not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        start_time = time.monotonic()

        # Validate JSON before loading
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        record_count = len(data) if isinstance(data, list) else 0

        # Use loaddata management command
        call_command('loaddata', filepath, verbosity=0)

        duration = round(time.monotonic() - start_time, 2)

        return Response({
            'status': 'completed',
            'schema': schema,
            'filename': filename,
            'records_restored': record_count,
            'duration_seconds': duration,
            'restored_at': timezone.now().isoformat(),
        })

    except json.JSONDecodeError as e:
        return Response({
            'status': 'failed',
            'error': f'Invalid backup file: {str(e)}',
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({
            'status': 'failed',
            'error': str(e),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated, IsSuperAdminOrAbove])
def delete_backup(request, filename):
    """Delete a specific backup file."""
    schema = getattr(connection, 'schema_name', 'unknown')

    if not filename.startswith(f'backup_{schema}_'):
        return Response(
            {'error': 'Access denied'},
            status=status.HTTP_403_FORBIDDEN,
        )

    filepath = os.path.join(_get_backup_dir(), filename)
    if not os.path.exists(filepath):
        return Response(
            {'error': 'Backup file not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    os.remove(filepath)
    return Response({'status': 'deleted', 'filename': filename})
