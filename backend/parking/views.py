# parking/views.py
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import ParkingSlot, Vehicle, ParkingPass, ParkingEntry
from .serializers import ParkingSlotSerializer, VehicleSerializer, ParkingPassSerializer, ParkingEntrySerializer
from notifications.services import NotificationService


class ParkingSlotViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'parking'
    queryset = ParkingSlot.objects.all()
    serializer_class = ParkingSlotSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['slot_type', 'status', 'building', 'floor']
    
    @action(detail=False, methods=['get'])
    def available(self, request):
        slots = self.queryset.filter(status='available')
        serializer = self.get_serializer(slots, many=True)
        return Response(serializer.data)

    def perform_update(self, serializer):
        old_instance = self.get_object()
        new_instance = serializer.save()
        
        # If assigned_to changed, notify user
        if old_instance.assigned_to != new_instance.assigned_to and new_instance.assigned_to:
            NotificationService.send_parking_notification(new_instance, 'slot_assigned')


class VehicleViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'parking'
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.IsAuthenticated()]
        return super().get_permissions()
    
    def get_queryset(self):
        if self.request.user.is_staff:
            return self.queryset
        return self.queryset.filter(owner=self.request.user)

    def perform_create(self, serializer):
        if self.request.user.is_staff and serializer.validated_data.get('owner'):
            serializer.save()
            return
        serializer.save(owner=self.request.user)


class ParkingPassViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'parking'
    queryset = ParkingPass.objects.all()
    serializer_class = ParkingPassSerializer
    
    def get_queryset(self):
        if self.request.user.is_staff:
            return self.queryset
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        parking_pass = serializer.save()
        NotificationService.send_parking_notification(parking_pass, 'pass_issued')


class ParkingEntryViewSet(ModulePermissionMixin, viewsets.ReadOnlyModelViewSet):
    module = 'parking'
    queryset = ParkingEntry.objects.all()
    serializer_class = ParkingEntrySerializer