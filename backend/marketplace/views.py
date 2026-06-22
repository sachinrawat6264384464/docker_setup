from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import models
from .models import MarketItem, ItemImage, MarketInterest
from .serializers import MarketItemSerializer, MarketInterestSerializer

class MarketItemViewSet(viewsets.ModelViewSet):
    queryset = MarketItem.objects.all()
    serializer_class = MarketItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'item_type', 'category', 'seller']
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'price']

    def get_queryset(self):
        # By default, residents only see active items
        # Sellers see their own items (pending/active/etc.)
        # Admins and Managers can see everything
        user = self.request.user
        qs = MarketItem.objects.select_related('seller').prefetch_related('images')
        if user.is_staff or user.role in ['master_admin', 'facility_manager']:
            return qs
        return qs.filter(models.Q(status='active') | models.Q(seller=user))

    def perform_create(self, serializer):
        serializer.save(seller=self.request.user)

    @action(detail=True, methods=['post'], url_path='interest')
    def express_interest(self, request, pk=None):
        item = self.get_object()
        serializer = MarketInterestSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(buyer=request.user, item=item)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class MarketInterestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MarketInterest.objects.all()
    serializer_class = MarketInterestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Users see interests on their items OR items they are interested in
        user = self.request.user
        qs = MarketInterest.objects.select_related('buyer', 'item', 'item__seller')
        return qs.filter(
            models.Q(item__seller=user) | models.Q(buyer=user)
        )
