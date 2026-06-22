# propflow/data_export.py - GDPR-compliant tenant data export
"""
Full data export for tenants. Exports all data from all models in the current
tenant schema into a structured JSON archive. Supports both synchronous (small
tenants) and async/Celery (large tenants) modes.

Usage:
    GET  /api/data-export/           → list previous exports
    POST /api/data-export/           → start a new export
    GET  /api/data-export/{id}/      → check status / download

Only master_admin / super_admin / facility_manager can trigger exports.
"""

import json
import os
import tempfile
import zipfile
from datetime import datetime
from io import BytesIO

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.serializers import serialize
from django.db import connection
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from accounts.permissions import (
    HasModulePermission,
    IsFacilityManagerOrAbove,
    user_has_permission,
)

User = get_user_model()

# ── Tenant app labels that should be exported ─────────────────────────────────
EXPORTABLE_APPS = [
    'accounts', 'properties', 'utilities', 'calendar_alerts',
    'maintenance', 'amenities', 'payments', 'notifications',
    'security', 'parking', 'entertainment', 'communication',
    'visitors', 'vendors', 'support', 'reports', 'reservations',
    'inspections',
]


def _get_tenant_models():
    """Return all concrete models from EXPORTABLE_APPS."""
    models = []
    for app_label in EXPORTABLE_APPS:
        try:
            app_config = apps.get_app_config(app_label)
            for model in app_config.get_models():
                if not model._meta.abstract and not model._meta.proxy:
                    models.append(model)
        except LookupError:
            continue
    return models


def _serialize_model(model):
    """Serialize all rows of a model to a list of dicts."""
    try:
        qs = model.objects.all()
        if not qs.exists():
            return []
        # Use Django's JSON serializer, then parse back to dicts
        raw = serialize('json', qs, use_natural_foreign_keys=True)
        return json.loads(raw)
    except Exception as e:
        return [{'_error': str(e), '_model': model._meta.label}]


def generate_export_data():
    """Generate a full export dict for the current tenant schema."""
    schema_name = getattr(connection, 'schema_name', 'unknown')

    export = {
        'meta': {
            'exported_at': timezone.now().isoformat(),
            'schema': schema_name,
            'django_version': __import__('django').get_version(),
            'format_version': '1.0',
        },
        'models': {},
        'summary': {},
    }

    models = _get_tenant_models()
    for model in models:
        label = model._meta.label  # e.g. "accounts.User"
        data = _serialize_model(model)
        export['models'][label] = data
        export['summary'][label] = len(data)

    return export


def create_export_archive(export_data):
    """Create a ZIP archive containing the export JSON."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Main data file
        zf.writestr(
            'export.json',
            json.dumps(export_data, indent=2, default=str, ensure_ascii=False),
        )
        # Summary / manifest
        zf.writestr(
            'manifest.json',
            json.dumps({
                'meta': export_data['meta'],
                'summary': export_data['summary'],
            }, indent=2, default=str),
        )
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════════
# API VIEWS
# ═══════════════════════════════════════════════════════════════════════════════


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated, IsFacilityManagerOrAbove])
def trigger_data_export(request):
    """
    Trigger a full tenant data export.

    Returns a JSON payload with the export metadata and download URL.
    For very large tenants, this could be made async via Celery.
    """
    schema = getattr(connection, 'schema_name', 'unknown')

    # Generate export synchronously (can be made async with Celery for large datasets)
    try:
        export_data = generate_export_data()
        archive = create_export_archive(export_data)

        # Store in media for later download (or serve directly)
        export_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
        os.makedirs(export_dir, exist_ok=True)

        filename = f'export_{schema}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.zip'
        filepath = os.path.join(export_dir, filename)

        with open(filepath, 'wb') as f:
            f.write(archive.read())

        download_url = f'{settings.MEDIA_URL}exports/{filename}'

        return Response({
            'status': 'completed',
            'schema': schema,
            'exported_at': export_data['meta']['exported_at'],
            'summary': export_data['summary'],
            'total_records': sum(export_data['summary'].values()),
            'download_url': download_url,
            'filename': filename,
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({
            'status': 'failed',
            'error': str(e),
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated, IsFacilityManagerOrAbove])
def list_exports(request):
    """List previously generated export files for this tenant."""
    schema = getattr(connection, 'schema_name', 'unknown')
    export_dir = os.path.join(settings.MEDIA_ROOT, 'exports')

    exports = []
    if os.path.exists(export_dir):
        for f in sorted(os.listdir(export_dir), reverse=True):
            if f.startswith(f'export_{schema}_') and f.endswith('.zip'):
                filepath = os.path.join(export_dir, f)
                stat = os.stat(filepath)
                exports.append({
                    'filename': f,
                    'size_bytes': stat.st_size,
                    'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    'download_url': f'{settings.MEDIA_URL}exports/{f}',
                })

    return Response({
        'schema': schema,
        'exports': exports,
        'count': len(exports),
    })


@extend_schema(responses=OpenApiTypes.BINARY)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated, IsFacilityManagerOrAbove])
def download_export(request, filename):
    """Download a specific export file."""
    schema = getattr(connection, 'schema_name', 'unknown')

    # Security: only allow downloading files for current tenant
    if not filename.startswith(f'export_{schema}_'):
        return Response(
            {'error': 'Access denied'},
            status=status.HTTP_403_FORBIDDEN,
        )

    filepath = os.path.join(settings.MEDIA_ROOT, 'exports', filename)
    if not os.path.exists(filepath):
        return Response(
            {'error': 'Export file not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    with open(filepath, 'rb') as f:
        response = HttpResponse(f.read(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated, IsFacilityManagerOrAbove])
def export_user_data(request, user_id=None):
    """
    GDPR: Export all data related to a specific user (right to data portability).
    If user_id is not provided, exports data for the requesting user.
    """
    target_user_id = user_id or str(request.user.id)

    try:
        target_user = User.objects.get(id=target_user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    # Non-admin users can only export their own data
    if str(request.user.id) != target_user_id:
        if request.user.role not in ('master_admin', 'super_admin', 'facility_manager'):
            return Response({'error': 'Can only export your own data'}, status=status.HTTP_403_FORBIDDEN)

    user_data = {
        'meta': {
            'exported_at': timezone.now().isoformat(),
            'user_id': str(target_user.id),
            'gdpr_export': True,
        },
        'user': {
            'username': target_user.username,
            'email': target_user.email,
            'first_name': target_user.first_name,
            'last_name': target_user.last_name,
            'phone': getattr(target_user, 'phone', ''),
            'role': target_user.role,
            'date_joined': target_user.date_joined.isoformat() if target_user.date_joined else None,
            'last_login': target_user.last_login.isoformat() if target_user.last_login else None,
            'is_active': target_user.is_active,
        },
    }

    # Collect user-related data from all models that have FK to User
    models = _get_tenant_models()
    for model in models:
        if model == User:
            continue

        # Find fields that reference User
        user_fields = []
        for field in model._meta.get_fields():
            if hasattr(field, 'related_model') and field.related_model == User:
                if hasattr(field, 'column'):  # FK or OneToOne
                    user_fields.append(field.name)

        for field_name in user_fields:
            try:
                qs = model.objects.filter(**{field_name: target_user})
                if qs.exists():
                    label = f'{model._meta.label}.{field_name}'
                    raw = serialize('json', qs, use_natural_foreign_keys=True)
                    user_data[label] = json.loads(raw)
            except Exception:
                continue

    return Response(user_data)
