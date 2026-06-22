# social/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Post, PostLike, PostComment
from .serializers import PostSerializer, PostCommentSerializer

class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.filter(is_hidden=False).select_related('author').prefetch_related('likes', 'comments')
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'author']
    search_fields = ['content']
    ordering_fields = ['created_at', 'is_pinned']
    ordering = ['-is_pinned', '-created_at']

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @action(detail=True, methods=['post'])
    def like(self, request, pk=None):
        post = self.get_object()
        like, created = PostLike.objects.get_or_create(post=post, user=request.user)
        
        if not created:
            like.delete()
            return Response({'status': 'unliked'}, status=status.HTTP_200_OK)
            
        return Response({'status': 'liked'}, status=status.HTTP_201_CREATED)

class PostCommentViewSet(viewsets.ModelViewSet):
    queryset = PostComment.objects.all().select_related('author')
    serializer_class = PostCommentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['post']

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
