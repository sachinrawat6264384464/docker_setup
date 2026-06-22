import os
import uuid
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.db import IntegrityError
from django.db.models import F
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from .models import Category, Tag, Post, Comment, Author, PostLike
from .serializers import (CategorySerializer, TagSerializer, PostListSerializer,
                          PostDetailSerializer, CommentSerializer, AuthorSerializer)


def get_client_ip(request):
    """Extract real client IP safely, preventing header spoofing."""
    if not request:
        return '0.0.0.0'
    x_real_ip = request.META.get('HTTP_X_REAL_IP', '').strip()
    if x_real_ip:
        return x_real_ip
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def _check_staff(request):
    """Return 403 Response if user is not staff/superuser, else None."""
    if not (request.user.is_staff or request.user.is_superuser):
        return Response({'error': 'Admin access required.'}, status=403)
    return None


# ─── Public Views ────────────────────────────────────────────────────────────

class PublicPostListView(generics.ListAPIView):
    serializer_class = PostListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = Post.objects.filter(status='published').select_related('author', 'author__user', 'category').prefetch_related('tags')
        category = self.request.query_params.get('category')
        tag      = self.request.query_params.get('tag')
        search   = self.request.query_params.get('search')
        featured = self.request.query_params.get('featured')
        if category:
            qs = qs.filter(category__slug=category)
        if tag:
            qs = qs.filter(tags__slug=tag)
        if search:
            qs = qs.filter(title__icontains=search)
        if featured:
            qs = qs.filter(is_featured=True)
        return qs


class PublicPostDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        post = get_object_or_404(Post, slug=slug, status='published')
        Post.objects.filter(pk=post.pk).update(view_count=F('view_count') + 1)
        post.refresh_from_db()
        return Response(PostDetailSerializer(post).data)


class PublicCategoryListView(generics.ListAPIView):
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    queryset = Category.objects.filter(is_active=True)


class PostCommentListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        post = get_object_or_404(Post, slug=slug)
        comments = Comment.objects.filter(post=post, is_approved=True, parent=None)
        return Response(CommentSerializer(comments, many=True).data)

    def post(self, request, slug):
        post = get_object_or_404(Post, slug=slug)
        if not post.allow_comments:
            return Response({'error': 'Comments disabled'}, status=400)
        data = request.data
        # Accept 'body' OR legacy 'content' field name
        body = data.get('body') or data.get('content', '')
        comment = Comment.objects.create(
            post=post,
            author_name=data.get('author_name', 'Anonymous'),
            author_email=data.get('author_email', ''),
            content=body,
            ip_address=get_client_ip(request),
        )
        return Response(CommentSerializer(comment).data, status=201)


class PostLikeToggleView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, slug):
        post = get_object_or_404(Post, slug=slug, status='published')
        ip = get_client_ip(request)
        try:
            like = PostLike.objects.get(post=post, ip_address=ip)
            like.delete()
            Post.objects.filter(pk=post.pk).update(like_count=F('like_count') - 1)
            post.refresh_from_db()
            return Response({'liked': False, 'count': post.like_count})
        except PostLike.DoesNotExist:
            try:
                PostLike.objects.create(post=post, ip_address=ip)
                Post.objects.filter(pk=post.pk).update(like_count=F('like_count') + 1)
                post.refresh_from_db()
                return Response({'liked': True, 'count': post.like_count})
            except IntegrityError:
                # Concurrent request already created this like; treat as already liked
                post.refresh_from_db()
                return Response({'liked': True, 'count': post.like_count})


# ─── Admin Views ─────────────────────────────────────────────────────────────

class AdminPostListView(generics.ListCreateAPIView):
    serializer_class = PostDetailSerializer
    permission_classes = [IsAuthenticated]
    queryset = Post.objects.all().select_related('author', 'author__user', 'category').prefetch_related('tags')


class AdminPostDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PostDetailSerializer
    permission_classes = [IsAuthenticated]
    queryset = Post.objects.all()
    lookup_field = 'slug'


class AdminCategoryView(generics.ListCreateAPIView):
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]
    queryset = Category.objects.all()

    def list(self, request, *args, **kwargs):
        denied = _check_staff(request)
        if denied:
            return denied
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        denied = _check_staff(request)
        if denied:
            return denied
        return super().create(request, *args, **kwargs)


class AdminCategoryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        denied = _check_staff(request)
        if denied:
            return denied
        category = get_object_or_404(Category, pk=pk)
        if category.posts.exists():
            return Response(
                {'error': 'Cannot delete category with existing posts. Reassign posts first.'},
                status=400,
            )
        category.delete()
        return Response(status=204)


class AdminTagView(generics.ListCreateAPIView):
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]
    queryset = Tag.objects.all()


class AdminCommentView(generics.ListAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Comment.objects.filter(is_approved=False).order_by('-created_at')
        post_id = self.request.query_params.get('post')
        if post_id:
            qs = qs.filter(post__id=post_id)
        return qs

    def patch(self, request, pk):
        denied = _check_staff(request)
        if denied:
            return denied
        comment = get_object_or_404(Comment, pk=pk)
        comment.is_approved = request.data.get('is_approved', False)
        comment.save()
        return Response(CommentSerializer(comment).data)

    def delete(self, request, pk):
        denied = _check_staff(request)
        if denied:
            return denied
        comment = get_object_or_404(Comment, pk=pk)
        comment.delete()
        return Response(status=204)


class AdminImageUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        denied = _check_staff(request)
        if denied:
            return denied
        image = request.FILES.get('image')
        if not image:
            return Response({'error': 'No image provided.'}, status=400)
        if not image.content_type.startswith('image/'):
            return Response({'error': 'File must be an image.'}, status=400)
        if image.size > 5 * 1024 * 1024:
            return Response({'error': 'Image must be under 5 MB.'}, status=400)

        ext = os.path.splitext(os.path.basename(image.name))[1].lower()
        safe_name = f'{uuid.uuid4().hex}{ext}'
        path = default_storage.save(f'blog/inline/{safe_name}', ContentFile(image.read()))
        absolute_url = request.build_absolute_uri(settings.MEDIA_URL + path)
        return Response({'url': absolute_url}, status=201)
