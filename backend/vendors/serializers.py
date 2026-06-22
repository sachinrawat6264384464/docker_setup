# vendors/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction, connection
from maintenance.models import MaintenanceRequest
from .models import (
    VendorCategory, Vendor, VendorService, VendorContract,
    VendorReview, VendorPayment, VendorInsurance
)

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user data"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class VendorCategorySerializer(serializers.ModelSerializer):
    vendor_count = serializers.SerializerMethodField()
    
    class Meta:
        model = VendorCategory
        fields = [
            'id', 'name', 'description', 'icon',
            'is_active', 'vendor_count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_vendor_count(self, obj):
        return obj.vendors.filter(status='active').count()


class VendorServiceSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = VendorService
        fields = [
            'id', 'vendor', 'category', 'category_name',
            'service_name', 'description', 'pricing_type',
            'base_price', 'is_active', 'min_notice_hours',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class VendorSerializer(serializers.ModelSerializer):
    categories = VendorCategorySerializer(many=True, read_only=True)
    category_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    services = VendorServiceSerializer(many=True, read_only=True)
    user = UserMiniSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    username = serializers.CharField(write_only=True, required=False, allow_blank=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, style={'input_type': 'password'})
    verified_by_user = UserMiniSerializer(source='verified_by', read_only=True)
    rating_display = serializers.SerializerMethodField()
    is_license_expired = serializers.SerializerMethodField()
    
    class Meta:
        model = Vendor
        fields = [
            'id', 'vendor_number', 'company_name', 'vendor_type',
            'categories', 'category_ids', 'user', 'user_id', 'username', 'password', 'contact_person', 'email',
            'phone', 'alternate_phone', 'website', 'address_line1',
            'address_line2', 'city', 'district', 'state', 'zip_code', 'country',
            'tax_id', 'license_number', 'license_expiry', 'status',
            'is_preferred', 'is_verified', 'verified_at', 'verified_by_user',
            'average_rating', 'rating_display', 'total_reviews', 'total_jobs',
            'payment_terms', 'hourly_rate', 'w9_form', 'notes', 'availability_preferences',
            'contract_start_date', 'contract_end_date', 'contract_value',
            'is_license_expired', 'services', 'created_at', 'updated_at',
            'last_job_date'
        ]
        read_only_fields = [
            'id', 'vendor_number', 'is_verified', 'verified_at',
            'average_rating', 'total_reviews', 'total_jobs',
            'created_at', 'updated_at', 'last_job_date'
        ]
        extra_kwargs = {
            'contact_person': {'required': False, 'default': ''},
            'phone': {'required': False, 'default': ''},
            'address_line1': {'required': False, 'default': ''},
            'address_line2': {'required': False, 'default': ''},
            'city': {'required': False, 'default': ''},
            'district': {'required': False, 'default': ''},
            'state': {'required': False, 'default': ''},
            'zip_code': {'required': False, 'default': ''},
        }
    
    def get_rating_display(self, obj):
        return {
            'average': float(obj.average_rating),
            'total_reviews': obj.total_reviews,
            'stars': '⭐' * int(obj.average_rating)
        }
    
    def get_is_license_expired(self, obj):
        if not obj.license_expiry:
            return None
        from django.utils import timezone
        return timezone.now().date() > obj.license_expiry
    
    def create(self, validated_data):
        category_ids = validated_data.pop('category_ids', [])
        user_id = validated_data.pop('user_id', None)
        username = validated_data.pop('username', None)
        password = validated_data.pop('password', None)

        if user_id is None and (username or password):
            if not username or not password:
                raise serializers.ValidationError({
                    'username': 'Username and password are required when creating vendor credentials.',
                    'password': 'Username and password are required when creating vendor credentials.',
                })

            if User.objects.filter(username__iexact=username).exists():
                raise serializers.ValidationError({
                    'username': 'This username is already in use.',
                })

            email = validated_data.get('email')
            if email and User.objects.filter(email__iexact=email).exists():
                raise serializers.ValidationError({
                    'email': 'A user with this email already exists.',
                })

            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=username,
                        email=validated_data.get('email', ''),
                        password=password,
                        role='tenant_vendor',
                        tenant_id=connection.schema_name,
                        is_active=True,
                        is_approved=True,
                        email_verified=True,
                    )
                    user._raw_password = password  # Store temporarily for welcome email
                    validated_data['user'] = user

                    if user_id is not None:
                        validated_data['user_id'] = user_id

                    vendor = super().create(validated_data)

                    if category_ids:
                        vendor.categories.set(category_ids)

                    return vendor
            except IntegrityError as exc:
                raise serializers.ValidationError({
                    'detail': 'Unable to create vendor credentials. Please use a different username.'
                }) from exc

        if user_id is not None:
            validated_data['user_id'] = user_id
        vendor = super().create(validated_data)
        
        if category_ids:
            vendor.categories.set(category_ids)
        
        return vendor
    
    def update(self, instance, validated_data):
        category_ids = validated_data.pop('category_ids', None)
        user_id = validated_data.pop('user_id', None)
        username = validated_data.pop('username', None)
        password = validated_data.pop('password', None)

        if instance.user:
            user_updated = False
            if username and instance.user.username != username:
                instance.user.username = username
                user_updated = True
            if password:
                instance.user.set_password(password)
                user_updated = True
            
            if not getattr(instance.user, 'tenant_id', None):
                instance.user.tenant_id = connection.schema_name
                user_updated = True
                
            if user_updated:
                instance.user.save()

        if user_id is not None:
            validated_data['user_id'] = user_id
        vendor = super().update(instance, validated_data)
        
        if category_ids is not None:
            vendor.categories.set(category_ids)
        
        return vendor


class VendorContractSerializer(serializers.ModelSerializer):
    vendor = VendorSerializer(read_only=True)
    vendor_id = serializers.UUIDField(write_only=True)
    created_by_user = UserMiniSerializer(source='created_by', read_only=True)
    is_fully_signed = serializers.SerializerMethodField()
    is_active_contract = serializers.SerializerMethodField()
    
    class Meta:
        model = VendorContract
        fields = [
            'id', 'contract_number', 'vendor', 'vendor_id',
            'contract_type', 'title', 'description', 'scope_of_work',
            'contract_value', 'payment_schedule', 'start_date',
            'end_date', 'status', 'contract_document', 'signed_document',
            'signed_by_vendor', 'signed_by_management',
            'vendor_signature_date', 'management_signature_date',
            'created_by_user', 'is_fully_signed', 'is_active_contract',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'contract_number', 'created_at', 'updated_at'
        ]
    
    def get_is_fully_signed(self, obj):
        return obj.signed_by_vendor and obj.signed_by_management
    
    def get_is_active_contract(self, obj):
        if obj.status != 'active':
            return False
        
        from django.utils import timezone
        now = timezone.now().date()
        
        if obj.end_date and now > obj.end_date:
            return False
        
        return now >= obj.start_date
    
    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['created_by'] = request.user
        return super().create(validated_data)


class VendorReviewSerializer(serializers.ModelSerializer):
    vendor = VendorSerializer(read_only=True)
    vendor_id = serializers.UUIDField(write_only=True)
    reviewed_by_user = UserMiniSerializer(source='reviewed_by', read_only=True)
    average_rating = serializers.SerializerMethodField()
    
    class Meta:
        model = VendorReview
        fields = [
            'id', 'vendor', 'vendor_id', 'reviewed_by_user',
            'overall_rating', 'quality_rating', 'timeliness_rating',
            'professionalism_rating', 'value_rating', 'average_rating',
            'title', 'comment', 'work_order_id', 'is_verified',
            'would_recommend', 'vendor_response', 'responded_at',
            'created_at'
        ]
        read_only_fields = [
            'id', 'is_verified', 'vendor_response',
            'responded_at', 'created_at'
        ]
    
    def get_average_rating(self, obj):
        ratings = [
            obj.overall_rating,
            obj.quality_rating,
            obj.timeliness_rating,
            obj.professionalism_rating,
            obj.value_rating
        ]
        return round(sum(ratings) / len(ratings), 2)
    
    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['reviewed_by'] = request.user
        return super().create(validated_data)


class VendorPaymentSerializer(serializers.ModelSerializer):
    vendor = VendorSerializer(read_only=True)
    vendor_id = serializers.UUIDField(write_only=True)
    contract = VendorContractSerializer(read_only=True)
    contract_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    created_by_user = UserMiniSerializer(source='created_by', read_only=True)
    approved_by_user = UserMiniSerializer(source='approved_by', read_only=True)
    is_overdue = serializers.SerializerMethodField()
    days_until_due = serializers.SerializerMethodField()
    
    class Meta:
        model = VendorPayment
        fields = [
            'id', 'payment_number', 'vendor', 'vendor_id',
            'contract', 'contract_id', 'amount', 'description',
            'invoice_number', 'invoice_date', 'status', 'due_date',
            'paid_date', 'invoice_document', 'payment_receipt',
            'notes', 'created_by_user', 'approved_by_user',
            'approved_at', 'is_overdue', 'days_until_due',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'payment_number', 'approved_at',
            'created_at', 'updated_at'
        ]
    
    def get_is_overdue(self, obj):
        if obj.status == 'paid':
            return False
        
        from django.utils import timezone
        return timezone.now().date() > obj.due_date
    
    def get_days_until_due(self, obj):
        if obj.status == 'paid':
            return None
        
        from django.utils import timezone
        delta = obj.due_date - timezone.now().date()
        return delta.days
    
    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['created_by'] = request.user
        return super().create(validated_data)


class VendorInsuranceSerializer(serializers.ModelSerializer):
    vendor = VendorSerializer(read_only=True)
    vendor_id = serializers.UUIDField(write_only=True)
    verified_by_user = UserMiniSerializer(source='verified_by', read_only=True)
    is_current = serializers.SerializerMethodField()
    days_until_expiry = serializers.SerializerMethodField()
    
    class Meta:
        model = VendorInsurance
        fields = [
            'id', 'vendor', 'vendor_id', 'insurance_type',
            'policy_number', 'insurance_company', 'coverage_amount',
            'effective_date', 'expiry_date', 'certificate_document',
            'is_verified', 'verified_by_user', 'verified_at',
            'is_current', 'days_until_expiry',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'verified_at', 'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'certificate_document': {'required': False, 'allow_null': True},
        }
    
    def get_is_current(self, obj):
        return not obj.is_expired()
    
    def get_days_until_expiry(self, obj):
        from django.utils import timezone
        delta = obj.expiry_date - timezone.now().date()
        return delta.days

    def create(self, validated_data):
        vendor_id = validated_data.pop('vendor_id')
        validated_data['vendor_id'] = vendor_id
        validated_data.setdefault('certificate_document', 'vendors/insurance/placeholder.txt')
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('vendor_id', None)
        return super().update(instance, validated_data)


class VendorWorkOrderSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source='requested_by.get_full_name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        model = MaintenanceRequest
        fields = [
            'id', 'request_number', 'category', 'category_display', 'priority', 'priority_display',
            'title', 'description', 'building', 'unit_number', 'specific_location',
            'status', 'status_display', 'requested_by_name', 'assigned_to_name',
            'requested_date', 'assigned_date', 'started_date', 'completed_date',
            'preferred_date', 'preferred_time', 'access_instructions',
            'work_performed', 'parts_used', 'parts_cost', 'labor_cost', 'total_cost',
            'photos_before', 'photos_after', 'technician_notes', 'admin_notes',
            'rating', 'feedback', 'feedback_date',
        ]
        read_only_fields = [
            'id', 'request_number', 'category', 'category_display', 'priority', 'priority_display',
            'title', 'description', 'building', 'unit_number', 'specific_location',
            'requested_by_name', 'assigned_to_name', 'requested_date', 'assigned_date',
            'started_date', 'completed_date', 'admin_notes', 'rating', 'feedback', 'feedback_date',
        ]