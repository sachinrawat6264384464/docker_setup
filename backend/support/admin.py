# support/admin.py
from django.contrib import admin
from .models import TicketCategory, Ticket, TicketComment, FAQArticle


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'sort_order', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name']
    list_editable = ['sort_order', 'is_active']


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ['ticket_number', 'subject', 'category', 'priority', 'status', 'created_by', 'assigned_to', 'created_at']
    list_filter = ['status', 'priority', 'category', 'created_at']
    search_fields = ['ticket_number', 'subject', 'description']
    readonly_fields = ['ticket_number', 'created_at', 'updated_at', 'resolved_at', 'closed_at']
    raw_id_fields = ['created_by', 'assigned_to']
    date_hierarchy = 'created_at'


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    list_display = ['ticket', 'author', 'is_internal', 'created_at']
    list_filter = ['is_internal', 'created_at']
    raw_id_fields = ['ticket', 'author']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(FAQArticle)
class FAQArticleAdmin(admin.ModelAdmin):
    list_display = ['question', 'category', 'is_published', 'view_count', 'helpful_count', 'sort_order']
    list_filter = ['is_published', 'category']
    search_fields = ['question', 'answer']
    list_editable = ['is_published', 'sort_order']
    readonly_fields = ['view_count', 'helpful_count', 'created_at', 'updated_at']
