# social/models.py
from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class Post(models.Model):
    POST_CATEGORY_CHOICES = [
        ('general', 'General'),
        ('lost_found', 'Lost & Found'),
        ('event', 'Event'),
        ('alert', 'Alert / Help'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='social_posts', db_constraint=False)
    content = models.TextField()
    category = models.CharField(max_length=20, choices=POST_CATEGORY_CHOICES, default='general')
    
    # Media
    image = models.ImageField(upload_to='social/posts/', null=True, blank=True)
    video = models.FileField(upload_to='social/videos/', null=True, blank=True)
    
    # Status
    is_hidden = models.BooleanField(default=False)  # For moderation
    is_pinned = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_pinned', '-created_at']
        verbose_name = 'Social Post'

    def __str__(self):
        return f"{self.author.get_full_name()} - {self.content[:30]}"

class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='liked_posts', db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['post', 'user']

class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_comments', db_constraint=False)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.username} on {self.post.id}"
