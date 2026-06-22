# accounts/people_hub_serializers.py - People Hub Data Serializers
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from .models import UserProfile

User = get_user_model()

class ResidentProfileSerializer(serializers.ModelSerializer):
    """Detailed profile information for residents"""
    class Meta:
        model = UserProfile
        fields = [
            'date_of_birth', 'gender', 'occupation', 'bio',
            'address_line_1', 'address_line_2', 'city', 'state', 
            'postal_code', 'country', 'lease_start_date', 'lease_end_date',
            'monthly_rent', 'security_deposit', 'household_size', 
            'has_pets', 'pet_details', 'vehicle_count', 'vehicle_details',
            'medical_conditions', 'insurance_provider', 'insurance_policy_number'
        ]

class ResidentListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for resident list view"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    profile_completion = serializers.SerializerMethodField()
    lease_status = serializers.SerializerMethodField()
    resident_type = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name', 'phone',
            'unit_number', 'building_name', 'role', 'is_active',
            'is_approved', 'email_verified', 'created_at',
            'profile_completion', 'lease_status', 'resident_type'
        ]

    def get_resident_type(self, obj):
        """Derive human-friendly resident type from role"""
        if obj.role == 'owner':
            return 'owner'
        return 'tenant'
    
    def get_profile_completion(self, obj):
        """Calculate profile completion percentage"""
        if not hasattr(obj, 'profile'):
            return 0
        
        profile = obj.profile
        total_fields = 15
        completed_fields = 0
        
        # Check basic fields
        if obj.first_name: completed_fields += 1
        if obj.last_name: completed_fields += 1
        if obj.email: completed_fields += 1
        if obj.phone: completed_fields += 1
        if obj.unit_number: completed_fields += 1
        if obj.building_name: completed_fields += 1
        if obj.emergency_contact_name: completed_fields += 1
        if obj.emergency_contact_phone: completed_fields += 1
        
        # Check profile fields
        if profile.date_of_birth: completed_fields += 1
        if profile.occupation: completed_fields += 1
        if profile.lease_start_date: completed_fields += 1
        if profile.monthly_rent: completed_fields += 1
        if profile.address_line_1: completed_fields += 1
        if profile.city: completed_fields += 1
        if profile.postal_code: completed_fields += 1
        
        return round((completed_fields / total_fields) * 100, 2)
    
    def get_lease_status(self, obj):
        """Get active lease status"""
        try:
            if hasattr(obj, 'prefetched_active_leases'):
                active_lease = obj.prefetched_active_leases[0] if obj.prefetched_active_leases else None
            else:
                from properties.models import Lease
                active_lease = Lease.objects.filter(
                    tenant=obj,
                    status='active'
                ).first()
            
            if active_lease:
                return {
                    'has_lease': True,
                    'start_date': active_lease.start_date,
                    'end_date': active_lease.end_date,
                    'monthly_rent': str(active_lease.monthly_rent)
                }
        except:
            pass
        
        return {'has_lease': False}

class ResidentDetailSerializer(serializers.ModelSerializer):
    """Complete resident information including profile and lease"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    profile = ResidentProfileSerializer(read_only=True)
    active_leases = serializers.SerializerMethodField()
    current_unit = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'phone', 'avatar', 'unit_number', 'building_name', 'role',
            'emergency_contact_name', 'emergency_contact_phone',
            'notification_preferences', 'email_verified', 'is_approved',
            'is_active', 'last_activity', 'date_joined', 'created_at',
            'profile', 'active_leases', 'current_unit'
        ]
    
    def get_active_leases(self, obj):
        """Get all active leases for this resident"""
        try:
            from properties.models import Lease
            leases = Lease.objects.filter(
                tenant=obj,
                status='active'
            ).select_related('unit__building')
            
            return [{
                'id': str(lease.id),
                'unit': f"{lease.unit.building.name} - {lease.unit.unit_number}",
                'start_date': lease.start_date,
                'end_date': lease.end_date,
                'monthly_rent': str(lease.monthly_rent),
                'status': lease.status
            } for lease in leases]
        except:
            return []
    
    def get_current_unit(self, obj):
        """Get current unit information"""
        try:
            from properties.models import Unit
            # Attempt to find unit by explicit user assignment
            if obj.unit_number and obj.building_name:
                unit = Unit.objects.filter(
                    unit_number__iexact=obj.unit_number,
                    building__name__iexact=obj.building_name
                ).select_related('building').first()
                if unit:
                    return {
                        'id': str(unit.id),
                        'unit_number': unit.unit_number,
                        'building': unit.building.name,
                        'unit_type': unit.unit_type,
                        'floor': unit.floor,
                        'area_sqft': unit.square_feet, # Fixed field name from area_sqft to square_feet based on models.py
                        'monthly_rent': str(unit.monthly_rent) if unit.monthly_rent else "0"
                    }
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error fetching current unit for {obj.id}: {str(e)}")
            pass
        
        return None

class ResidentCreateSerializer(serializers.ModelSerializer):
    """Create new resident (owner or tenant)"""
    profile_data = serializers.JSONField(required=False, write_only=True)
    unit_id = serializers.UUIDField(required=False, write_only=True, allow_null=True)
    # 'owner' | 'tenant' — determines role and unit assignment logic
    resident_type = serializers.ChoiceField(
        choices=[('owner', 'Owner'), ('tenant', 'Tenant')],
        default='tenant',
        write_only=True,
        required=False,
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name', 'phone',
            'unit_number', 'building_name', 'emergency_contact_name',
            'emergency_contact_phone', 'password', 'profile_data',
            'unit_id', 'resident_type',
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': True, 'min_length': 8}
        }

    def validate_email(self, value):
        normalized_email = value.lower()
        if User.objects.filter(email__iexact=normalized_email).exists():
            raise serializers.ValidationError(f"The email '{normalized_email}' is already registered. Please use a different one.")
        return normalized_email

    def validate_username(self, value):
        normalized_username = value.strip()
        if User.objects.filter(username__iexact=normalized_username).exists():
            raise serializers.ValidationError(f"The username '{normalized_username}' is already taken. Please choose another one.")
        return normalized_username

    def _get_manager_unit_pairs(self):
        """Get (building_name, unit_number) pairs from FM scope."""
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or getattr(user, 'role', None) != 'facility_manager':
            return None
        try:
            from accounts.fm_scope import get_fm_unit_pairs
            return list(get_fm_unit_pairs(user) or [])
        except Exception:
            return []

    def _assert_unit_in_manager_scope(self, unit):
        """Facility managers can now assign residents to any unit in the organization."""
        return

    def validate_password(self, value):
        # Bypass password validation for easier account creation
        return value

    def _assign_owner_unit(self, user, unit_id, unit_number, building_name):
        """Assign a unit to an owner without strict eligibility checks."""
        import logging
        log = logging.getLogger(__name__)
        try:
            from properties.models import Unit
            if unit_id:
                unit = Unit.objects.select_related('building').filter(id=unit_id).first()
            elif unit_number and building_name:
                unit = Unit.objects.select_related('building').filter(
                    building__name__iexact=building_name,
                    unit_number__iexact=unit_number,
                ).first()
            else:
                return

            if not unit:
                return

            # Skip scope and eligibility checks to allow immediate assignment
            if unit.unit_type != 'tenant_occupied' and not unit.leases.filter(status='active').exists():
                unit.status = 'occupied'
                unit.is_occupied = True
                unit.unit_type = 'owner_occupied'
                unit.current_resident = user.get_full_name() or user.email
            
            unit.owner_user = user
            unit.owner_first_name = user.first_name
            unit.owner_last_name = user.last_name
            unit.owner_email = user.email
            unit.owner_phone = user.phone or ''
            unit.save()
            
            user.unit_number = unit.unit_number
            user.building_name = unit.building.name
            user.save(update_fields=['unit_number', 'building_name'])
        except serializers.ValidationError:
            raise
        except Exception as e:
            log.error(f"Error assigning owner unit to {user.email}: {e}")

    def _assign_tenant_unit(self, user, unit_id, unit_number, building_name):
        """Assign a unit to a tenant. Eligible: vacant or tenant_occupied (just created) units."""
        import logging
        log = logging.getLogger(__name__)
        try:
            from properties.models import Unit
            assigned_unit = None
            if unit_id:
                assigned_unit = Unit.objects.select_related('building').filter(id=unit_id).first()
            elif unit_number and building_name:
                assigned_unit = Unit.objects.select_related('building').filter(
                    building__name__iexact=building_name,
                    unit_number__iexact=unit_number,
                ).first()

            if not assigned_unit:
                log.warning(f"_assign_tenant_unit: No unit found for unit_id={unit_id}, unit_number={unit_number}, building={building_name}")
                return

            self._assert_unit_in_manager_scope(assigned_unit)

            # Enforce one resident per apartment — only vacant/tenant_occupied (no active occupant) units allowed
            has_active_tenant = False
            if assigned_unit.unit_type == 'owner_occupied':
                has_active_tenant = True
            elif assigned_unit.leases.filter(status='active').exists():
                has_active_tenant = True
            else:
                from django.contrib.auth import get_user_model
                _User = get_user_model()
                if _User.objects.filter(
                    role='tenant',
                    is_active=True,
                    building_name__iexact=assigned_unit.building.name if assigned_unit.building else '',
                    unit_number__iexact=assigned_unit.unit_number
                ).exclude(id=user.id).exists():
                    has_active_tenant = True

            if has_active_tenant:
                raise serializers.ValidationError({
                    'unit_id': 'This apartment is already occupied by another resident.'
                })

            # Update the unit record
            assigned_unit.status = 'occupied'
            assigned_unit.is_occupied = True
            assigned_unit.unit_type = 'tenant_occupied'
            assigned_unit.current_resident = user.get_full_name() or user.email
            assigned_unit.save()

            # Auto-populate building_name / unit_number on user (save full object to avoid update_fields issues)
            bldg_name = assigned_unit.building.name if assigned_unit.building else ''
            unit_num = assigned_unit.unit_number
            log.info(f"_assign_tenant_unit: Assigning unit_number='{unit_num}', building_name='{bldg_name}' to user {user.email}")
            user.unit_number = unit_num
            user.building_name = bldg_name
            # Save with explicit field list first, fall back to full save
            try:
                user.save(update_fields=['unit_number', 'building_name'])
            except Exception as save_err:
                log.warning(f"_assign_tenant_unit: update_fields save failed ({save_err}), trying full save")
                user.save()
            log.info(f"_assign_tenant_unit: Successfully set unit info for user {user.email}")
        except serializers.ValidationError:
            raise
        except Exception as e:
            import traceback
            log.error(f"Error assigning tenant unit to {getattr(user, 'email', '?')}: {e}\n{traceback.format_exc()}")

    def validate(self, attrs):
        """Facility managers can create residents with or without immediate unit assignment."""
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        profile_data = validated_data.pop('profile_data', {})
        password = validated_data.pop('password')
        unit_id = validated_data.pop('unit_id', None)
        resident_type = validated_data.pop('resident_type', 'tenant')
        unit_number = (validated_data.get('unit_number') or '').strip()
        building_name = (validated_data.get('building_name') or '').strip()
        request = self.context.get('request')

        if request and request.user.is_authenticated:
            from django.db import connection as _conn
            # master_admin users live in the public schema (tenant_id=None/'public').
            # When they create a resident, use the active DB connection schema so the
            # new user is stored in the correct tenant schema and redirects to
            # /residents/dashboard (not masteradmin) after login.
            requester_tenant_id = request.user.tenant_id
            if not requester_tenant_id or requester_tenant_id == 'public':
                schema = getattr(_conn, 'schema_name', None)
                if schema and schema != 'public':
                    requester_tenant_id = schema
            validated_data['tenant_id'] = requester_tenant_id

        # Set role based on resident_type selection
        validated_data['role'] = 'owner' if resident_type == 'owner' else 'tenant'
        validated_data['is_approved'] = True

        try:
            user = User.objects.create_user(**validated_data, password=password)
            user._raw_password = password  # Store temporarily for welcome email
        except IntegrityError:
            conflicting_username = validated_data.get('username')
            conflicting_email = validated_data.get('email')
            if conflicting_username and User.objects.filter(username__iexact=conflicting_username).exists():
                raise serializers.ValidationError({'username': 'Username already exists'})
            if conflicting_email and User.objects.filter(email__iexact=conflicting_email).exists():
                raise serializers.ValidationError({'email': 'User with this email already exists'})
            raise serializers.ValidationError({'non_field_errors': ['Could not create resident due to a data conflict.']})

        # Assign unit based on resident type
        if resident_type == 'owner':
            self._assign_owner_unit(user, unit_id, unit_number, building_name)
        else:
            self._assign_tenant_unit(user, unit_id, unit_number, building_name)

        # Update profile with additional data
        if profile_data and hasattr(user, 'profile'):
            profile = user.profile
            for key, value in profile_data.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
            profile.save()

        return user

class ResidentUpdateSerializer(serializers.ModelSerializer):
    """Update resident information"""
    profile_data = serializers.JSONField(required=False, write_only=True)
    
    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'email', 'phone', 'avatar',
            'unit_number', 'building_name', 'emergency_contact_name',
            'emergency_contact_phone', 'notification_preferences',
            'is_approved', 'is_active', 'profile_data', 'role'
        ]

    def _get_manager_unit_pairs(self):
        """Get (building_name, unit_number) pairs from FM scope."""
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or getattr(user, 'role', None) != 'facility_manager':
            return None
        try:
            from accounts.fm_scope import get_fm_unit_pairs
            return list(get_fm_unit_pairs(user) or [])
        except Exception:
            return []
    
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile_data', {})
        old_unit_number = (instance.unit_number or '').strip()
        old_building_name = (instance.building_name or '').strip()
        new_unit_number = (validated_data.get('unit_number') if 'unit_number' in validated_data else old_unit_number).strip()
        new_building_name = (validated_data.get('building_name') if 'building_name' in validated_data else old_building_name).strip()

        unit_pairs = self._get_manager_unit_pairs()
        if unit_pairs is not None and (new_unit_number != old_unit_number or new_building_name != old_building_name):
            if not unit_pairs:
                raise serializers.ValidationError({'unit_number': 'You do not have any assigned units.'})
            
            # Validate that the new unit is in FM's scope
            normalized_pairs = {(str(b).strip().lower(), str(u).strip().lower()) for b, u in unit_pairs if b and u}
            query_pair = (new_building_name.lower(), new_unit_number.lower())
            
            if not normalized_pairs or query_pair not in normalized_pairs:
                raise serializers.ValidationError({'unit_number': 'You can update residents only within your assigned units.'})
        
        # Update user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        self._sync_assigned_unit(instance, old_building_name, old_unit_number, new_building_name, new_unit_number)
        
        # Update profile
        if profile_data and hasattr(instance, 'profile'):
            profile = instance.profile
            for key, value in profile_data.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
            profile.save()
        
        return instance

    def _sync_assigned_unit(self, resident, old_building_name, old_unit_number, new_building_name, new_unit_number):
        try:
            from properties.models import Unit, Lease
        except Exception:
            return

        def vacate_unit(building_name, unit_number):
            if not building_name or not unit_number:
                return
            Unit.objects.filter(
                building__name__iexact=building_name,
                unit_number__iexact=unit_number,
            ).update(
                status='available',
                is_occupied=False,
                unit_type='vacant',
                current_resident=''
            )

        def occupy_unit(building_name, unit_number):
            if not building_name or not unit_number:
                return

            unit = Unit.objects.select_related('building').filter(
                building__name__iexact=building_name,
                unit_number__iexact=unit_number,
            ).first()
            if not unit:
                return

            if resident.role == 'owner':
                if unit.unit_type != 'tenant_occupied' and not unit.leases.filter(status='active').exists():
                    unit.status = 'occupied'
                    unit.is_occupied = True
                    unit.unit_type = 'owner_occupied'
                    unit.current_resident = resident.get_full_name() or resident.email
                unit.owner_user = resident
                unit.owner_first_name = resident.first_name
                unit.owner_last_name = resident.last_name
                unit.owner_email = resident.email
                unit.owner_phone = getattr(resident, 'phone', '') or ''
                unit.owner_address = getattr(resident, 'address', '') or ''
            else:
                unit.status = 'occupied'
                unit.is_occupied = True
                unit.unit_type = 'tenant_occupied'
                unit.current_resident = resident.get_full_name() or resident.email
            unit.save()

        # If resident has an active lease, keep lease unit occupied and do not override it.
        active_lease = Lease.objects.filter(tenant=resident, status='active').select_related('unit').first()
        if active_lease and active_lease.unit_id:
            active_unit = active_lease.unit
            if active_unit:
                active_unit.status = 'occupied'
                active_unit.is_occupied = True
                active_unit.unit_type = 'tenant_occupied'
                active_unit.current_resident = resident.get_full_name() or resident.email
                active_unit.save()
            return

        old_assigned = old_building_name and old_unit_number
        new_assigned = new_building_name and new_unit_number

        # Vacate old unit if assignment changed or got cleared
        if old_assigned and (not new_assigned or old_building_name.lower() != new_building_name.lower() or old_unit_number.lower() != new_unit_number.lower()):
            vacate_unit(old_building_name, old_unit_number)

        # Occupy / sync new unit if assignment exists
        if new_assigned:
            occupy_unit(new_building_name, new_unit_number)

class BulkResidentActionSerializer(serializers.Serializer):
    """Bulk actions on residents"""
    resident_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False
    )
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False
    )
    action = serializers.ChoiceField(
        choices=['approve', 'disapprove', 'activate', 'deactivate', 'delete'],
        write_only=True
    )

    def _validate_ids_for_tenant(self, value):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Authentication required")

        if not value:
            raise serializers.ValidationError("At least one resident ID is required")

        # Keep this serializer permissive; the view reports invalid IDs while still
        # processing valid ones.
        return list(dict.fromkeys(value))
    
    def validate_resident_ids(self, value):
        return self._validate_ids_for_tenant(value)

    def validate_ids(self, value):
        return self._validate_ids_for_tenant(value)

    def validate(self, attrs):
        normalized_ids = attrs.get('resident_ids') or attrs.get('ids')
        if not normalized_ids:
            raise serializers.ValidationError({'resident_ids': 'This field is required.'})
        attrs['resident_ids'] = normalized_ids
        return attrs

class ResidentStatsSerializer(serializers.Serializer):
    """Statistics for People Hub dashboard"""
    total_residents = serializers.IntegerField()
    active_residents = serializers.IntegerField()
    inactive_residents = serializers.IntegerField()
    approved_residents = serializers.IntegerField()
    pending_approval = serializers.IntegerField()
    verified_emails = serializers.IntegerField()
    with_active_leases = serializers.IntegerField()
    recent_registrations = serializers.IntegerField()
    occupancy_rate = serializers.FloatField()

class ResidentSearchSerializer(serializers.Serializer):
    """Search/filter parameters for residents"""
    search = serializers.CharField(required=False, allow_blank=True)
    building = serializers.CharField(required=False, allow_blank=True)
    unit_number = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    is_approved = serializers.BooleanField(required=False)
    email_verified = serializers.BooleanField(required=False)
    has_lease = serializers.BooleanField(required=False)