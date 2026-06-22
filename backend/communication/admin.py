# communication/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Conversation, ConversationParticipant, Message, MessageAttachment,
    MessageReaction, MessageReadReceipt, Announcement, AnnouncementAttachment,
    AnnouncementView
)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation_type', 'title', 'created_by', 'participant_count', 'last_message_at', 'created_at']
    list_filter = ['conversation_type', 'is_locked', 'is_archived', 'created_at']
    search_fields = ['title', 'description', 'id']
    readonly_fields = ['id', 'created_at', 'updated_at', 'last_message_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'conversation_type', 'title', 'description', 'created_by')
        }),
        ('Settings', {
            'fields': ('is_locked', 'is_archived')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_message_at')
        }),
    )
    
    def participant_count(self, obj):
        return obj.participants.count()
    participant_count.short_description = 'Participants'


@admin.register(ConversationParticipant)
class ConversationParticipantAdmin(admin.ModelAdmin):
    list_display = ['user', 'conversation', 'role', 'unread_count', 'is_muted', 'is_pinned', 'joined_at']
    list_filter = ['role', 'is_muted', 'is_pinned', 'joined_at']
    search_fields = ['user__username', 'user__email', 'conversation__title']
    readonly_fields = ['joined_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'sender', 'conversation', 'message_type', 'content_preview', 'is_edited', 'is_deleted', 'created_at']
    list_filter = ['message_type', 'is_edited', 'is_deleted', 'created_at']
    search_fields = ['content', 'sender__username', 'conversation__title']
    readonly_fields = ['id', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    
    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Content'


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
    list_display = ['filename', 'message', 'file_type', 'file_size', 'uploaded_at']
    list_filter = ['file_type', 'uploaded_at']
    search_fields = ['filename']
    readonly_fields = ['uploaded_at']


@admin.register(MessageReaction)
class MessageReactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'emoji', 'created_at']
    list_filter = ['emoji', 'created_at']
    search_fields = ['user__username']
    readonly_fields = ['created_at']


@admin.register(MessageReadReceipt)
class MessageReadReceiptAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'read_at']
    list_filter = ['read_at']
    search_fields = ['user__username']
    readonly_fields = ['read_at']


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['announcement_number', 'title', 'announcement_type', 'priority_badge', 'is_published', 'view_count', 'created_at']
    list_filter = ['announcement_type', 'priority', 'is_published', 'created_at']
    search_fields = ['announcement_number', 'title', 'content']
    readonly_fields = ['announcement_number', 'view_count', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('announcement_number', 'title', 'content', 'announcement_type', 'priority', 'created_by')
        }),
        ('Targeting', {
            'fields': ('target_all', 'target_buildings')
        }),
        ('Scheduling', {
            'fields': ('scheduled_for', 'expires_at')
        }),
        ('Publication', {
            'fields': ('is_published', 'published_at')
        }),
        ('Statistics', {
            'fields': ('view_count',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def priority_badge(self, obj):
        colors = {
            'low': 'green',
            'medium': 'blue',
            'high': 'orange',
            'urgent': 'red'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.priority, 'gray'),
            obj.get_priority_display()
        )
    priority_badge.short_description = 'Priority'


@admin.register(AnnouncementAttachment)
class AnnouncementAttachmentAdmin(admin.ModelAdmin):
    list_display = ['filename', 'announcement', 'file_size', 'uploaded_at']
    list_filter = ['uploaded_at']
    search_fields = ['filename', 'announcement__title']
    readonly_fields = ['uploaded_at']


@admin.register(AnnouncementView)
class AnnouncementViewAdmin(admin.ModelAdmin):
    list_display = ['user', 'announcement', 'viewed_at']
    list_filter = ['viewed_at']
    search_fields = ['user__username', 'announcement__title']
    readonly_fields = ['viewed_at']
