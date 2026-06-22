from rest_framework import serializers
from .models import PricingPlan, PlanFeature, Subscription, PlanService, PlanServiceMapping, AddOnRequest, TenantAddonGrant


class PlanServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanService
        fields = ['id', 'name', 'description', 'price_per_unit', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_price_per_unit(self, value):
        if value < 0:
            raise serializers.ValidationError("Price per unit cannot be negative.")
        return value


class PlanServiceMappingSerializer(serializers.ModelSerializer):
    service = PlanServiceSerializer(read_only=True)
    service_id = serializers.UUIDField(write_only=True)
    plan_id = serializers.UUIDField(write_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    service_price = serializers.DecimalField(source='service.price_per_unit', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PlanServiceMapping
        fields = ['id', 'plan', 'plan_id', 'plan_name', 'service', 'service_id', 'service_price', 'is_included']
        read_only_fields = ['id', 'plan']

    def create(self, validated_data):
        plan_id = validated_data.pop('plan_id')
        service_id = validated_data.pop('service_id')
        plan = PricingPlan.objects.get(id=plan_id)
        service = PlanService.objects.get(id=service_id)
        return PlanServiceMapping.objects.create(plan=plan, service=service, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('plan_id', None)
        validated_data.pop('service_id', None)
        instance.is_included = validated_data.get('is_included', instance.is_included)
        instance.save()
        return instance


class PlanFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanFeature
        fields = ['feature_name', 'feature_key', 'is_included', 'limit_value', 'display_order']


class PricingPlanSerializer(serializers.ModelSerializer):
    features = serializers.SerializerMethodField()

    class Meta:
        model = PricingPlan
        fields = ['id', 'name', 'slug', 'description', 'tagline', 'monthly_price',
                  'annual_price', 'unit_limit', 'manager_limit', 'is_featured',
                  'is_custom_pricing', 'color', 'features', 'display_order']

    def validate(self, attrs):
        numeric_fields = ['monthly_price', 'annual_price', 'unit_limit', 'manager_limit', 'display_order']
        for field in numeric_fields:
            if field in attrs and attrs[field] is not None:
                if attrs[field] < 0:
                    raise serializers.ValidationError({field: f"{field.replace('_', ' ').capitalize()} cannot be negative."})
        return attrs

    def get_features(self, obj):
        # IMPORTANT: use .all() NOT .select_related() here so Django's
        # prefetch_related('service_mappings__service') cache is used.
        # Calling .select_related() creates a fresh queryset that bypasses
        # the prefetch cache, causing N+1 queries (one per plan).
        mappings = obj.service_mappings.all()
        features_list = []
        for m in mappings:
            features_list.append({
                'feature_name': m.service.name,
                'is_included': m.is_included,
                'limit_value': '',
                'display_order': 0
            })

        # Fallback to existing PlanFeature objects if no mappings
        if not features_list:
            for pf in obj.features.all():
                features_list.append({
                    'feature_name': pf.feature_name,
                    'is_included': pf.is_included,
                    'limit_value': pf.limit_value,
                    'display_order': pf.display_order
                })
        return features_list


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PricingPlanSerializer(read_only=True)
    plan_id = serializers.UUIDField(write_only=True, required=False)
    days_until_renewal = serializers.SerializerMethodField()
    is_trial = serializers.SerializerMethodField()
    usage_stats = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = ['id', 'plan', 'plan_id', 'billing_cycle', 'status',
                  'current_period_start', 'current_period_end', 'trial_ends_at',
                  'cancelled_at', 'razorpay_subscription_id',
                  'days_until_renewal', 'is_trial', 'tenant_schema', 'usage_stats', 'created_at']

    def get_days_until_renewal(self, obj):
        if not obj.current_period_end:
            return None
        from django.utils import timezone
        delta = obj.current_period_end - timezone.now()
        return max(0, delta.days)

    def get_is_trial(self, obj):
        return obj.status == 'trialing'

    def get_usage_stats(self, obj):
        """Calculate current usage for units and managers.
        
        Cached for 5 minutes per subscription to avoid 2 DB queries
        per serialized subscription row.
        """
        from django.core.cache import cache
        cache_key = f'usage_stats_{obj.id}'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            from properties.models import Unit
            from django.contrib.auth import get_user_model
            User = get_user_model()

            unit_count = Unit.objects.count()
            manager_count = User.objects.filter(role__in=['manager', 'admin']).count()

            result = {
                'units': {
                    'used': unit_count,
                    'limit': obj.plan.unit_limit if obj.plan else 0
                },
                'managers': {
                    'used': manager_count,
                    'limit': obj.plan.manager_limit if obj.plan else 0
                }
            }
            cache.set(cache_key, result, 300)  # cache for 5 minutes
            return result
        except Exception:
            return None


class AddOnRequestSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    service_description = serializers.CharField(source='service.description', read_only=True)
    service_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = AddOnRequest
        fields = [
            'id', 'tenant_schema', 'service', 'service_id', 'service_name', 'service_description',
            'status', 'requested_by_email', 'requested_by_name', 'reviewed_by_name',
            'monthly_price', 'quantity', 'notes', 'review_notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'service', 'tenant_schema', 'status', 'reviewed_by_name',
                            'monthly_price', 'review_notes', 'created_at', 'updated_at']

    def create(self, validated_data):
        service_id = validated_data.pop('service_id')
        service = PlanService.objects.get(id=service_id)
        quantity = validated_data.get('quantity', 1)
        validated_data['monthly_price'] = service.price_per_unit * quantity
        return AddOnRequest.objects.create(service=service, **validated_data)


class TenantAddonGrantSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    service_description = serializers.CharField(source='service.description', read_only=True)
    service_price = serializers.DecimalField(source='service.price_per_unit', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = TenantAddonGrant
        fields = ['id', 'tenant_schema', 'service', 'service_name', 'service_description',
                  'service_price', 'is_active', 'granted_at', 'revoked_at']
        read_only_fields = ['id', 'tenant_schema', 'service', 'granted_at']
