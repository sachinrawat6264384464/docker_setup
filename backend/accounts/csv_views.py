# accounts/csv_views.py - CSV Upload and Processing Views
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from django.http import HttpResponse, JsonResponse
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q
from .csv_models import CSVUpload, CSVRowResult, CSVTemplate
from .csv_processor import CSVProcessingEngine
from .serializers import ActivityLogSerializer
from .models import ActivityLog
import threading
import csv
import io
import logging
from .tasks import process_csv_file_async
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

logger = logging.getLogger(__name__)

def process_csv_async(csv_upload_id):
    """Background task to process CSV file"""
    try:
        csv_upload = CSVUpload.objects.get(id=csv_upload_id)
        processor = CSVProcessingEngine(csv_upload)
        result = processor.process_file()
        logger.info(f"CSV processing completed for upload {csv_upload_id}: {result}")
    except Exception as e:
        logger.error(f"CSV processing failed for upload {csv_upload_id}: {str(e)}")

@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_csv_file(request):
    """
    Upload CSV file for processing
    """
    # Check permissions
    if not (hasattr(request.user, 'can_manage_property') and request.user.can_manage_property):
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    if 'file' not in request.FILES:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
    
    file = request.FILES['file']
    
    # Validate file
    if not file.name.lower().endswith(('.csv', '.xlsx', '.xls')):
        return Response(
            {'error': 'Only CSV and Excel files are allowed'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check file size (10MB limit)
    if file.size > 10 * 1024 * 1024:
        return Response(
            {'error': 'File size too large. Maximum 10MB allowed'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Create CSV upload record
        csv_upload = CSVUpload.objects.create(
            uploaded_by=request.user,
            file=file,
            original_filename=file.name,
            file_size=file.size,
            status='pending'
        )
        
        # Log the upload
        ActivityLog.objects.create(
            user=request.user,
            action='csv_upload_started',
            description=f'Started CSV upload: {file.name} ({file.size} bytes)',
            metadata={
                'upload_id': str(csv_upload.id),
                'filename': file.name,
                'file_size': file.size
            }
        )
        
        task = process_csv_file_async.delay(str(csv_upload.id))
        
        logger.info(f"CSV processing task started: {task.id} for upload {csv_upload.id}")
        
        return Response({
            'upload_id': str(csv_upload.id),
            'task_id': task.id,
            'message': 'File uploaded successfully. Processing started in background.',
            'status': 'pending'
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"CSV upload failed: {str(e)}")
        return Response(
            {'error': f'Upload failed: {str(e)}'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_task_status(request, task_id):
    """
    Get status of a Celery task
    
    Args:
        task_id: Celery task ID
        
    Returns:
        Task status and result
    """
    from celery.result import AsyncResult
    
    task = AsyncResult(task_id)
    
    response_data = {
        'task_id': task_id,
        'status': task.state,
        'result': None,
        'error': None
    }
    
    if task.state == 'PENDING':
        response_data['message'] = 'Task is waiting to be processed'
    
    elif task.state == 'STARTED':
        response_data['message'] = 'Task is currently being processed'
    
    elif task.state == 'SUCCESS':
        response_data['result'] = task.result
        response_data['message'] = 'Task completed successfully'
    
    elif task.state == 'FAILURE':
        response_data['error'] = str(task.info)
        response_data['message'] = 'Task failed'
    
    elif task.state == 'RETRY':
        response_data['message'] = 'Task is being retried'
    
    return Response(response_data)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_upload_status(request, upload_id):
    """
    Get status of CSV upload processing
    """
    csv_upload = get_object_or_404(CSVUpload, id=upload_id, uploaded_by=request.user)
    
    response_data = {
        'upload_id': str(csv_upload.id),
        'filename': csv_upload.original_filename,
        'status': csv_upload.status,
        'total_rows': csv_upload.total_rows,
        'processed_rows': csv_upload.processed_rows,
        'success_count': csv_upload.success_count,
        'error_count': csv_upload.error_count,
        'warning_count': csv_upload.warning_count,
        'success_rate': csv_upload.success_rate,
        'processing_started_at': csv_upload.processing_started_at,
        'processing_completed_at': csv_upload.processing_completed_at,
        'processing_time_seconds': csv_upload.processing_time_seconds,
        'summary': csv_upload.summary,
        'errors': csv_upload.errors[:5] if csv_upload.errors else [],  # Limit errors shown
    }
    
    # Add progress percentage
    if csv_upload.total_rows > 0:
        response_data['progress_percentage'] = round(
            (csv_upload.processed_rows / csv_upload.total_rows) * 100, 2
        )
    else:
        response_data['progress_percentage'] = 0
    
    return Response(response_data)

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_upload_results(request, upload_id):
    """
    Get detailed results of CSV processing
    """
    csv_upload = get_object_or_404(CSVUpload, id=upload_id, uploaded_by=request.user)
    
    # Get query parameters for filtering
    result_type = request.query_params.get('result_type', None)  # success, error, warning
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 50))
    
    # Filter results
    results = csv_upload.row_results.all()
    if result_type:
        results = results.filter(result_type=result_type)
    
    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    paginated_results = results[start:end]
    
    results_data = []
    for result in paginated_results:
        results_data.append({
            'row_number': result.row_number,
            'result_type': result.result_type,
            'message': result.message,
            'raw_data': result.raw_data,
            'details': result.details,
            'created_user_id': result.created_user_id,
        })
    
    return Response({
        'upload_info': {
            'upload_id': str(csv_upload.id),
            'filename': csv_upload.original_filename,
            'status': csv_upload.status,
            'summary': csv_upload.summary,
        },
        'results': results_data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_results': results.count(),
            'has_next': end < results.count(),
        }
    })

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def list_csv_uploads(request):
    """
    List CSV uploads for current user
    """
    uploads = CSVUpload.objects.filter(uploaded_by=request.user).order_by('-created_at')
    
    # Apply filters
    status_filter = request.query_params.get('status', None)
    if status_filter:
        uploads = uploads.filter(status=status_filter)
    
    # Pagination
    page = int(request.query_params.get('page', 1))
    page_size = int(request.query_params.get('page_size', 20))
    start = (page - 1) * page_size
    end = start + page_size
    
    paginated_uploads = uploads[start:end]
    
    uploads_data = []
    for upload in paginated_uploads:
        uploads_data.append({
            'upload_id': str(upload.id),
            'filename': upload.original_filename,
            'file_size': upload.file_size,
            'status': upload.status,
            'total_rows': upload.total_rows,
            'success_count': upload.success_count,
            'error_count': upload.error_count,
            'success_rate': upload.success_rate,
            'created_at': upload.created_at,
            'processing_completed_at': upload.processing_completed_at,
        })
    
    return Response({
        'uploads': uploads_data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_uploads': uploads.count(),
            'has_next': end < uploads.count(),
        }
    })

@extend_schema(responses=OpenApiTypes.BINARY)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def download_csv_template(request):
    """
    Download CSV template for resident upload
    """
    template_type = request.query_params.get('type', 'residents')
    
    # Create CSV template
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{template_type}_template.csv"'
    
    writer = csv.writer(response)
    
    if template_type == 'residents':
        # Header row
        headers = [
            'first_name', 'last_name', 'email', 'phone',
            'colony_name', 'building_name', 'block_name', 'wing_name', 'floor_number', 'unit_number',
            'emergency_contact_name',
            'emergency_contact_phone', 'lease_start_date', 'lease_end_date',
            'monthly_rent', 'security_deposit', 'date_of_birth', 'occupation',
            'square_feet', 'bedrooms', 'bathrooms',
            'document_title', 'document_type', 'document_pdf_url', 'document_file_name'
        ]
        writer.writerow(headers)
        
        # Sample data rows
        sample_rows = [
            [
                'John', 'Doe', 'john.doe@email.com', '9876543210',
                'Palm Residency', 'Tower A', 'A', 'East Wing', '1', 'A101', 'John Sr.', '9876543220',
                '2024-01-01', '2024-12-31', '25000', '50000',
                '1990-05-15', 'Software Engineer', '1000', '2', '2',
                'Rental Agreement - A101', 'lease_agreement', 'https://example.com/docs/john-lease.pdf', 'john-lease.pdf'
            ],
            [
                'Jane', 'Smith', 'jane.smith@email.com', '9876543211',
                'Palm Residency', 'Tower B', 'B', 'West Wing', '2', 'B202', 'Jane Sr.', '9876543221',
                '2024-02-01', '2025-01-31', '30000', '60000',
                '1985-08-20', 'Doctor', '1200', '3', '2',
                '', '', '', ''
            ],
        ]
        
        for row in sample_rows:
            writer.writerow(row)
    
    return response

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_csv_templates(request):
    """
    Get available CSV templates
    """
    templates = CSVTemplate.objects.filter(is_active=True).order_by('template_type', 'name')
    
    templates_data = []
    for template in templates:
        templates_data.append({
            'id': str(template.id),
            'name': template.name,
            'template_type': template.template_type,
            'description': template.description,
            'required_columns': template.required_columns,
            'optional_columns': template.optional_columns,
            'column_descriptions': template.column_descriptions,
        })
    
    return Response({'templates': templates_data})

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_csv_upload(request, upload_id):
    """
    Delete CSV upload record and associated data
    """
    csv_upload = get_object_or_404(CSVUpload, id=upload_id, uploaded_by=request.user)
    
    # Only allow deletion of completed/failed uploads
    if csv_upload.status in ['pending', 'processing']:
        return Response(
            {'error': 'Cannot delete upload that is currently processing'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Log the deletion
    ActivityLog.objects.create(
        user=request.user,
        action='csv_upload_deleted',
        description=f'Deleted CSV upload: {csv_upload.original_filename}',
        metadata={
            'upload_id': str(csv_upload.id),
            'filename': csv_upload.original_filename
        }
    )
    
    # Delete the upload and associated file
    csv_upload.delete()
    
    return Response({'message': 'CSV upload deleted successfully'})

@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def retry_csv_processing(request, upload_id):
    """
    Retry processing a failed CSV upload
    """
    csv_upload = get_object_or_404(CSVUpload, id=upload_id, uploaded_by=request.user)
    
    if csv_upload.status not in ['failed', 'partial']:
        return Response(
            {'error': 'Only failed or partial uploads can be retried'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Reset status and counters
    csv_upload.status = 'pending'
    csv_upload.processed_rows = 0
    csv_upload.success_count = 0
    csv_upload.error_count = 0
    csv_upload.warning_count = 0
    csv_upload.errors = []
    csv_upload.warnings = []
    csv_upload.summary = {}
    csv_upload.processing_started_at = None
    csv_upload.processing_completed_at = None
    csv_upload.save()
    
    # Clear previous row results
    csv_upload.row_results.all().delete()
    
    # Start processing again
    thread = threading.Thread(
        target=process_csv_async, 
        args=(csv_upload.id,)
    )
    thread.daemon = True
    thread.start()
    
    return Response({
        'message': 'CSV processing restarted',
        'upload_id': str(csv_upload.id),
        'status': 'pending'
    })

@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def csv_processing_stats(request):
    """
    Get CSV processing statistics for the current user/tenant
    """
    uploads = CSVUpload.objects.filter(uploaded_by=request.user)
    
    stats = {
        'total_uploads': uploads.count(),
        'successful_uploads': uploads.filter(status='completed').count(),
        'failed_uploads': uploads.filter(status='failed').count(),
        'partial_uploads': uploads.filter(status='partial').count(),
        'processing_uploads': uploads.filter(status__in=['pending', 'processing']).count(),
        'total_rows_processed': sum(upload.processed_rows for upload in uploads),
        'total_users_created': sum(upload.success_count for upload in uploads),
        'total_errors': sum(upload.error_count for upload in uploads),
    }
    
    # Recent uploads (last 7 days)
    recent_uploads = uploads.filter(
        created_at__gte=timezone.now() - timezone.timedelta(days=7)
    )
    stats['recent_uploads_count'] = recent_uploads.count()
    
    return Response(stats)