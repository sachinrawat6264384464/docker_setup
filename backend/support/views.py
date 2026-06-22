# support/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Count, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import TicketCategory, Ticket, TicketComment, FAQArticle
from .serializers import (
    TicketCategorySerializer, TicketSerializer, TicketCreateSerializer,
    TicketCommentSerializer, FAQArticleSerializer,
)


class TicketCategoryViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'support'
    queryset = TicketCategory.objects.all()
    serializer_class = TicketCategorySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name', 'sort_order']

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get('active_only', '').lower() == 'true':
            qs = qs.filter(is_active=True)
        return qs


class TicketViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'support'
    queryset = Ticket.objects.select_related('category', 'created_by', 'assigned_to').prefetch_related('comments')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'priority', 'category', 'assigned_to']
    search_fields = ['subject', 'description', 'ticket_number']
    ordering_fields = ['created_at', 'updated_at', 'priority', 'status']

    def get_permissions(self):
        """
        Allow any authenticated user to create or update.
        Ownership is enforced by get_queryset and get_object.
        """
        if self.action in ['create', 'update', 'partial_update']:
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == 'create':
            return TicketCreateSerializer
        return TicketSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Residents can only see their own tickets
        if user.role == 'tenant':
            qs = qs.filter(created_by=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def my_tickets(self, request):
        """Get current user's tickets."""
        qs = self.get_queryset().filter(created_by=request.user)
        page = self.paginate_queryset(qs)
        serializer = TicketSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """Assign a ticket to a staff member."""
        ticket = self.get_object()
        assigned_to_id = request.data.get('assigned_to')
        if not assigned_to_id:
            return Response({'error': 'assigned_to is required'}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            assignee = User.objects.get(id=assigned_to_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        ticket.assigned_to = assignee
        if ticket.status == 'open':
            ticket.status = 'in_progress'
        ticket.save(update_fields=['assigned_to', 'status', 'updated_at'])
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Mark a ticket as resolved."""
        ticket = self.get_object()
        ticket.status = 'resolved'
        ticket.resolution_notes = request.data.get('resolution_notes', '')
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'updated_at'])
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close a ticket."""
        ticket = self.get_object()
        ticket.status = 'closed'
        ticket.closed_at = timezone.now()
        ticket.satisfaction_rating = request.data.get('satisfaction_rating')
        ticket.feedback = request.data.get('feedback', '')
        ticket.save(update_fields=['status', 'closed_at', 'satisfaction_rating', 'feedback', 'updated_at'])
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        """Reopen a resolved/closed ticket."""
        ticket = self.get_object()
        if ticket.status not in ('resolved', 'closed'):
            return Response({'error': 'Only resolved or closed tickets can be reopened'}, status=status.HTTP_400_BAD_REQUEST)
        ticket.status = 'open'
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.save(update_fields=['status', 'resolved_at', 'closed_at', 'updated_at'])
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def escalate(self, request, pk=None):
        """Escalate a ticket's priority."""
        ticket = self.get_object()
        priority_order = ['low', 'medium', 'high', 'urgent']
        current_idx = priority_order.index(ticket.priority) if ticket.priority in priority_order else 0
        if current_idx >= len(priority_order) - 1:
            return Response({'error': 'Ticket is already at the highest priority'}, status=status.HTTP_400_BAD_REQUEST)
        ticket.priority = priority_order[current_idx + 1]
        ticket.save(update_fields=['priority', 'updated_at'])
        return Response(TicketSerializer(ticket).data)


class TicketCommentViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = TicketComment.objects.select_related('ticket', 'author')
    serializer_class = TicketCommentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['ticket', 'is_internal']

    def get_permissions(self):
        """Allow any authenticated user to create comments."""
        if self.action == 'create':
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Hide internal comments from residents
        if user.role == 'tenant':
            qs = qs.filter(is_internal=False)
        return qs

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class FAQArticleViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'support'
    queryset = FAQArticle.objects.select_related('category')
    serializer_class = FAQArticleSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'is_published']
    search_fields = ['question', 'answer']
    ordering_fields = ['sort_order', 'view_count', 'helpful_count']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Residents only see published articles
        if user.role == 'tenant':
            qs = qs.filter(is_published=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish an FAQ article."""
        article = self.get_object()
        article.is_published = True
        article.save(update_fields=['is_published', 'updated_at'])
        return Response(FAQArticleSerializer(article).data)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive (unpublish) an FAQ article."""
        article = self.get_object()
        article.is_published = False
        article.save(update_fields=['is_published', 'updated_at'])
        return Response(FAQArticleSerializer(article).data)

    @action(detail=True, methods=['post'])
    def mark_helpful(self, request, pk=None):
        """Increment the helpful counter."""
        article = self.get_object()
        article.helpful_count += 1
        article.save(update_fields=['helpful_count'])
        return Response({'helpful_count': article.helpful_count})

    @action(detail=True, methods=['post'])
    def increment_view(self, request, pk=None):
        """Increment the view counter."""
        article = self.get_object()
        article.view_count += 1
        article.save(update_fields=['view_count'])
        return Response({'view_count': article.view_count})


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def support_dashboard(request):
    """Support dashboard statistics."""
    qs = Ticket.objects.all()
    user = request.user
    if user.role == 'tenant':
        qs = qs.filter(created_by=user)

    from django.utils.timezone import localdate
    import datetime
    today_start = timezone.make_aware(datetime.datetime.combine(localdate(), datetime.time.min))

    recent_tickets = qs.order_by('-created_at')[:5]
    recent_data = TicketSerializer(recent_tickets, many=True).data

    from django.db.models import Count, Q
    active_statuses = ['open', 'in_progress', 'awaiting_response']
    
    aggs = qs.aggregate(
        total=Count('id'),
        open_cnt=Count('id', filter=Q(status='open')),
        in_progress_cnt=Count('id', filter=Q(status='in_progress')),
        awaiting_cnt=Count('id', filter=Q(status='awaiting_response')),
        resolved_cnt=Count('id', filter=Q(status='resolved')),
        closed_cnt=Count('id', filter=Q(status='closed')),
        resolved_today=Count('id', filter=Q(status='resolved', resolved_at__gte=today_start)),
        low_pri=Count('id', filter=Q(priority='low', status__in=active_statuses)),
        med_pri=Count('id', filter=Q(priority='medium', status__in=active_statuses)),
        high_pri=Count('id', filter=Q(priority='high', status__in=active_statuses)),
        urgent_pri=Count('id', filter=Q(priority='urgent', status__in=active_statuses))
    )

    stats = {
        'total_tickets': aggs['total'],
        'open': aggs['open_cnt'],
        'in_progress': aggs['in_progress_cnt'],
        'awaiting_response': aggs['awaiting_cnt'],
        'resolved': aggs['resolved_cnt'],
        'closed': aggs['closed_cnt'],
        'resolved_today': aggs['resolved_today'],
        'by_priority': {
            'low': aggs['low_pri'],
            'medium': aggs['med_pri'],
            'high': aggs['high_pri'],
            'urgent': aggs['urgent_pri'],
        },
        'faq_count': FAQArticle.objects.filter(is_published=True).count(),
        'recent_tickets': recent_data,
    }
    return Response(stats)
