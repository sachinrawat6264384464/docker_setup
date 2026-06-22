from django.db import IntegrityError
from rest_framework import serializers
from .models import Category, Tag, Author, Post, Comment


class CategorySerializer(serializers.ModelSerializer):
    post_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'color', 'icon', 'post_count']

    def get_post_count(self, obj):
        return obj.posts.filter(status='published').count()


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug']


class AuthorSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = Author
        fields = ['id', 'name', 'email', 'bio', 'avatar', 'twitter', 'linkedin', 'website']

    def get_name(self, obj):
        return obj.user.get_full_name() or obj.user.email


class PostListSerializer(serializers.ModelSerializer):
    author   = AuthorSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    tags     = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'slug', 'excerpt', 'cover_image', 'featured_image',
            'author', 'category', 'tags', 'status', 'published_at', 'view_count',
            'read_time_minutes', 'is_featured', 'is_pinned', 'like_count', 'created_at',
        ]


class PostDetailSerializer(PostListSerializer):
    # Write-only FK for category assignment
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source='category',
        write_only=True,
        required=False,
        allow_null=True,
    )
    # Write-only list of tag name strings (get-or-create)
    tag_names = serializers.ListField(
        child=serializers.CharField(max_length=50),
        write_only=True,
        required=False,
        default=list,
    )
    # like_count is read-only — managed by F() expressions in views, never written by clients
    class Meta(PostListSerializer.Meta):
        fields = PostListSerializer.Meta.fields + [
            'content', 'seo_title', 'seo_description', 'seo_keywords',
            'canonical_url', 'allow_comments', 'updated_at', 'category_id', 'tag_names',
        ]
        read_only_fields = ['like_count']

    def _set_tags(self, post, tag_names):
        if tag_names is None:
            return
        tags = []
        for name in tag_names:
            name = name.strip()
            if name:
                try:
                    tag, _ = Tag.objects.get_or_create(name=name)
                except IntegrityError:
                    tag = Tag.objects.get(name=name)
                tags.append(tag)
        post.tags.set(tags)

    def create(self, validated_data):
        tag_names = validated_data.pop('tag_names', [])
        post = super().create(validated_data)
        self._set_tags(post, tag_names)
        return post

    def update(self, instance, validated_data):
        tag_names = validated_data.pop('tag_names', None)
        post = super().update(instance, validated_data)
        self._set_tags(post, tag_names)
        return post


class CommentSerializer(serializers.ModelSerializer):
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id', 'author_name', 'author_email', 'content',
            'is_approved', 'created_at', 'replies',
        ]

    def get_replies(self, obj):
        if obj.parent is None:
            return CommentSerializer(obj.replies.filter(is_approved=True), many=True).data
        return []
