# communication/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django_tenants.utils import schema_context
from .models import (
    Conversation, ConversationParticipant, Message, MessageAttachment,
    MessageReaction, MessageReadReceipt, Announcement, AnnouncementAttachment,
    AnnouncementView
)

User = get_user_model()

def safe_get_user(instance, field_name):
    if not instance:
        return None
    try:
        user = getattr(instance, field_name)
        if user is not None:
            return user
    except Exception:
        pass
        
    fk_id = getattr(instance, f"{field_name}_id", None)
    if fk_id:
        try:
            return User.objects.get(id=fk_id)
        except Exception:
            pass
        try:
            with schema_context('public'):
                return User.objects.get(id=fk_id)
        except Exception:
            pass
    return None


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user data for messages"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class MessageAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageAttachment
        fields = ['id', 'file', 'filename', 'file_size', 'file_type', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']


class MessageReactionSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    
    class Meta:
        model = MessageReaction
        fields = ['id', 'message', 'user', 'emoji', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_user(self, obj):
        user = safe_get_user(obj, 'user')
        return UserMiniSerializer(user).data if user else None


class MessageReadReceiptSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    
    class Meta:
        model = MessageReadReceipt
        fields = ['id', 'user', 'read_at']
        read_only_fields = ['id', 'read_at']

    def get_user(self, obj):
        user = safe_get_user(obj, 'user')
        return UserMiniSerializer(user).data if user else None


class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.SerializerMethodField()
    attachments = MessageAttachmentSerializer(many=True, read_only=True)
    reactions = MessageReactionSerializer(many=True, read_only=True)
    read_receipts = MessageReadReceiptSerializer(many=True, read_only=True)
    reply_to_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'conversation', 'sender', 'message_type', 'content',
            'reply_to', 'reply_to_message', 'is_edited', 'is_deleted',
            'attachments', 'reactions', 'read_receipts',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'sender', 'is_edited', 'is_deleted', 'created_at', 'updated_at']
    
    def get_sender(self, obj):
        user = safe_get_user(obj, 'sender')
        return UserMiniSerializer(user).data if user else None

    def get_reply_to_message(self, obj):
        if obj.reply_to:
            sender = safe_get_user(obj.reply_to, 'sender')
            return {
                'id': obj.reply_to.id,
                'sender': UserMiniSerializer(sender).data if sender else None,
                'content': obj.reply_to.content[:100],
                'created_at': obj.reply_to.created_at
            }
        return None


class ConversationParticipantSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    
    class Meta:
        model = ConversationParticipant
        fields = [
            'id', 'user', 'role', 'is_muted', 'is_pinned',
            'last_read_at', 'unread_count', 'joined_at'
        ]
        read_only_fields = ['id', 'unread_count', 'joined_at']

    def get_user(self, obj):
        user = safe_get_user(obj, 'user')
        return UserMiniSerializer(user).data if user else None


class ConversationSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()
    participants_data = ConversationParticipantSerializer(source='participant_set', many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Conversation
        fields = [
            'id', 'conversation_type', 'title', 'description',
            'created_by', 'participants_data', 'last_message',
            'unread_count', 'is_locked', 'is_archived',
            'created_at', 'updated_at', 'last_message_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at', 'last_message_at']
    
    def get_created_by(self, obj):
        user = safe_get_user(obj, 'created_by')
        return UserMiniSerializer(user).data if user else None

    def get_last_message(self, obj):
        last_msg = obj.messages.filter(is_deleted=False).order_by('-created_at').first()
        if last_msg:
            sender = safe_get_user(last_msg, 'sender')
            return {
                'id': last_msg.id,
                'sender': UserMiniSerializer(sender).data if sender else None,
                'content': last_msg.content[:100],
                'created_at': last_msg.created_at
            }
        return None
    
    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            participant = obj.participant_set.filter(user=request.user).first()
            return participant.unread_count if participant else 0
        return 0


class ConversationCreateSerializer(serializers.ModelSerializer):
    participant_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True
    )
    
    class Meta:
        model = Conversation
        fields = ['conversation_type', 'title', 'description', 'participant_ids']
    
    def create(self, validated_data):
        participant_ids = validated_data.pop('participant_ids')
        request = self.context.get('request')
        
        conversation = Conversation.objects.create(
            created_by=request.user,
            **validated_data
        )
        
        # Add participants
        for user_id in participant_ids:
            ConversationParticipant.objects.create(
                conversation=conversation,
                user_id=user_id
            )
        
        # Add creator as participant
        ConversationParticipant.objects.get_or_create(
            conversation=conversation,
            user=request.user,
            defaults={'role': 'admin'}
        )
        
        return conversation


class AnnouncementAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnnouncementAttachment
        fields = ['id', 'file', 'filename', 'file_size', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']


class AnnouncementSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()
    attachments = AnnouncementAttachmentSerializer(many=True, read_only=True)
    is_viewed = serializers.SerializerMethodField()
    
    class Meta:
        model = Announcement
        fields = [
            'id', 'announcement_number', 'title', 'content',
            'announcement_type', 'priority', 'created_by',
            'target_buildings', 'target_all', 'scheduled_for',
            'expires_at', 'is_published', 'published_at',
            'view_count', 'attachments', 'is_viewed',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'announcement_number', 'created_by', 'published_at',
            'view_count', 'created_at', 'updated_at'
        ]
    
    def get_created_by(self, obj):
        user = safe_get_user(obj, 'created_by')
        return UserMiniSerializer(user).data if user else None

    def get_is_viewed(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return AnnouncementView.objects.filter(
                announcement=obj,
                user=request.user
            ).exists()
        return False
