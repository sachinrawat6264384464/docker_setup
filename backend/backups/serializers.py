from rest_framework import serializers
from .models import Backup


class BackupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Backup
        fields = [
            'id', 'name', 'type', 'status', 'description',
            'sizeBytes', 'createdAt', 'updatedAt', 'created_by', 'error_message'
        ]
        read_only_fields = ['id', 'createdAt', 'updatedAt', 'status', 'sizeBytes',
                            'error_message', 'created_by']


class BackupCreateSerializer(serializers.ModelSerializer):
    description = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
    )

    class Meta:
        model = Backup
        fields = ['type', 'description']

    def validate_description(self, value):
        import re
        if not re.match(r'^[a-zA-Z0-9\s.,_-]+$', value):
            raise serializers.ValidationError(
                "Description can only contain letters, numbers, spaces, dots, commas, underscores, and hyphens."
            )
        if Backup.objects.filter(description=value).exists():
            raise serializers.ValidationError(
                "A backup with this description already exists."
            )
        return value
