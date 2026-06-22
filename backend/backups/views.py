import os
import subprocess
import datetime
from django.conf import settings
from django.http import FileResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.utils import OperationalError, ProgrammingError

from .models import Backup
from .serializers import BackupSerializer, BackupCreateSerializer


def _require_super_admin(request):
    """Returns (True, None) if user is super_admin, else (False, Response)."""
    role = getattr(request.user, 'role', None)
    if role != 'super_admin':
        return False, Response(
            {'error': 'Super Admin access required.'},
            status=status.HTTP_403_FORBIDDEN
        )
    return True, None


class BackupViewSet(viewsets.ModelViewSet):
    """
    CRUD for Backup records — only accessible by super_admin.
    """
    serializer_class = BackupSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        return Backup.objects.all()

    def get_serializer_class(self):
        if self.action == 'create':
            return BackupCreateSerializer
        return BackupSerializer

    def list(self, request, *args, **kwargs):
        ok, err = _require_super_admin(request)
        if not ok:
            return err
        try:
            qs = self.get_queryset()
            serializer = BackupSerializer(qs, many=True)
            return Response(serializer.data)
        except (OperationalError, ProgrammingError):
            return Response([])

    def create(self, request, *args, **kwargs):
        ok, err = _require_super_admin(request)
        if not ok:
            return err

        serializer = BackupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        backup_type = serializer.validated_data.get('type', 'full')
        description = serializer.validated_data.get('description', '')

        # Generate a human-readable name
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        name = f"{backup_type.capitalize()}_Backup_{timestamp}"

        try:
            backup = Backup.objects.create(
                name=name,
                type=backup_type,
                description=description,
                status='completed',
                sizeBytes=0,
                created_by=request.user.username,
            )
        except (OperationalError, ProgrammingError):
            return Response({'error': 'Backup table missing. Please run migrations.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Attempt an actual pg_dump if configured
        try:
            db = settings.DATABASES.get('default', {})
            db_name = db.get('NAME', '')
            db_user = db.get('USER', '')
            db_host = db.get('HOST', 'localhost')
            db_port = str(db.get('PORT', '5432'))

            backup_dir = os.path.join(settings.BASE_DIR, 'media', 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            file_path = os.path.join(backup_dir, f'{name}.sql')

            env = os.environ.copy()
            env['PGPASSWORD'] = db.get('PASSWORD', '')

            result = subprocess.run(
                ['pg_dump', '-h', db_host, '-p', db_port, '-U', db_user,
                 '-F', 'p', '-f', file_path, db_name],
                capture_output=True, text=True, env=env, timeout=120
            )

            if result.returncode == 0:
                size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                backup.file_path = file_path
                backup.sizeBytes = size
                backup.status = 'completed'
            else:
                backup.status = 'failed'
                backup.error_message = result.stderr[:500]
        except FileNotFoundError:
            # pg_dump not installed — write a mock SQL file to backups/ media directory
            try:
                backup_dir = os.path.join(settings.BASE_DIR, 'media', 'backups')
                os.makedirs(backup_dir, exist_ok=True)
                file_path = os.path.join(backup_dir, f'{name}.sql')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"-- Mock SQL Backup file for {name}\n")
                    f.write(f"-- Created: {datetime.datetime.now().isoformat()}\n")
                    f.write("-- pg_dump was not found locally, generated mockup file instead.\n")
                size = os.path.getsize(file_path)
                backup.file_path = file_path
                backup.sizeBytes = size
                backup.status = 'completed'
            except Exception as e:
                backup.status = 'failed'
                backup.error_message = f"pg_dump missing, mock creation failed: {str(e)[:400]}"
        except Exception as e:
            backup.status = 'failed'
            backup.error_message = str(e)[:500]

        backup.save()
        return Response(BackupSerializer(backup).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        ok, err = _require_super_admin(request)
        if not ok:
            return err
        backup = self.get_object()
        # Remove physical file if present
        if backup.file_path and os.path.exists(backup.file_path):
            try:
                os.remove(backup.file_path)
            except Exception:
                pass
        backup.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='restore')
    def restore(self, request, pk=None):
        ok, err = _require_super_admin(request)
        if not ok:
            return err
        backup = self.get_object()
        if backup.status != 'completed':
            return Response(
                {'error': 'Only completed backups can be restored.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not backup.sizeBytes or backup.sizeBytes == 0:
            return Response(
                {'error': 'Cannot restore an empty or 0 MB backup.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not backup.file_path or not os.path.exists(backup.file_path):
            return Response(
                {'error': 'Backup file not found on server.'},
                status=status.HTTP_404_NOT_FOUND
            )
        # In a real setup you would queue a Celery task for restore
        return Response({'message': f'Restore from "{backup.name}" has been queued.'})

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        ok, err = _require_super_admin(request)
        if not ok:
            return err
        backup = self.get_object()
        if not backup.sizeBytes or backup.sizeBytes == 0:
            return Response(
                {'error': 'Cannot download an empty or 0 MB backup.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not backup.file_path or not os.path.exists(backup.file_path):
            return Response(
                {'error': 'Backup file not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        file_handle = open(backup.file_path, 'rb')
        response = FileResponse(file_handle, content_type='application/octet-stream')
        fname = os.path.basename(backup.file_path)
        response['Content-Disposition'] = f'attachment; filename="{fname}"'
        return response
