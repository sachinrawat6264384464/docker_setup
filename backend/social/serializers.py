# social/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Post, PostLike, PostComment

User = get_user_model()

class AuthorSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    class Meta:
        model = User
        fields = ['id', 'username', 'full_name', 'avatar', 'role']

class PostCommentSerializer(serializers.ModelSerializer):
    author_details = AuthorSerializer(source='author', read_only=True)
    
    class Meta:
        model = PostComment
        fields = ['id', 'post', 'author', 'author_details', 'text', 'created_at']
        read_only_fields = ['author']

class PostSerializer(serializers.ModelSerializer):
    author_details = AuthorSerializer(source='author', read_only=True)
    likes_count = serializers.IntegerField(source='likes.count', read_only=True)
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    is_liked = serializers.SerializerMethodField()
    
    class Meta:
        model = Post
        fields = [
            'id', 'author', 'author_details', 'content', 'category', 
            'image', 'video', 'is_pinned', 'created_at', 
            'likes_count', 'comments_count', 'is_liked'
        ]
        read_only_fields = ['author', 'is_pinned']

    def get_is_liked(self, obj):
        user = self.context.get('request').user
        if user.is_authenticated:
            return obj.likes.filter(user=user).exists()
        return False
