import os
import csv
import json
from django.conf import settings
from django.http import FileResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.utils import OperationalError, ProgrammingError

from .models import DataExportRecord
from .serializers import DataExportRecordSerializer, DataExportCreateSerializer


def _require_super_admin(request):
    role = getattr(request.user, 'role', None)
    if role != 'super_admin':
        return False, Response(
            {'error': 'Super Admin access required.'},
            status=status.HTTP_403_FORBIDDEN
        )
    return True, None


# Map of data type keys to table/model info for export
DATA_TYPE_MAP = {
    'users': 'accounts_user',
    'payments': 'payments_payment',
    'maintenance': 'maintenance_maintenancerequest',
    'properties': 'properties_property',
    'audit_logs': 'accounts_auditlog',
}


def _export_to_csv(data_types, file_path):
    """Create a minimal CSV export from raw SQL for listed data types."""
    from django.db import connection
    with open(file_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for dtype in data_types:
            table = DATA_TYPE_MAP.get(dtype)
            if not table:
                continue
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT * FROM {table} LIMIT 1000")
                    cols = [d[0] for d in cursor.description]
                    writer.writerow([f'--- {dtype} ---'])
                    writer.writerow(cols)
                    writer.writerows(cursor.fetchall())
                    writer.writerow([])
            except Exception:
                writer.writerow([f'--- {dtype}: error reading data ---'])
    return os.path.getsize(file_path)


def _export_to_json(data_types, file_path):
    """Create a JSON export from raw SQL for listed data types."""
    from django.db import connection
    result = {}
    for dtype in data_types:
        table = DATA_TYPE_MAP.get(dtype)
        if not table:
            continue
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {table} LIMIT 1000")
                cols = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
                result[dtype] = [dict(zip(cols, row)) for row in rows]
        except Exception:
            result[dtype] = {'error': 'Could not read data'}
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, default=str)
    return os.path.getsize(file_path)


class DataExportViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return DataExportRecord.objects.all()

    def list(self, request):
        ok, err = _require_super_admin(request)
        if not ok:
            return err
        try:
            qs = DataExportRecord.objects.all()
            return Response(DataExportRecordSerializer(qs, many=True).data)
        except (OperationalError, ProgrammingError):
            return Response([])

    def create(self, request):
        ok, err = _require_super_admin(request)
        if not ok:
            return err

        serializer = DataExportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            record = DataExportRecord.objects.create(
                requestedBy=request.user.username,
                dataTypes=data['dataTypes'],
                format=data.get('format', 'csv'),
                dateFrom=data.get('dateFrom'),
                dateTo=data.get('dateTo'),
                status='processing',
            )
        except (OperationalError, ProgrammingError):
            return Response({'error': 'Database matching table pending. Please run migrations.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Attempt actual export
        try:
            export_dir = os.path.join(settings.BASE_DIR, 'media', 'exports')
            os.makedirs(export_dir, exist_ok=True)
            ext = record.format
            file_path = os.path.join(export_dir, f'export_{record.id}.{ext}')

            if record.format == 'csv':
                _export_to_csv(record.dataTypes, file_path)
            elif record.format == 'json':
                _export_to_json(record.dataTypes, file_path)
            else:
                # xlsx fallback: save as CSV
                _export_to_csv(record.dataTypes, file_path)

            record.file_path = file_path
            record.status = 'completed'
        except Exception as e:
            record.status = 'failed'
            record.error_message = str(e)[:500]

        record.save()
        return Response(DataExportRecordSerializer(record).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        ok, err = _require_super_admin(request)
        if not ok:
            return err
        try:
            record = DataExportRecord.objects.get(pk=pk)
        except DataExportRecord.DoesNotExist:
            return Response({'error': 'Export not found.'}, status=status.HTTP_404_NOT_FOUND)

        if record.status != 'completed' or not record.file_path or not os.path.exists(record.file_path):
            return Response({'error': 'Export file not available.'}, status=status.HTTP_404_NOT_FOUND)

        file_handle = open(record.file_path, 'rb')
        response = FileResponse(file_handle, content_type='application/octet-stream')
        fname = os.path.basename(record.file_path)
        response['Content-Disposition'] = f'attachment; filename="{fname}"'
        return response
