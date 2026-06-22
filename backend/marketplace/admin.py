from django.contrib import admin
from .models import MarketItem, ItemImage, MarketInterest

class ItemImageInline(admin.TabularInline):
    model = ItemImage
    extra = 1

@admin.register(MarketItem)
class MarketItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'seller', 'item_type', 'price', 'status', 'created_at']
    list_filter = ['status', 'item_type', 'category']
    search_fields = ['title', 'description', 'seller__email']
    inlines = [ItemImageInline]
    actions = ['approve_items', 'reject_items']

    def approve_items(self, request, queryset):
        queryset.update(status='active', approved_by=request.user)
    approve_items.short_description = "Approve selected items"

    def reject_items(self, request, queryset):
        queryset.update(status='rejected')
    reject_items.short_description = "Reject selected items"

@admin.register(MarketInterest)
class MarketInterestAdmin(admin.ModelAdmin):
    list_display = ['item', 'buyer', 'created_at']
    list_filter = ['created_at']
    search_fields = ['item__title', 'buyer__email']
