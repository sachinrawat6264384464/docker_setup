from rest_framework import serializers
from .models import MarketItem, ItemImage, MarketInterest
from django.contrib.auth import get_user_model

User = get_user_model()

class SellerSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email']

class ItemImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemImage
        fields = ['id', 'image', 'is_primary']

class MarketItemSerializer(serializers.ModelSerializer):
    seller_details = SellerSerializer(source='seller', read_only=True)
    images = ItemImageSerializer(many=True, read_only=True)
    primary_image = serializers.SerializerMethodField()
    uploaded_images = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False
    )

    class Meta:
        model = MarketItem
        fields = [
            'id', 'seller', 'seller_details', 'title', 'description', 
            'category', 'item_type', 'price', 'is_negotiable', 
            'status', 'images', 'primary_image', 'uploaded_images', 'created_at'
        ]
        read_only_fields = ['seller', 'status', 'created_at']

    def get_primary_image(self, obj):
        # Use python list to avoid N+1 database queries on prefetched related objects
        images = list(obj.images.all())
        if not images:
            return None
            
        primary = next((img for img in images if img.is_primary), None)
        if not primary:
            primary = images[0]
            
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(primary.image.url)
        return primary.image.url

    def create(self, validated_data):
        uploaded_images = validated_data.pop('uploaded_images', [])
        item = MarketItem.objects.create(**validated_data)
        
        for idx, img in enumerate(uploaded_images):
            ItemImage.objects.create(
                item=item, 
                image=img, 
                is_primary=(idx == 0)
            )
        return item

class MarketInterestSerializer(serializers.ModelSerializer):
    buyer_details = SellerSerializer(source='buyer', read_only=True)
    
    class Meta:
        model = MarketInterest
        fields = ['id', 'item', 'buyer', 'buyer_details', 'message', 'created_at']
        read_only_fields = ['buyer', 'created_at']
