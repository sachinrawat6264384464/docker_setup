import csv
from django.http import HttpResponse
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.apps import apps
from django.db.models import Q

import logging
logger = logging.getLogger(__name__)

class BulkExportViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        return Response({'message': 'Bulk Export API is active. Use /api/export/<module_key>/ to export data.'})

    def _get_model_for_module(self, module_key):
        """Map module keys from frontend to actual Django models."""
        mapping = {
            'units': ('properties', 'Unit'),
            'unit': ('properties', 'Unit'),
            'buildings': ('properties', 'Building'),
            'building': ('properties', 'Building'),
            'blocks': ('properties', 'Block'),
            'block': ('properties', 'Block'),
            'communities': ('properties', 'Township'),
            'colony': ('properties', 'Township'),
            'people-hub': ('accounts', 'User'),
            'people': ('accounts', 'User'),
            'users': ('accounts', 'User'),
            'payments': ('payments', 'Payment'),
            'payment': ('payments', 'Payment'),
            'maintenance': ('maintenance', 'MaintenanceRequest'),
            'rental': ('properties', 'Lease'),
            'leases': ('properties', 'Lease'),
        }
        
        if module_key not in mapping:
            return None
        
        app_label, model_name = mapping[module_key]
        try:
            return apps.get_model(app_label, model_name)
        except LookupError:
            return None

    def retrieve(self, request, pk=None):
        """
        pk is the module_key (e.g., 'units', 'buildings').
        """
        raise ValueError(f"RETRIEVE VIEW SUCCESSFULLY ENTERED WITH PK: {pk}")
        from django.db import connection
        module_key = pk.strip().lower() if pk else ''
        logger.info(f"Bulk Export requested for module: '{module_key}' (Original PK: '{pk}')")
        
        # Handle cases where PK might have a trailing slash from the URL capture
        if module_key.endswith('/'):
            module_key = module_key[:-1]
            
        model = self._get_model_for_module(module_key)
        
        if not model:
            available_keys = ['units', 'buildings', 'blocks', 'communities', 'people', 'payments', 'maintenance', 'rental']
            error_msg = f'Bulk Export failed: Module "{module_key}" not found or not exportable. Available: {", ".join(available_keys)}'
            logger.error(error_msg)
            # Raising an exception ensures this shows up in Sentry "Issues" tab
            raise ValueError(error_msg)
        
        logger.info(f"Found model {model.__name__} for module {module_key}. Starting export...")

        # Apply basic filters from query params
        status_filter = request.query_params.get('status')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        colony_id = request.query_params.get('colony')
        building_id = request.query_params.get('building')
        block_id = request.query_params.get('block')
        
        queryset = model.objects.all()
        
        if status_filter:
            if hasattr(model, 'status'):
                queryset = queryset.filter(status=status_filter)
        
        if date_from:
            if hasattr(model, 'created_at'):
                queryset = queryset.filter(created_at__date__gte=date_from)
        
        if date_to:
            if hasattr(model, 'created_at'):
                queryset = queryset.filter(created_at__date__lte=date_to)

        # Property hierarchy filters
        if colony_id:
            if hasattr(model, 'township'):
                queryset = queryset.filter(township_id=colony_id)
            elif hasattr(model, 'building'):
                queryset = queryset.filter(building__township_id=colony_id)
            elif hasattr(model, 'block'):
                queryset = queryset.filter(block__township_id=colony_id)

        if building_id:
            if hasattr(model, 'building'):
                queryset = queryset.filter(building_id=building_id)
            elif hasattr(model, 'unit'):
                queryset = queryset.filter(unit__building_id=building_id)

        if block_id:
            if hasattr(model, 'block'):
                queryset = queryset.filter(block_id=block_id)

        # Basic CSV Export
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{module_key}_export.csv"'
        
        writer = csv.writer(response)
        
        # Get field names and foreign keys
        fields = []
        fk_fields = []
        for f in model._meta.get_fields():
            if f.concrete and not f.many_to_many and not f.one_to_many:
                fields.append(f.name)
                if f.is_relation and f.many_to_one:
                    fk_fields.append(f.name)
        
        # Optimize queryset by fetching all foreign keys in one go
        if fk_fields:
            queryset = queryset.select_related(*fk_fields)

        writer.writerow(fields)
        
        # Use iterator to stream results and prevent RAM exhaustion (OOM)
        for obj in queryset.iterator(chunk_size=1000):
            row = []
            for field in fields:
                val = getattr(obj, field)
                # If it's a model instance (ForeignKey), try to get a name or string representation
                if hasattr(val, 'name'):
                    row.append(val.name)
                elif hasattr(val, 'email'):
                    row.append(val.email)
                elif val is not None:
                    row.append(str(val))
                else:
                    row.append('')
            writer.writerow(row)
            
        return response
