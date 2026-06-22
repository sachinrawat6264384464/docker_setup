# communication/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import FileExtensionValidator
import uuid

User = get_user_model()


class Conversation(models.Model):
    """Group or direct conversation"""
    CONVERSATION_TYPES = [
        ('direct', 'Direct Message'),
        ('group', 'Group Chat'),
        ('announcement', 'Announcement Channel'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation_type = models.CharField(max_length=20, choices=CONVERSATION_TYPES, default='direct')
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_conversations', db_constraint=False)
    participants = models.ManyToManyField(User, through='ConversationParticipant', related_name='conversations')
    
    # Settings
    is_locked = models.BooleanField(default=False)  # Locked conversations can't receive new messages
    is_archived = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-last_message_at', '-created_at']
        indexes = [
            models.Index(fields=['-last_message_at']),
            models.Index(fields=['conversation_type']),
        ]
    
    def __str__(self):
        return self.title or f"{self.conversation_type} - {self.id}"
    
    def get_other_participant(self, user):
        """For direct messages, get the other participant"""
        if self.conversation_type == 'direct':
            return self.participants.exclude(id=user.id).first()
        return None


class ConversationParticipant(models.Model):
    """Through model for conversation participants with additional data"""
    ROLES = [
        ('member', 'Member'),
        ('admin', 'Admin'),
        ('moderator', 'Moderator'),
    ]
    
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='participant_set')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversation_memberships', db_constraint=False)
    role = models.CharField(max_length=20, choices=ROLES, default='member')
    
    # Participant settings
    is_muted = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    
    # Read tracking
    last_read_at = models.DateTimeField(null=True, blank=True)
    unread_count = models.IntegerField(default=0)
    
    # Timestamps
    joined_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['conversation', 'user']
        indexes = [
            models.Index(fields=['user', '-joined_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} in {self.conversation}"


class Message(models.Model):
    """Individual message in a conversation"""
    MESSAGE_TYPES = [
        ('text', 'Text Message'),
        ('file', 'File Attachment'),
        ('image', 'Image'),
        ('system', 'System Message'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_messages', db_constraint=False)
    
    # Content
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default='text')
    content = models.TextField()
    
    # Reply functionality
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    
    # Status
    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['sender']),
        ]
    
    def __str__(self):
        return f"Message from {self.sender.username if self.sender else 'System'} at {self.created_at}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update conversation's last message time
        self.conversation.last_message_at = self.created_at
        self.conversation.save(update_fields=['last_message_at'])


class MessageAttachment(models.Model):
    """File attachments for messages"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(
        upload_to='communication/attachments/%Y/%m/',
        validators=[FileExtensionValidator(['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'gif', 'zip'])]
    )
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    file_type = models.CharField(max_length=100)
    
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.filename


class MessageReaction(models.Model):
    """Emoji reactions to messages"""
    REACTIONS = [
        ('👍', 'Thumbs Up'),
        ('❤️', 'Heart'),
        ('😂', 'Laugh'),
        ('😮', 'Surprised'),
        ('😢', 'Sad'),
        ('👏', 'Clap'),
    ]
    
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='message_reactions', db_constraint=False)
    emoji = models.CharField(max_length=10, choices=REACTIONS)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['message', 'user', 'emoji']
    
    def __str__(self):
        return f"{self.user.username} reacted {self.emoji}"


class MessageReadReceipt(models.Model):
    """Track who has read each message"""
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='read_receipts')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='read_messages', db_constraint=False)
    read_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['message', 'user']
        indexes = [
            models.Index(fields=['user', '-read_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} read message at {self.read_at}"


class Announcement(models.Model):
    """Broadcast announcements to residents"""
    PRIORITY_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    ANNOUNCEMENT_TYPES = [
        ('general', 'General Announcement'),
        ('maintenance', 'Maintenance Notice'),
        ('event', 'Event Announcement'),
        ('emergency', 'Emergency Alert'),
        ('policy', 'Policy Update'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    announcement_number = models.CharField(max_length=50, unique=True, editable=False)
    
    title = models.CharField(max_length=200)
    content = models.TextField()
    announcement_type = models.CharField(max_length=50, choices=ANNOUNCEMENT_TYPES, default='general')
    priority = models.CharField(max_length=20, choices=PRIORITY_LEVELS, default='medium')
    
    # Targeting
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_announcements', db_constraint=False)
    target_buildings = models.JSONField(default=list, blank=True)  # List of building IDs
    target_all = models.BooleanField(default=True)
    
    # Scheduling
    scheduled_for = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Status
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    
    # Engagement tracking
    view_count = models.IntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['priority']),
            models.Index(fields=['is_published']),
        ]
    
    def __str__(self):
        return f"{self.announcement_number} - {self.title}"
    
    def save(self, *args, **kwargs):
        if not self.announcement_number:
            from datetime import datetime
            year_month = datetime.now().strftime('%Y%m')
            last_announcement = Announcement.objects.filter(
                announcement_number__startswith=f'ANN-{year_month}'
            ).order_by('-announcement_number').first()
            
            if last_announcement:
                last_number = int(last_announcement.announcement_number.split('-')[-1])
                new_number = last_number + 1
            else:
                new_number = 1
            
            self.announcement_number = f'ANN-{year_month}-{new_number:05d}'
        
        super().save(*args, **kwargs)


class AnnouncementAttachment(models.Model):
    """Attachments for announcements"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='communication/announcements/%Y/%m/')
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.filename


class AnnouncementView(models.Model):
    """Track who has viewed each announcement"""
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name='views')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='viewed_announcements', db_constraint=False)
    viewed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['announcement', 'user']
    
    def __str__(self):
        return f"{self.user.username} viewed {self.announcement.announcement_number}"
