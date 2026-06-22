# support/serializers.py
from rest_framework import serializers
from .models import TicketCategory, Ticket, TicketComment, FAQArticle


class TicketCategorySerializer(serializers.ModelSerializer):
    ticket_count = serializers.SerializerMethodField()

    class Meta:
        model = TicketCategory
        fields = '__all__'

    def get_ticket_count(self, obj):
        return obj.tickets.count()


class TicketCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.get_full_name', read_only=True)

    class Meta:
        model = TicketComment
        fields = '__all__'
        read_only_fields = ['author']


class TicketSerializer(serializers.ModelSerializer):
    comments = TicketCommentSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    resident_name = serializers.SerializerMethodField()
    unit_number = serializers.SerializerMethodField()
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True, default='')
    category_name = serializers.CharField(source='category.name', read_only=True, default='')

    class Meta:
        model = Ticket
        fields = '__all__'
        read_only_fields = ['ticket_number', 'created_by', 'resolved_at', 'closed_at']

    def get_resident_name(self, obj):
        target_user = obj.resident or obj.created_by
        return target_user.get_full_name() if target_user else 'Unknown'

    def get_unit_number(self, obj):
        target_user = obj.resident or obj.created_by
        return target_user.unit_number if target_user and hasattr(target_user, 'unit_number') else 'N/A'


class TicketCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ['subject', 'description', 'category', 'priority', 'resident', 'related_object_type', 'related_object_id', 'attachments']

    def to_internal_value(self, data):
        # Handle category being passed as a name string instead of UUID
        category_data = data.get('category')
        if category_data and isinstance(category_data, str):
            try:
                # Try if it's already a valid UUID
                import uuid
                uuid.UUID(category_data)
            except ValueError:
                # If not a UUID, treat it as a name and find/create the category
                from .models import TicketCategory
                category, _ = TicketCategory.objects.get_or_create(
                    name=category_data.capitalize(),
                    defaults={'description': f'Automatically created category for {category_data}'}
                )
                # Replace the name with the UUID string for the field validator
                data = data.copy()
                data['category'] = str(category.id)

        # Handle priority being passed with different casing (e.g. "Medium" vs "medium")
        priority_data = data.get('priority')
        if priority_data and isinstance(priority_data, str):
            data = data.copy() if not isinstance(data, dict) or 'category' not in data else data
            data['priority'] = priority_data.lower()

        return super().to_internal_value(data)


class FAQArticleSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True, default='')

    class Meta:
        model = FAQArticle
        fields = '__all__'
        read_only_fields = ['created_by', 'view_count', 'helpful_count']

    def to_internal_value(self, data):
        # Handle category being passed as a name string instead of UUID
        category_data = data.get('category')
        if category_data and isinstance(category_data, str) and category_data:
            try:
                import uuid
                uuid.UUID(category_data)
            except ValueError:
                from .models import TicketCategory
                category, _ = TicketCategory.objects.get_or_create(
                    name=category_data.capitalize(),
                    defaults={'description': f'Automatically created category for {category_data}'}
                )
                data = data.copy()
                data['category'] = str(category.id)
        elif category_data == '':
            data = data.copy()
            data['category'] = None

        return super().to_internal_value(data)
