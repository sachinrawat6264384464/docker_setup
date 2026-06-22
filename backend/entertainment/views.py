# ========================================
# FILE 4: entertainment/views.py
# ========================================
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Q
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import Event, EventRegistration, Club
from .serializers import EventSerializer, EventRegistrationSerializer, ClubSerializer


class EventViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing community events
    """
    module = 'entertainment'
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['title', 'description', 'venue', 'organized_by']
    ordering_fields = ['start_date', 'title', 'created_at']
    filterset_fields = ['event_type', 'status', 'is_paid']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by date range
        start_date_from = self.request.query_params.get('start_date_from')
        start_date_to = self.request.query_params.get('start_date_to')
        
        if start_date_from:
            queryset = queryset.filter(start_date__gte=start_date_from)
        if start_date_to:
            queryset = queryset.filter(start_date__lte=start_date_to)
            
        if self.request.query_params.get('upcoming') == 'true':
            queryset = queryset.filter(start_date__gte=timezone.now().date(), status='published')
        
        return queryset.select_related('created_by')
        
    def get_required_permission(self, method, action=None):
        if action in ['register', 'unregister', 'upcoming', 'ongoing']:
            return f"{self.module}.view"
        return super().get_required_permission(method, action)
    
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """Get upcoming published events"""
        events = self.get_queryset().filter(
            start_date__gte=timezone.now().date(),
            status='published'
        ).order_by('start_date', 'start_time')
        
        page = self.paginate_queryset(events)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def ongoing(self, request):
        """Get currently ongoing events"""
        today = timezone.now().date()
        events = self.get_queryset().filter(
            start_date__lte=today,
            end_date__gte=today,
            status='ongoing'
        )
        
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def register(self, request, pk=None):
        """Register for an event"""
        event = self.get_object()
        
        # Check if event is full
        if event.current_attendees >= event.max_attendees:
            return Response(
                {'error': 'Event is full'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if already registered
        if EventRegistration.objects.filter(event=event, user=request.user).exists():
            return Response(
                {'error': 'Already registered for this event'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create registration
        number_of_guests = request.data.get('number_of_guests', 1)
        guest_names = request.data.get('guest_names', [])
        
        registration = EventRegistration.objects.create(
            event=event,
            user=request.user,
            number_of_guests=number_of_guests,
            guest_names=guest_names
        )
        
        # Update attendee count
        event.current_attendees += number_of_guests
        event.save()
        
        serializer = EventRegistrationSerializer(registration)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def unregister(self, request, pk=None):
        """Cancel registration for an event"""
        event = self.get_object()
        
        try:
            registration = EventRegistration.objects.get(event=event, user=request.user)
            number_of_guests = registration.number_of_guests
            registration.delete()
            
            # Update attendee count
            event.current_attendees = max(0, event.current_attendees - number_of_guests)
            event.save()
            return Response({'status': 'registration cancelled'})
        except EventRegistration.DoesNotExist:
            return Response(
                {'error': 'Not registered for this event'},
                status=status.HTTP_400_BAD_REQUEST
            )


class EventRegistrationViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing event registrations
    """
    module = 'entertainment'
    queryset = EventRegistration.objects.all()
    serializer_class = EventRegistrationSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['event__title', 'user__username']
    ordering_fields = ['created_at']
    filterset_fields = ['status', 'event']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Users can only see their own registrations unless they're staff
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        
        return queryset.select_related('event', 'user')
    
    @action(detail=True, methods=['post'])
    def check_in(self, request, pk=None):
        """Check in to an event"""
        registration = self.get_object()
        
        if registration.status != 'confirmed':
            return Response(
                {'error': 'Registration must be confirmed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        registration.status = 'attended'
        registration.checked_in_at = timezone.now()
        registration.save()
        
        serializer = self.get_serializer(registration)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel event registration"""
        registration = self.get_object()
        
        if registration.user != request.user and not request.user.is_staff:
            return Response(
                {'error': 'Cannot cancel other user registrations'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        registration.status = 'cancelled'
        registration.save()
        
        # Update attendee count
        event = registration.event
        event.current_attendees = max(0, event.current_attendees - registration.number_of_guests)
        event.save()
        
        return Response({'status': 'registration cancelled'})


class ClubViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing community clubs
    """
    module = 'entertainment'
    queryset = Club.objects.all()
    serializer_class = ClubSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    filterset_fields = ['category', 'is_active']
    
    def get_queryset(self):
        return super().get_queryset().prefetch_related('members').select_related('admin')
        
    def get_required_permission(self, method, action=None):
        if action in ['join', 'leave', 'my_clubs']:
            return f"{self.module}.view"
        return super().get_required_permission(method, action)
    
    @action(detail=True, methods=['post'])
    def join(self, request, pk=None):
        """Join a club"""
        club = self.get_object()
        
        # Check if club is full
        if club.is_full():
            return Response(
                {'error': 'Club is full'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if already a member
        if club.members.filter(id=request.user.id).exists():
            return Response(
                {'error': 'Already a member of this club'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        club.members.add(request.user)
        
        serializer = self.get_serializer(club)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        """Leave a club"""
        club = self.get_object()
        
        if not club.members.filter(id=request.user.id).exists():
            return Response(
                {'error': 'Not a member of this club'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Admins cannot leave their own club
        if club.admin == request.user:
            return Response(
                {'error': 'Club admins cannot leave. Transfer admin rights first.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        club.members.remove(request.user)
        
        return Response({'status': 'left club successfully'})
    
    @action(detail=False, methods=['get'])
    def my_clubs(self, request):
        """Get clubs the user is a member of"""
        clubs = self.get_queryset().filter(members=request.user)
        
        serializer = self.get_serializer(clubs, many=True)
        return Response(serializer.data)