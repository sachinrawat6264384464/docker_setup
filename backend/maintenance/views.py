# maintenance/views.py - COMPLETE REPLACEMENT
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db.models import Q
from django.utils import timezone
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from accounts.models import User
from notifications.services import NotificationService
from .models import MaintenanceRequest, MaintenanceSchedule, Vendor
from properties.models import Unit, Lease
from .serializers import (
    MaintenanceRequestSerializer, 
    MaintenanceScheduleSerializer, 
    VendorSerializer
)


class MaintenanceRequestViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'maintenance'
    serializer_class = MaintenanceRequestSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'status', 'priority', 'building']
    search_fields = ['title', 'description', 'request_number']
    ordering_fields = ['created_at', 'priority', 'status']
    ordering = ['-created_at']
    
    def get_permissions(self):
        """
        Allow any authenticated user to create or update.
        Ownership is enforced by get_queryset and get_object.
        """
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        """
        Admins see all requests.
        Facility managers see only requests for their assigned buildings (matched by building name).
        All other users see only their own requests.
        """
        user = self.request.user
        base_qs = MaintenanceRequest.objects.select_related(
            'requested_by', 'assigned_to', 'unit', 'lease', 'tenant_user', 'owner_user'
        )

        if getattr(self, 'action', None) == 'list':
            base_qs = base_qs.defer('photos_before', 'photos_after')

        if hasattr(user, 'role') and user.role in ('super_admin', 'superadmin', 'master_admin', 'masteradmin'):
            return base_qs.all()

        if hasattr(user, 'role') and user.role == 'facility_manager':
            from accounts.fm_scope import get_fm_building_names
            building_names = list(get_fm_building_names(user) or [])
            
            # FMs see:
            # 1. Requests in their assigned buildings (case-insensitive)
            # 2. Requests explicitly assigned to them
            # 3. Requests they personally created
            q_filter = Q(assigned_to=user) | Q(requested_by=user)
            
            if building_names:
                for name in building_names:
                    q_filter |= Q(building__iexact=name)
            
            return base_qs.filter(q_filter).distinct()

        if getattr(user, 'role', None) == 'owner':
            return base_qs.filter(
                Q(owner_user=user) |
                Q(owner_email__iexact=getattr(user, 'email', '')) |
                Q(unit__owner_email__iexact=getattr(user, 'email', ''))
            ).distinct()

        return base_qs.filter(
            Q(requested_by=user) |
            Q(tenant_user=user) |
            Q(lease__tenant=user)
        ).distinct()
    
    def perform_create(self, serializer):
        """Save with current user as requester; enforce FM building scope."""
        user = self.request.user
        if hasattr(user, 'role') and user.role == 'facility_manager':
            from accounts.fm_scope import get_fm_unit_pairs
            building_name = (serializer.validated_data.get('building') or '').strip()
            unit_number = (serializer.validated_data.get('unit_number') or '').strip()
            allowed_pairs = {(str(b).lower(), str(u).lower()) for b, u in (get_fm_unit_pairs(user) or []) if b and u}
            if (building_name.lower(), unit_number.lower()) not in allowed_pairs:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('You can only create maintenance requests for assigned units.')

        request_obj = serializer.save(requested_by=user)

        try:
            if request_obj.owner_user and request_obj.owner_user != user:
                NotificationService.send(
                    user=request_obj.owner_user,
                    title=f'New Maintenance Request - #{request_obj.request_number}',
                    message=(
                        f'{request_obj.title} was created for Unit {request_obj.unit_number} in '
                        f'{request_obj.building}. Review it in your owner portal.'
                    ),
                    notification_type='maintenance',
                    priority=request_obj.priority,
                    send_email=True,
                    send_push=True,
                    related_object_type='maintenance_request',
                    related_object_id=request_obj.id,
                    action_url=f'/owner/maintenance?request={request_obj.id}',
                    metadata={
                        'request_id': str(request_obj.id),
                        'request_number': request_obj.request_number,
                        'unit_number': request_obj.unit_number,
                        'building': request_obj.building,
                    },
                )
        except Exception:
            pass
    
    def create(self, request, *args, **kwargs):
        """Override create to return proper error responses"""
        serializer = self.get_serializer(data=request.data, context={'request': request})
        
        if not serializer.is_valid():
            # Return field-level errors
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    def update(self, request, *args, **kwargs):
        """Override update to return proper error responses"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        self.perform_update(serializer)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], url_path='my-requests')
    def my_requests(self, request):
        """Get current user's requests only"""
        requests = MaintenanceRequest.objects.select_related(
            'requested_by', 'assigned_to', 'unit', 'lease', 'tenant_user', 'owner_user'
        ).filter(requested_by=request.user)
        
        # Apply filters
        category = request.query_params.get('category')
        status_filter = request.query_params.get('status')
        search = request.query_params.get('search')
        
        if category:
            requests = requests.filter(category=category)
        if status_filter:
            requests = requests.filter(status=status_filter)
        if search:
            requests = requests.filter(
                title__icontains=search
            ) | requests.filter(
                description__icontains=search
            )
        
        serializer = self.get_serializer(requests, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['patch'], url_path='update-status')
    def update_status(self, request, pk=None):
        """Update request status (manager/admin only)"""
        instance = self.get_object()
        new_status = request.data.get('status')
        
        if not new_status:
            return Response(
                {'status': ['This field is required']},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        instance.status = new_status
        
        # Update timeline dates based on status
        now = timezone.now()
        if new_status == 'acknowledged' and not instance.acknowledged_date:
            instance.acknowledged_date = now
        elif new_status == 'in_progress' and not instance.started_date:
            instance.started_date = now
        elif new_status == 'completed' and not instance.completed_date:
            instance.completed_date = now
            
        instance.save()

        if instance.owner_user and instance.owner_user != instance.requested_by:
            NotificationService.send(
                user=instance.owner_user,
                title=f'Maintenance Status Updated - #{instance.request_number}',
                message=f'{instance.title} is now {instance.get_status_display()}.',
                notification_type='maintenance',
                priority='medium',
                send_email=True,
                send_push=True,
                related_object_type='maintenance_request',
                related_object_id=instance.id,
                action_url=f'/owner/maintenance?request={instance.id}',
            )

        if instance.requested_by:
            NotificationService.send(
                user=instance.requested_by,
                title=f'Maintenance Status Updated - #{instance.request_number}',
                message=f'Your request {instance.request_number} is now {instance.get_status_display()}.',
                notification_type='maintenance',
                priority='low',
                send_email=True,
                send_push=True,
                related_object_type='maintenance_request',
                related_object_id=instance.id,
                action_url=f'/residents/maintenance?request={instance.id}',
            )
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['patch'], url_path='assign')
    def assign(self, request, pk=None):
        """Assign request to a user (staff/vendor)"""
        from django.utils import timezone
        instance = self.get_object()
        assigned_to = request.data.get('assigned_to')
        
        if assigned_to:
            instance.assigned_to_id = assigned_to
            if not instance.assigned_date:
                instance.assigned_date = timezone.now()
            # Optionally auto-update status to assigned if currently submitted
            if instance.status == 'submitted':
                instance.status = 'assigned'
        else:
            instance.assigned_to = None
            
        instance.save()
        
        # Notify the user who was assigned the task
        if instance.assigned_to:
            NotificationService.send(
                user=instance.assigned_to,
                title='New Task Assigned',
                message=f'You have been assigned to maintenance request #{instance.request_number}.',
                notification_type='maintenance',
                priority='high',
                send_email=True,
                action_url=f'/manager/maintenance',
            )

        # Notify Master Admins if assigned by an FM
        user = self.request.user
        if getattr(user, 'role', None) == 'facility_manager':
            master_admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
            for admin in master_admins:
                NotificationService.send(
                    user=admin,
                    title='FM Activity: Maintenance Assigned',
                    message=f'Facility Manager {user.get_full_name()} assigned request #{instance.request_number} to someone.',
                    notification_type='system',
                    priority='low',
                    send_email=True,
                    action_url='/admin/maintenance',
                )
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class MaintenanceScheduleViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'maintenance'
    queryset = MaintenanceSchedule.objects.all().select_related('assigned_to')
    serializer_class = MaintenanceScheduleSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'frequency', 'is_active']
    search_fields = ['title', 'description']


class VendorViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'maintenance'
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['service_type', 'is_active']
    search_fields = ['name', 'contact_person']