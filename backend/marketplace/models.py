# marketplace/models.py
from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()

class MarketItem(models.Model):
    ITEM_TYPES = [
        ('sell', 'For Sale'),
        ('rent', 'For Rent'),
        ('giveaway', 'Free / Giveaway'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('active', 'Active'),
        ('sold', 'Sold / Rented'),
        ('expired', 'Expired'),
        ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Seller Details (Only Residents)
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='market_items')
    
    # Item Details
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=100) # e.g. Furniture, Electronics, Vehicles
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES, default='sell')
    
    # Pricing
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_negotiable = models.BooleanField(default=True)
    
    # Status & Moderation (Controlled by Admin/Manager)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_items')
    rejection_reason = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Marketplace Item'

    def __str__(self):
        return f"{self.title} - {self.seller.get_full_name()}"

class ItemImage(models.Model):
    item = models.ForeignKey(MarketItem, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='marketplace/items/')
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class MarketInterest(models.Model):
    """Tracks when a buyer is interested in an item"""
    item = models.ForeignKey(MarketItem, on_delete=models.CASCADE, related_name='interests')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='interested_items')
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['item', 'buyer']
