# properties/serializers.py
from rest_framework import serializers
from .models import Building, Unit, Lease, PropertyDocument, Township, Block, Floor, PropertyCity, AreaZone, FacilityManagerAssignment
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()


def _sync_fm_assignment_for_scope(*, instance, scope_type, manager, request_user):
    """Keep FacilityManagerAssignment in sync with managed_by for township/building."""
    scope_filters = {scope_type: instance, 'scope_type': scope_type}
    active_qs = FacilityManagerAssignment.objects.filter(is_active=True, **scope_filters)

    if manager and getattr(manager, 'role', None) == 'facility_manager':
        active_qs.exclude(facility_manager=manager).update(is_active=False)
        defaults = {
            'assigned_by': request_user if getattr(request_user, 'is_authenticated', False) else None,
            'is_active': True,
        }
        assignment, _ = FacilityManagerAssignment.objects.get_or_create(
            facility_manager=manager,
            **scope_filters,
            defaults=defaults,
        )
        changed = False
        if not assignment.is_active:
            assignment.is_active = True
            changed = True
        if getattr(request_user, 'is_authenticated', False) and assignment.assigned_by_id != getattr(request_user, 'id', None):
            assignment.assigned_by = request_user
            changed = True
        if changed:
            assignment.save(update_fields=['is_active', 'assigned_by'])
    else:
        active_qs.update(is_active=False)

# =========================
# BUILDING SERIALIZERS
# =========================

class BuildingSerializer(serializers.ModelSerializer):
    total_units_count = serializers.SerializerMethodField()
    occupied_units_count = serializers.SerializerMethodField()
    available_units_count = serializers.SerializerMethodField()
    managed_by_name = serializers.SerializerMethodField()
    num_blocks = serializers.SerializerMethodField()
    complete_address = serializers.SerializerMethodField()

    class Meta:
        model = Building
        fields = '__all__'

    def get_occupied_units_count(self, obj):
        if hasattr(obj, 'occupied_units_count_annotated'):
            return obj.occupied_units_count_annotated
        return self._scoped_units(obj).filter(status='occupied').count()

    def get_available_units_count(self, obj):
        if hasattr(obj, 'available_units_count_annotated'):
            return obj.available_units_count_annotated
        return self._scoped_units(obj).filter(status='available').count()

    def get_total_units_count(self, obj):
        if hasattr(obj, 'total_units_count_annotated'):
            return obj.total_units_count_annotated
        return self._scoped_units(obj).count()

    def get_num_blocks(self, obj):
        if hasattr(obj, 'num_blocks_annotated'):
            return obj.num_blocks_annotated
        block_ids = self._get_manager_block_ids()
        if block_ids is None:
            return obj.block_set.count()
        if not block_ids:
            return 0
        return obj.block_set.filter(id__in=block_ids).count()

    def _get_manager_block_ids(self):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or getattr(user, 'role', None) != 'facility_manager':
            return None
        from accounts.fm_scope import get_fm_block_ids
        ids = get_fm_block_ids(user)
        return list(ids) if ids is not None else []

    def _scoped_units(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or getattr(user, 'role', None) != 'facility_manager':
            return obj.units.all()
        from accounts.fm_scope import is_building_accessible
        if not is_building_accessible(user, obj.pk):
            return obj.units.none()
        return obj.units.all()

    def get_managed_by_name(self, obj):
        if obj.managed_by:
            name = obj.managed_by.get_full_name()
            return name if name.strip() else obj.managed_by.username
        return None

    def get_complete_address(self, obj):
        return obj.complete_address or obj.address


class BuildingCreateSerializer(serializers.ModelSerializer):
    complete_address = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Building
        fields = '__all__'

    def get_complete_address(self, obj):
        return obj.complete_address or obj.address

    def create(self, validated_data):
        request = self.context.get('request')
        manager = validated_data.get('managed_by')
        instance = super().create(validated_data)
        _sync_fm_assignment_for_scope(
            instance=instance,
            scope_type='building',
            manager=manager,
            request_user=getattr(request, 'user', None),
        )
        return instance

    def update(self, instance, validated_data):
        request = self.context.get('request')
        manager = validated_data.get('managed_by', instance.managed_by)
        instance = super().update(instance, validated_data)
        _sync_fm_assignment_for_scope(
            instance=instance,
            scope_type='building',
            manager=manager,
            request_user=getattr(request, 'user', None),
        )
        return instance


# =========================
# UNIT SERIALIZERS
# =========================

class UnitSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source='building.name', read_only=True)
    building_address = serializers.CharField(source='building.address', read_only=True)
    current_tenant = serializers.SerializerMethodField()
    active_lease = serializers.SerializerMethodField()
    unit_type_display = serializers.CharField(source='get_unit_type_display', read_only=True)
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)

    class Meta:
        model = Unit
        fields = '__all__'

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Fallback for owner details from owner_user if empty
        if instance.owner_user:
            if not ret.get('owner_first_name'):
                ret['owner_first_name'] = instance.owner_user.first_name
            if not ret.get('owner_last_name'):
                ret['owner_last_name'] = instance.owner_user.last_name
            if not ret.get('owner_email'):
                ret['owner_email'] = instance.owner_user.email
            if not ret.get('owner_phone'):
                ret['owner_phone'] = getattr(instance.owner_user, 'phone', '')
            if not ret.get('owner_address'):
                ret['owner_address'] = getattr(instance.owner_user, 'address', '')
        return ret

    def get_current_tenant(self, obj):
        # 1. Try active lease first
        if hasattr(obj, 'active_leases_prefetched'):
            active_leases = obj.active_leases_prefetched
            lease = active_leases[0] if active_leases else None
            # 2. Try any lease linked to this unit (pending/etc.)
            if not lease and hasattr(obj, 'all_leases_prefetched'):
                all_leases = obj.all_leases_prefetched
                lease = all_leases[0] if all_leases else None
        else:
            lease = obj.leases.filter(status='active').first()
            if not lease:
                lease = obj.leases.first()
            
        if lease:
            return {
                'id': str(lease.tenant.id),
                'first_name': lease.tenant.first_name,
                'last_name': lease.tenant.last_name,
                'name': lease.tenant.get_full_name(),
                'email': lease.tenant.email,
                'phone': getattr(lease.tenant, 'phone', None),
            }
        
        # No lease found — return None. Fallback user lookup removed to eliminate N+1 per-unit DB queries.
        return None


    def get_active_lease(self, obj):
        if hasattr(obj, 'active_leases_prefetched'):
            lease = obj.active_leases_prefetched[0] if obj.active_leases_prefetched else None
        else:
            lease = obj.leases.filter(status='active').first()
        if lease:
            return {
                'id': str(lease.id),
                'start_date': lease.start_date,
                'end_date': lease.end_date,
                'monthly_rent': str(lease.monthly_rent),
            }
        return None


class UnitCreateSerializer(serializers.ModelSerializer):
    building = serializers.PrimaryKeyRelatedField(queryset=Building.objects.all(), required=True, allow_null=False)
    unit_number = serializers.CharField(required=True)

    tenant_user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    tenant_first_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    tenant_last_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    tenant_email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    tenant_phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Unit
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request:
            from accounts.fm_scope import is_facility_manager, get_manager_building_ids
            if is_facility_manager(request.user):
                b_ids = get_manager_building_ids(request.user)
                if b_ids is not None:
                    self.fields['building'].queryset = Building.objects.filter(id__in=b_ids)

    def validate_owner_user(self, value):
        if value and getattr(value, 'role', None) != 'owner':
            raise serializers.ValidationError('Selected user must have the owner role.')
        return value

    def _sync_owner_fields(self, attrs):
        # Determine owner_user to use
        if 'owner_user' in attrs:
            owner_user = attrs.get('owner_user')
        elif self.instance and self.instance.owner_user:
            owner_user = self.instance.owner_user
        else:
            owner_user = None

        if owner_user:
            attrs['owner_first_name'] = owner_user.first_name or ''
            attrs['owner_last_name'] = owner_user.last_name or ''
            attrs['owner_email'] = owner_user.email or ''
            attrs['owner_phone'] = getattr(owner_user, 'phone', '') or ''
            attrs['owner_address'] = getattr(owner_user, 'address', '') or ''
        return attrs

    def validate(self, attrs):
        # Clean owner_phone and tenant_phone if they are just country prefixes (e.g., "+1")
        for key in ['owner_phone', 'tenant_phone']:
            val = attrs.get(key)
            if val:
                digits = [c for c in val if c.isdigit()]
                if len(digits) < 5:
                    attrs[key] = ''

        # If building is null during update, restore the existing one to avoid IntegrityError
        if 'building' in attrs and attrs['building'] is None and self.instance:
            attrs['building'] = self.instance.building
            
        # Get unit_type, default to 'vacant' if not provided
        unit_type = attrs.get('unit_type', 'vacant')
        building = attrs.get('building') or getattr(self.instance, 'building', None)
        floor = attrs.get('floor') if 'floor' in attrs else getattr(self.instance, 'floor', None)
        attrs = self._sync_owner_fields(attrs)
        
        # Set status and is_occupied based on unit_type
        if unit_type == 'vacant':
            attrs['status'] = 'available'
            attrs['is_occupied'] = False
        elif unit_type in ['owner_occupied', 'tenant_occupied']:
            attrs['status'] = 'occupied'
            attrs['is_occupied'] = True

        # Enforce the configured apartments-per-floor limit when a floor is provided.
        if building and floor is not None:
            apartments_per_floor = getattr(building, 'apartments_per_floor', 0) or 0
            if apartments_per_floor > 0:
                existing_units = Unit.objects.filter(building=building, floor=floor)
                if self.instance and self.instance.pk:
                    existing_units = existing_units.exclude(pk=self.instance.pk)

                if existing_units.count() >= apartments_per_floor:
                    raise serializers.ValidationError({
                        'floor': f'Floor {floor} already has the maximum of {apartments_per_floor} apartments.'
                    })
        
        return attrs

    def create(self, validated_data):
        tenant_user = validated_data.pop('tenant_user', None)
        tenant_first_name = validated_data.pop('tenant_first_name', None)
        tenant_last_name = validated_data.pop('tenant_last_name', None)
        tenant_email = validated_data.pop('tenant_email', None)
        tenant_phone = validated_data.pop('tenant_phone', None)

        from django.db import transaction
        with transaction.atomic():
            instance = super().create(validated_data)
            self._sync_owner_user_unit(instance)

            tenant_data = {
                'tenant_user': tenant_user,
                'tenant_first_name': tenant_first_name,
                'tenant_last_name': tenant_last_name,
                'tenant_email': tenant_email,
                'tenant_phone': tenant_phone,
            }
            self._sync_tenant_user_unit(instance, tenant_data)
            return instance

    def update(self, instance, validated_data):
        tenant_user = validated_data.pop('tenant_user', None)
        tenant_first_name = validated_data.pop('tenant_first_name', None)
        tenant_last_name = validated_data.pop('tenant_last_name', None)
        tenant_email = validated_data.pop('tenant_email', None)
        tenant_phone = validated_data.pop('tenant_phone', None)

        from django.db import transaction
        with transaction.atomic():
            old_owner_user = instance.owner_user
            old_unit_number = instance.unit_number
            old_building_name = instance.building.name if instance.building else ''

            from django.contrib.auth import get_user_model
            User = get_user_model()
            old_tenant_user = User.objects.filter(
                role='tenant',
                unit_number=old_unit_number,
                building_name=old_building_name
            ).first()

            instance = super().update(instance, validated_data)

            # If owner changed or unit number/building changed, sync it
            self._sync_owner_user_unit(instance, old_owner_user, old_building_name, old_unit_number)

            tenant_data = {
                'tenant_user': tenant_user,
                'tenant_first_name': tenant_first_name,
                'tenant_last_name': tenant_last_name,
                'tenant_email': tenant_email,
                'tenant_phone': tenant_phone,
            }
            self._sync_tenant_user_unit(instance, tenant_data, old_tenant_user, old_building_name, old_unit_number)
            return instance

    def _sync_tenant_user_unit(self, instance, tenant_data, old_tenant_user=None, old_building_name='', old_unit_number=''):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        new_tenant_user = tenant_data.get('tenant_user')
        new_unit_number = instance.unit_number
        new_building_name = instance.building.name if instance.building else ''

        tenant_first_name = (tenant_data.get('tenant_first_name') or '').strip()
        tenant_last_name = (tenant_data.get('tenant_last_name') or '').strip()
        tenant_email = (tenant_data.get('tenant_email') or '').strip()
        tenant_phone = (tenant_data.get('tenant_phone') or '').strip()

        if tenant_phone and len([c for c in tenant_phone if c.isdigit()]) < 5:
            tenant_phone = ''

        # If no new_tenant_user was explicitly selected, but we are in tenant_occupied and have an old one
        if not new_tenant_user and instance.unit_type == 'tenant_occupied' and old_tenant_user:
            new_tenant_user = old_tenant_user

        # If unit is tenant occupied and no tenant_user is set/found, but details are entered, find or create
        if instance.unit_type == 'tenant_occupied' and not new_tenant_user and (tenant_email or tenant_phone or tenant_first_name or tenant_last_name):
            email_clean = tenant_email
            phone_clean = tenant_phone
            first_name = tenant_first_name
            last_name = tenant_last_name

            user = None
            if email_clean:
                user = User.objects.filter(email__iexact=email_clean).first()
            if not user and phone_clean:
                potential_users = User.objects.filter(phone=phone_clean)
                for u in potential_users:
                    u_first = (u.first_name or '').strip().lower()
                    u_last = (u.last_name or '').strip().lower()
                    new_first = first_name.strip().lower()
                    new_last = last_name.strip().lower()
                    
                    first_match = not u_first or not new_first or u_first == new_first
                    last_match = not u_last or not new_last or u_last == new_last
                    if first_match and last_match:
                        user = u
                        break

            if not user:
                # Create user
                if email_clean:
                    username = email_clean.split('@')[0]
                elif phone_clean:
                    username = f"tenant_{phone_clean}"
                else:
                    username = f"tenant_{first_name.lower()}_{last_name.lower()}"

                username = ''.join(c for c in username if c.isalnum() or c in ['_', '-'])
                if not username:
                    username = "tenant_user"

                base_username = username
                counter = 1
                while User.objects.filter(username__iexact=username).exists():
                    username = f"{base_username}_{counter}"
                    counter += 1

                request = self.context.get('request')
                tenant_id = getattr(request.user, 'tenant_id', None) if request and request.user else None
                # master_admin lives in public schema (tenant_id=None/'public').
                # Use the active DB connection schema for the new user.
                if not tenant_id or tenant_id == 'public':
                    from django.db import connection as _conn
                    schema = getattr(_conn, 'schema_name', None)
                    if schema and schema != 'public':
                        tenant_id = schema

                user = User.objects.create_user(
                    username=username,
                    email=email_clean,
                    first_name=first_name,
                    last_name=last_name,
                    phone=phone_clean,
                    role='tenant',
                    is_approved=True,
                    is_active=True,
                    tenant_id=tenant_id
                )

            if user.role != 'tenant':
                user.role = 'tenant'
                user.save(update_fields=['role'])

            new_tenant_user = user

        # 1. If unit is no longer tenant occupied, or if tenant has changed, vacate the old tenant
        if instance.unit_type != 'tenant_occupied' or (old_tenant_user and old_tenant_user != new_tenant_user):
            if old_tenant_user:
                old_tenant_user.unit_number = ''
                old_tenant_user.building_name = ''
                old_tenant_user.save(update_fields=['unit_number', 'building_name'])

        # 2. If there is a new tenant, update their unit info and details
        if new_tenant_user:
            if instance.unit_type == 'tenant_occupied':
                updated_fields = ['unit_number', 'building_name']
                new_tenant_user.unit_number = new_unit_number
                new_tenant_user.building_name = new_building_name

                if tenant_first_name is not None and tenant_first_name.strip() and new_tenant_user.first_name != tenant_first_name.strip():
                    new_tenant_user.first_name = tenant_first_name.strip()
                    updated_fields.append('first_name')
                if tenant_last_name is not None and tenant_last_name.strip() and new_tenant_user.last_name != tenant_last_name.strip():
                    new_tenant_user.last_name = tenant_last_name.strip()
                    updated_fields.append('last_name')
                if tenant_email is not None and tenant_email.strip() and new_tenant_user.email != tenant_email.strip():
                    new_tenant_user.email = tenant_email.strip()
                    updated_fields.append('email')
                if tenant_phone is not None and tenant_phone.strip() and new_tenant_user.phone != tenant_phone.strip():
                    new_tenant_user.phone = tenant_phone.strip()
                    updated_fields.append('phone')

                new_tenant_user.save(update_fields=updated_fields)
                
                # Update current_resident on Unit
                instance.current_resident = new_tenant_user.get_full_name() or new_tenant_user.email or new_tenant_user.username
                instance.save(update_fields=['current_resident'])
            else:
                # If unit is no longer tenant occupied, clear it on user
                if new_tenant_user.unit_number == new_unit_number and new_tenant_user.building_name == new_building_name:
                    new_tenant_user.unit_number = ''
                    new_tenant_user.building_name = ''
                    new_tenant_user.save(update_fields=['unit_number', 'building_name'])

    def _sync_owner_user_unit(self, instance, old_owner_user=None, old_building_name='', old_unit_number=''):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        new_owner_user = instance.owner_user
        new_unit_number = instance.unit_number
        new_building_name = instance.building.name if instance.building else ''

        owner_first_name = (instance.owner_first_name or '').strip()
        owner_last_name = (instance.owner_last_name or '').strip()
        owner_email = (instance.owner_email or '').strip()
        owner_phone = (instance.owner_phone or '').strip()

        if owner_phone and len([c for c in owner_phone if c.isdigit()]) < 5:
            owner_phone = ''

        # If no owner_user is linked, but owner details are filled directly, find or create the user account
        if not new_owner_user and (owner_email or owner_phone or owner_first_name or owner_last_name):
            email_clean = owner_email
            phone_clean = owner_phone
            first_name = owner_first_name
            last_name = owner_last_name
            
            user = None
            if email_clean:
                user = User.objects.filter(email__iexact=email_clean).first()
            if not user and phone_clean:
                # Match phone but ensure name is compatible (not a completely different person)
                potential_users = User.objects.filter(phone=phone_clean)
                for u in potential_users:
                    u_first = (u.first_name or '').strip().lower()
                    u_last = (u.last_name or '').strip().lower()
                    new_first = first_name.strip().lower()
                    new_last = last_name.strip().lower()
                    
                    first_match = not u_first or not new_first or u_first == new_first
                    last_match = not u_last or not new_last or u_last == new_last
                    if first_match and last_match:
                        user = u
                        break
                
            if not user:
                if email_clean:
                    username = email_clean.split('@')[0]
                elif phone_clean:
                    username = f"owner_{phone_clean}"
                else:
                    username = f"owner_{first_name.lower()}_{last_name.lower()}"
                
                username = ''.join(c for c in username if c.isalnum() or c in ['_', '-'])
                if not username:
                    username = "owner_user"
                    
                base_username = username
                counter = 1
                while User.objects.filter(username__iexact=username).exists():
                    username = f"{base_username}_{counter}"
                    counter += 1
                
                request = self.context.get('request')
                tenant_id = getattr(request.user, 'tenant_id', None) if request and request.user else None
                # master_admin lives in public schema (tenant_id=None/'public').
                # Use the active DB connection schema for the new user.
                if not tenant_id or tenant_id == 'public':
                    from django.db import connection as _conn
                    schema = getattr(_conn, 'schema_name', None)
                    if schema and schema != 'public':
                        tenant_id = schema
                
                user = User.objects.create_user(
                    username=username,
                    email=email_clean,
                    first_name=first_name,
                    last_name=last_name,
                    phone=phone_clean,
                    role='owner',
                    is_approved=True,
                    is_active=True,
                    tenant_id=tenant_id
                )
            
            if user.role != 'owner':
                user.role = 'owner'
                user.save(update_fields=['role'])
                
            instance.owner_user = user
            instance.save(update_fields=['owner_user'])
            new_owner_user = user

        # 1. If there was an old owner, and they are no longer the owner (or the unit changed)
        if old_owner_user and (old_owner_user != new_owner_user or old_building_name != new_building_name or old_unit_number != new_unit_number):
            # Only clear if it still points to this unit
            if old_owner_user.unit_number == old_unit_number and old_owner_user.building_name == old_building_name:
                old_owner_user.unit_number = ''
                old_owner_user.building_name = ''
                old_owner_user.save(update_fields=['unit_number', 'building_name'])

        # 2. If there is a new owner, update their unit info
        if new_owner_user:
            new_owner_user.unit_number = new_unit_number
            new_owner_user.building_name = new_building_name
            new_owner_user.save(update_fields=['unit_number', 'building_name'])


class UnitBulkUpdateSerializer(serializers.Serializer):
    unit_ids = serializers.ListField(child=serializers.UUIDField())
    status = serializers.ChoiceField(choices=Unit.STATUS_CHOICES, required=False)
    monthly_rent = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    maintenance_charge = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)


# =========================
# LEASE SERIALIZERS
# =========================

class LeaseSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source='tenant.get_full_name', read_only=True)
    tenant_email = serializers.CharField(source='tenant.email', read_only=True)
    tenant_phone = serializers.CharField(source='tenant.phone', read_only=True)
    unit_number = serializers.CharField(source='unit.unit_number', read_only=True)
    building_name = serializers.CharField(source='unit.building.name', read_only=True)
    building_id = serializers.UUIDField(source='unit.building.id', read_only=True)
    block = serializers.CharField(source='unit.block', read_only=True)
    days_remaining = serializers.SerializerMethodField()
    is_late_fee_applicable = serializers.SerializerMethodField()
    
    # 🔧 ADD THIS: Include lease documents
    documents = serializers.SerializerMethodField()
    agreement_document_url = serializers.SerializerMethodField()
    monthlyRent = serializers.DecimalField(source='monthly_rent', max_digits=10, decimal_places=2, read_only=True)
    rent_amount = serializers.DecimalField(source='monthly_rent', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Lease
        fields = '__all__'

    def get_days_remaining(self, obj):
        from django.utils import timezone
        if obj.status == 'active':
            today = timezone.now().date()
            if obj.end_date > today:
                return (obj.end_date - today).days
        return 0

    def get_is_late_fee_applicable(self, obj):
        from django.utils import timezone
        if obj.late_fee_applicable_date:
            return timezone.now().date() >= obj.late_fee_applicable_date
        return False
    
    # 🔧 ADD THIS METHOD
    def get_documents(self, obj):
        from .models import PropertyDocument
        docs = PropertyDocument.objects.filter(lease=obj).select_related('uploaded_by')
        return [{
            'id': str(doc.id),
            'title': doc.title,
            'document_type': doc.document_type,
            'file': doc.file.url if doc.file else None,
            'uploaded_at': doc.uploaded_at,
            'uploaded_by': doc.uploaded_by.get_full_name() if doc.uploaded_by else None,
        } for doc in docs]
    
    # 🔧 ADD THIS METHOD
    def get_agreement_document_url(self, obj):
        if obj.agreement_document:
            return obj.agreement_document.url
        return None


class LeaseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lease
        exclude = ('agreement_document',)

    def validate(self, data):
        print(f"DEBUG: Receiving Lease Data: {data}")
        unit = data.get('unit', getattr(self.instance, 'unit', None))
        start_date = data.get('start_date', getattr(self.instance, 'start_date', None))
        end_date = data.get('end_date', getattr(self.instance, 'end_date', None))
        monthly_rent = data.get('monthly_rent', getattr(self.instance, 'monthly_rent', None))

        if monthly_rent is not None and monthly_rent <= 0:
            raise serializers.ValidationError({"monthly_rent": "Monthly rent must be greater than 0."})

        if start_date and end_date and start_date >= end_date:
            raise serializers.ValidationError("End date must be after start date")

        overlapping_leases = Lease.objects.filter(
            unit=unit,
            status='active'
        ).exclude(id=self.instance.id if self.instance else None)

        if overlapping_leases.exists():
            raise serializers.ValidationError("Unit already has an active lease")

        return data


# =========================
# PROPERTY DOCUMENT SERIALIZERS
# =========================

class PropertyDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True)
    building_name = serializers.CharField(source='building.name', read_only=True, allow_null=True)
    unit_number = serializers.CharField(source='unit.unit_number', read_only=True, allow_null=True)
    file_size = serializers.SerializerMethodField()

    class Meta:
        model = PropertyDocument
        fields = '__all__'

    def get_file_size(self, obj):
        try:
            if obj.file and hasattr(obj.file, 'size'):
                return obj.file.size
        except Exception:
            pass
        return 0


class PropertyDocumentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyDocument
        fields = '__all__'
    
    def validate_title(self, value):
        """Ensure title is not empty"""
        if not value or not value.strip():
            raise serializers.ValidationError("Document title cannot be empty.")
        return value.strip()
    
    def validate_document_type(self, value):
        """Ensure document type is valid"""
        valid_types = dict(PropertyDocument.DOCUMENT_TYPE_CHOICES).keys()
        if value not in valid_types:
            raise serializers.ValidationError(f"Invalid document type. Valid options: {', '.join(valid_types)}")
        return value



# =========================
# DASHBOARD / STATS SERIALIZERS
# =========================

class BuildingStatsSerializer(serializers.Serializer):
    total_buildings = serializers.IntegerField()
    total_units = serializers.IntegerField()
    occupied_units = serializers.IntegerField()
    available_units = serializers.IntegerField()
    maintenance_units = serializers.IntegerField()
    occupancy_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    total_monthly_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


class UnitAvailabilitySerializer(serializers.Serializer):
    building_id = serializers.UUIDField()
    building_name = serializers.CharField()
    total_units = serializers.IntegerField()
    available_units = serializers.IntegerField()
    occupied_units = serializers.IntegerField()
    maintenance_units = serializers.IntegerField()
    reserved_units = serializers.IntegerField()


# =========================
# HIERARCHY SERIALIZERS
# =========================

class PropertyCitySerializer(serializers.ModelSerializer):
    area_count = serializers.SerializerMethodField()
    township_count = serializers.SerializerMethodField()

    class Meta:
        model = PropertyCity
        fields = ['id', 'name', 'state', 'description', 'is_active', 'area_count', 'township_count', 'created_at']

    def get_area_count(self, obj):
        return obj.area_zones.count()

    def get_township_count(self, obj):
        return obj.townships.count()


class PropertyCityCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyCity
        fields = '__all__'


class AreaZoneSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(source='city_ref.name', read_only=True)
    state = serializers.CharField(source='city_ref.state', read_only=True)
    township_count = serializers.SerializerMethodField()

    class Meta:
        model = AreaZone
        fields = ['id', 'name', 'description', 'is_active', 'city_ref', 'city_name', 'state', 'township_count', 'created_at']

    def get_township_count(self, obj):
        return obj.townships.count()


class AreaZoneCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AreaZone
        fields = '__all__'

class TownshipSerializer(serializers.ModelSerializer):
    building_count = serializers.SerializerMethodField()
    city_ref_name = serializers.CharField(source='city_ref.name', read_only=True)
    area_zone_name = serializers.CharField(source='area_zone.name', read_only=True)
    state_name = serializers.SerializerMethodField()
    managed_by_name = serializers.SerializerMethodField()
    complete_address = serializers.SerializerMethodField()

    class Meta:
        model = Township
        fields = [
            'id', 'name', 'address', 'address_line1', 'address_line2', 'address_line3', 'landmark',
            'city', 'district', 'state', 'postal_code', 'country', 'managed_by', 'managed_by_name', 'description',
            'city_ref', 'city_ref_name', 'area_zone', 'area_zone_name', 'state_name',
            'complete_address', 'building_count', 'is_active', 'created_at'
        ]

    def get_building_count(self, obj):
        return obj.buildings.count()

    def get_state_name(self, obj):
        if obj.city_ref and obj.city_ref.state:
            return obj.city_ref.state
        return obj.state

    def get_managed_by_name(self, obj):
        if obj.managed_by:
            name = obj.managed_by.get_full_name()
            return name if name.strip() else obj.managed_by.username
        return None

    def get_complete_address(self, obj):
        return obj.complete_address or obj.address


class TownshipCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Township
        fields = '__all__'

    def create(self, validated_data):
        request = self.context.get('request')
        manager = validated_data.get('managed_by')
        instance = super().create(validated_data)
        _sync_fm_assignment_for_scope(
            instance=instance,
            scope_type='township',
            manager=manager,
            request_user=getattr(request, 'user', None),
        )
        return instance

    def update(self, instance, validated_data):
        request = self.context.get('request')
        manager = validated_data.get('managed_by', instance.managed_by)
        instance = super().update(instance, validated_data)
        _sync_fm_assignment_for_scope(
            instance=instance,
            scope_type='township',
            manager=manager,
            request_user=getattr(request, 'user', None),
        )
        return instance


class BlockSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source='building.name', read_only=True)
    floor_count = serializers.SerializerMethodField()

    class Meta:
        model = Block
        fields = [
            'id', 'name', 'building', 'building_name', 'description', 'floor_count', 
            'building_type', 'year_built', 'total_floors', 'apartments_per_floor', 'total_units',
            'property_area', 'business_name', 'business_registration_number',
            'address_line1', 'address_line2', 'address_line3', 'landmark',
            'created_at'
        ]

    def get_floor_count(self, obj):
        return obj.floors.count()


class BlockCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = '__all__'


class FloorSerializer(serializers.ModelSerializer):
    block_name = serializers.CharField(source='block.name', read_only=True)
    building_name = serializers.CharField(source='block.building.name', read_only=True)
    apartment_count = serializers.SerializerMethodField()
    occupied_count = serializers.SerializerMethodField()
    available_count = serializers.SerializerMethodField()

    class Meta:
        model = Floor
        fields = [
            'id', 'floor_number', 'label', 'block', 'block_name', 'building_name',
            'apartment_count', 'occupied_count', 'available_count', 'created_at'
        ]

    def get_apartment_count(self, obj):
        return obj.apartments.count()

    def get_occupied_count(self, obj):
        return obj.apartments.filter(status='occupied').count()

    def get_available_count(self, obj):
        return obj.apartments.filter(status='available').count()


class FloorCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Floor
        fields = '__all__'


class ApartmentSummarySerializer(serializers.ModelSerializer):
    """Lightweight serializer for apartment listings within a floor."""
    building_name = serializers.CharField(source='building.name', read_only=True)
    current_tenant = serializers.SerializerMethodField()
    active_lease = serializers.SerializerMethodField()

    class Meta:
        model = Unit
        fields = [
            'id', 'unit_number', 'block', 'floor', 'unit_type', 'status',
            'unit_category', 'property_area', 'business_name', 'business_registration_number',
            'bedrooms', 'bathrooms', 'square_feet', 'monthly_rent',
            'owner_first_name', 'owner_last_name', 'owner_email', 'owner_phone',
            'current_resident', 'building_name', 'building', 'current_tenant', 'active_lease',
        ]

    def get_current_tenant(self, obj):
        # 1. Try active lease first
        lease = obj.leases.filter(status='active').first()
        if not lease:
            # 2. Try any lease linked to this unit (pending/etc.)
            lease = obj.leases.first()
            
        if lease:
            return {
                'id': str(lease.tenant.id),
                'first_name': lease.tenant.first_name,
                'last_name': lease.tenant.last_name,
                'name': lease.tenant.get_full_name(),
                'email': lease.tenant.email,
                'phone': getattr(lease.tenant, 'phone', None),
            }
        
        # 3. Fallback: find by explicit unit_number and building_name on User model
        from django.contrib.auth import get_user_model
        User = get_user_model()
        building_name_str = obj.building.name.strip() if obj.building else ''
        unit_number_str = obj.unit_number.strip() if obj.unit_number else ''
        
        if not unit_number_str:
            return None
            
        tenant = User.objects.filter(
            role='tenant',
            unit_number__iexact=unit_number_str
        ).filter(
            Q(building_name__iexact=building_name_str) | Q(building_name='') | Q(building_name__isnull=True)
        ).first()
        
        if tenant:
            return {
                'id': str(tenant.id),
                'first_name': tenant.first_name,
                'last_name': tenant.last_name,
                'name': tenant.get_full_name(),
                'email': tenant.email,
                'phone': getattr(tenant, 'phone', None),
            }
        return None

    def get_active_lease(self, obj):
        lease = obj.leases.filter(status='active').first()
        if lease:
            return {
                'id': str(lease.id),
                'start_date': lease.start_date,
                'end_date': lease.end_date,
                'monthly_rent': str(lease.monthly_rent),
            }
        return None


class FloorDetailSerializer(serializers.ModelSerializer):
    """Full floor detail with all apartments and their tenant/owner info."""
    block_name = serializers.CharField(source='block.name', read_only=True)
    building_name = serializers.CharField(source='block.building.name', read_only=True)
    apartments = serializers.SerializerMethodField()
    total_apartments = serializers.SerializerMethodField()
    occupied_count = serializers.SerializerMethodField()
    available_count = serializers.SerializerMethodField()

    class Meta:
        model = Floor
        fields = [
            'id', 'floor_number', 'label', 'block', 'block_name', 'building_name',
            'total_apartments', 'occupied_count', 'available_count', 'apartments',
        ]

    def get_apartments(self, obj):
        units = obj.apartments.select_related('building').prefetch_related('leases__tenant')
        return ApartmentSummarySerializer(units, many=True).data

    def get_total_apartments(self, obj):
        return obj.apartments.count()

    def get_occupied_count(self, obj):
        return obj.apartments.filter(status='occupied').count()

    def get_available_count(self, obj):
        return obj.apartments.filter(status='available').count()


# ======================================================
# FACILITY MANAGER ASSIGNMENT SERIALIZERS
# ======================================================

class FacilityManagerAssignmentSerializer(serializers.ModelSerializer):
    facility_manager_name = serializers.SerializerMethodField()
    assigned_by_name = serializers.SerializerMethodField()
    scope_label = serializers.SerializerMethodField()

    class Meta:
        model = FacilityManagerAssignment
        fields = [
            'id', 'facility_manager', 'facility_manager_name',
            'scope_type', 'scope_label',
            'township', 'building', 'block',
            'assigned_by', 'assigned_by_name',
            'assigned_at', 'is_active', 'notes',
        ]
        read_only_fields = ['assigned_by', 'assigned_at']

    def get_facility_manager_name(self, obj):
        return obj.facility_manager.get_full_name() or obj.facility_manager.username

    def get_assigned_by_name(self, obj):
        if obj.assigned_by:
            return obj.assigned_by.get_full_name() or obj.assigned_by.username
        return None

    def get_scope_label(self, obj):
        if obj.scope_type == 'township' and obj.township:
            return str(obj.township)
        if obj.scope_type == 'building' and obj.building:
            return str(obj.building)
        if obj.scope_type == 'block' and obj.block:
            return str(obj.block)
        return ''

    def validate(self, data):
        scope_type = data.get('scope_type') or getattr(self.instance, 'scope_type', None)
        if scope_type == 'township' and not data.get('township'):
            raise serializers.ValidationError({'township': 'Required for township scope.'})
        if scope_type == 'building' and not data.get('building'):
            raise serializers.ValidationError({'building': 'Required for building scope.'})
        if scope_type == 'block' and not data.get('block'):
            raise serializers.ValidationError({'block': 'Required for block scope.'})
        return data
