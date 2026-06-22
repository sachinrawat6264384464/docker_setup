# accounts/models.py - COMPLETE FILE WITH FIXES
from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
import secrets
import string
from django.utils import timezone
from datetime import timedelta
from django.db import connection

class User(AbstractUser):
    """
    Custom user model with additional fields for property management
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Role choices with hierarchy
    ROLE_CHOICES = [
        ('master_admin', 'Master Admin'),
        ('super_admin', 'Super Admin'),
        ('masteradmin', 'Master Admin'),
        ('superadmin', 'Super Admin'),
        ('super_admin_admin', 'Hub Administrator'),
        ('operations_manager', 'Operations Manager'),
        ('tech_support_lead', 'Tech Support Lead'),
        ('finance_billing_manager', 'Finance Manager'),
        ('sales_marketing_admin', 'Marketing Admin'),
        ('system_auditor', 'System Auditor'),
        ('platform_member', 'Platform Member'),
        ('facility_manager', 'Facility Manager'),
        ('property_staff', 'Property Staff'),
        ('owner', 'Owner'),
        ('tenant_vendor', 'Vendor'),
        ('tenant', 'Residents'),
        ('maintenance_staff', 'Maintenance Staff'),
        ('security_guard', 'Security Guard'),
    ]

    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='tenant')
    
    # Tenant association (multi-tenancy)
    tenant_id = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text="Associated tenant schema name"
    )
    
    # Personal information
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    
    # Property-related fields
    unit_number = models.CharField(max_length=50, blank=True, help_text="Apartment/unit number")
    building_name = models.CharField(max_length=200, blank=True, help_text="Building name")
    
    # Emergency contact
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    
    # OTP and security fields
    otp_code = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    otp_attempts = models.IntegerField(default=0)
    otp_blocked_until = models.DateTimeField(blank=True, null=True)
    
    # Email verification
    email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=100, blank=True, null=True)

    # Password reset token expiry
    password_reset_token_created_at = models.DateTimeField(blank=True, null=True)

    # Notification preferences
    notification_preferences = models.JSONField(
        default=dict,
        blank=True,
        help_text="User notification preferences (email, sms, push, in_app)"
    )

    # Granular permissions for this specific user
    permissions = models.JSONField(
        default=list,
        blank=True,
        help_text="Granular permissions assigned to this user"
    )

    # Status fields
    is_approved = models.BooleanField(default=True, help_text="Admin approval for tenant access")
    last_activity = models.DateTimeField(auto_now=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"

    def delete(self, *args, **kwargs):
        from django.db import connection
        from django.conf import settings

        if connection.schema_name == 'public':
            shared_app_labels = set()
            for app in settings.SHARED_APPS:
                parts = app.split('.')
                if 'apps' in parts:
                    shared_app_labels.add(parts[0])
                else:
                    shared_app_labels.add(parts[-1])

            opts = self._meta
            original_get_fields = opts.get_fields

            def patched_get_fields(include_parents=True, include_hidden=False):
                fields = original_get_fields(include_parents=include_parents, include_hidden=include_hidden)
                filtered = []
                for f in fields:
                    if f.auto_created and not f.concrete and (f.one_to_one or f.one_to_many):
                        if f.related_model and f.related_model._meta.app_label not in shared_app_labels:
                            continue
                    filtered.append(f)
                return filtered

            opts.get_fields = patched_get_fields
            try:
                return super().delete(*args, **kwargs)
            finally:
                opts.get_fields = original_get_fields
        else:
            return super().delete(*args, **kwargs)
    
    # Role checking properties
    @property
    def is_master_admin(self):
        return self.role in ('master_admin', 'masteradmin')

    @property
    def is_tenant_admin(self):
        return self.role in ('master_admin', 'masteradmin')

    @property
    def is_super_admin(self):
        return self.role in ('super_admin', 'superadmin')

    @property
    def is_platform_member(self):
        return self.role == 'platform_member'
    
    @property
    def is_system_admin(self):
        return (
        connection.schema_name == "public"
        and self.role in ("super_admin", "superadmin")
        and self.is_superuser
    )
    
    @property
    def is_facility_manager(self):
        return self.role == 'facility_manager'

    @property
    def managed_blocks(self):
        """Resolve facility manager block access from tenant-side assignments."""
        try:
            from properties.models import Block

            if not self.is_facility_manager:
                return Block.objects.none()

            if getattr(connection, 'schema_name', 'public') == 'public':
                return Block.objects.none()

            return Block.objects.filter(
                fm_assignments__facility_manager=self,
                fm_assignments__is_active=True,
            ).distinct()
        except Exception:
            class _EmptyBlocks:
                def values_list(self, *args, **kwargs):
                    return []

            return _EmptyBlocks()
    
    @property
    def is_property_staff(self):
        return self.role == 'property_staff'
    
    @property
    def is_tenant(self):
        return self.role == 'tenant'

    @property
    def is_tenant_vendor(self):
        return self.role == 'tenant_vendor'
    
    @property
    def is_maintenance_staff(self):
        return self.role == 'maintenance_staff'
    
    @property
    def is_security_guard(self):
        return self.role == 'security_guard'
    
    @property
    def can_manage_tenants(self):
        """Check if user can manage other tenants"""
        return self.is_tenant_admin or self.is_system_admin
    
    @property
    def can_manage_property(self):
        """Check if user can manage property data"""
        return self.role in ['master_admin', 'masteradmin', 'super_admin', 'superadmin', 'facility_manager', 'property_staff']
    
    @property
    def can_assign_roles(self):
        """Check if user can assign roles to others"""
        return (
        self.is_system_admin
        or self.is_tenant_admin
        or self.is_facility_manager
    )
    
    def can_assign_role(self, target_role):
        """Check if user can assign a specific role"""
        # Keep assignment checks in sync with centralized RBAC constants.
        from .permissions import ROLE_MANAGEMENT_HIERARCHY
        allowed_roles = ROLE_MANAGEMENT_HIERARCHY.get(self.role, [])
        return target_role in allowed_roles
    
    def generate_otp(self):
        """Generate OTP for email/SMS verification"""
        self.otp_code = ''.join(secrets.choice(string.digits) for _ in range(6))
        self.otp_created_at = timezone.now()
        self.otp_attempts = 0
        self.save(update_fields=['otp_code', 'otp_created_at', 'otp_attempts'])
        return self.otp_code
    
    def verify_otp(self, otp_code):
        """Verify OTP code"""
        # Check if user is blocked
        if self.otp_blocked_until and self.otp_blocked_until > timezone.now():
            return False, "OTP verification blocked. Please try again later."
        
        # Check if OTP exists and is not expired
        if not self.otp_code or not self.otp_created_at:
            return False, "No OTP found. Please request a new one."
        
        # Check expiry (5 minutes)
        if self.otp_created_at + timedelta(minutes=5) < timezone.now():
            return False, "OTP has expired. Please request a new one."
        
        # Check OTP code
        if self.otp_code == otp_code:
            self.otp_code = None
            self.otp_created_at = None
            self.otp_attempts = 0
            self.email_verified = True
            self.save(update_fields=['otp_code', 'otp_created_at', 'otp_attempts', 'email_verified'])
            return True, "OTP verified successfully."
        else:
            self.otp_attempts += 1
            if self.otp_attempts >= 3:
                self.otp_blocked_until = timezone.now() + timedelta(minutes=15)
                self.save(update_fields=['otp_attempts', 'otp_blocked_until'])
                return False, "Too many failed attempts. OTP verification blocked for 15 minutes."
            else:
                self.save(update_fields=['otp_attempts'])
                return False, f"Invalid OTP. {3 - self.otp_attempts} attempts remaining."
    
    def generate_email_verification_token(self):
        """Generate email verification token"""
        self.email_verification_token = secrets.token_urlsafe(32)
        self.save(update_fields=['email_verification_token'])
        return self.email_verification_token


class UserProfile(models.Model):
    """
    Extended profile information for users
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # Additional personal info
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(
        max_length=20,
        choices=[
            ('male', 'Male'),
            ('female', 'Female'),
            ('other', 'Other'),
            ('prefer_not_to_say', 'Prefer not to say'),
        ],
        blank=True
    )
    occupation = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True)
    
    # Address information
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True, default='India')
    
    # Lease information (for tenants)
    lease_start_date = models.DateField(blank=True, null=True)
    lease_end_date = models.DateField(blank=True, null=True)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    security_deposit = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    # Family/household information
    household_size = models.IntegerField(default=1)
    has_pets = models.BooleanField(default=False)
    pet_details = models.TextField(blank=True, help_text="Pet information")
    
    # Vehicle information
    vehicle_count = models.IntegerField(default=0)
    vehicle_details = models.JSONField(default=list, blank=True, help_text="Vehicle information")
    
    # Emergency information
    medical_conditions = models.TextField(blank=True)
    insurance_provider = models.CharField(max_length=200, blank=True)
    insurance_policy_number = models.CharField(max_length=100, blank=True)
    is_senior = models.BooleanField(default=False, help_text="Mark if the resident is a senior citizen for priority care")
    
    # Work information (for staff)
    employee_id = models.CharField(max_length=50, blank=True)
    department = models.CharField(max_length=100, blank=True)
    supervisor = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='supervised_users'
    )
    
    # Working hours for staff/managers
    working_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text="Working hours schedule for staff and managers"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Profile for {self.user.get_full_name()}"


class Role(models.Model):
    """
    Role management with permissions
    """
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=200)
    description = models.TextField()
    
    # Role level (hierarchy)
    level = models.IntegerField(
        help_text="Higher number = higher authority (1=lowest, 10=highest)"
    )
    
    # Permissions
    permissions = models.JSONField(
        default=list, 
        blank=True,
        help_text="List of permission codes"
    )
    
    # Scope
    is_system_role = models.BooleanField(
        default=False, 
        help_text="System-wide role vs tenant-specific role"
    )
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-level', 'name']

    def __str__(self):
        return self.display_name

    def has_permission(self, permission_code):
        """Check if this role includes a specific permission code."""
        return permission_code in (self.permissions or [])

    def add_permission(self, permission_code):
        """Add a permission code to this role."""
        if self.permissions is None:
            self.permissions = []
        if permission_code not in self.permissions:
            self.permissions.append(permission_code)

    def remove_permission(self, permission_code):
        """Remove a permission code from this role."""
        if self.permissions and permission_code in self.permissions:
            self.permissions.remove(permission_code)

    def set_permissions(self, permission_codes):
        """Replace all permissions with the given list."""
        self.permissions = list(set(permission_codes))


class Permission(models.Model):
    """
    Individual permissions that can be assigned to roles
    """
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField()
    
    module = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="Module this permission belongs to (e.g., users, properties, payments)"
    )

    category = models.CharField(
        max_length=50,
        choices=[
            ('system', 'System Management'),
            ('tenant', 'Tenant Management'),
            ('user', 'User Management'),
            ('property', 'Property Management'),
            ('maintenance', 'Maintenance'),
            ('payment', 'Payments'),
            ('report', 'Reports & Analytics'),
            ('amenity', 'Amenities'),
            ('visitor', 'Visitors'),
            ('parking', 'Parking'),
            ('communication', 'Communication'),
            ('notification', 'Notifications'),
            ('security', 'Security'),
            ('utility', 'Utilities'),
            ('calendar', 'Calendar & Events'),
            ('vendor', 'Vendors'),
            ('entertainment', 'Entertainment'),
            ('support', 'Support'),
            ('settings', 'Settings'),
        ]
    )
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['category', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.code})"


class UserRole(models.Model):
    """
    User role assignments with context
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='role_assignments')
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    
    # Assignment context
    assigned_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='assigned_roles'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    
    # Validity
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    class Meta:
        unique_together = ['user', 'role']
    
    def __str__(self):
        return f"{self.user.username} - {self.role.name}"
    
    @property
    def is_valid(self):
        """Check if role assignment is currently valid"""
        now = timezone.now()
        return (
            self.is_active and 
            self.valid_from <= now and 
            (self.valid_until is None or self.valid_until > now)
        )


class ActivityLog(models.Model):
    """
    Log user activities across the system
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    action = models.CharField(max_length=100)
    description = models.TextField()
    
    # Request context
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    
    # Additional context
    tenant_schema = models.CharField(max_length=100, blank=True)
    affected_user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='activities_about'
    )
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
            models.Index(fields=['tenant_schema', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.action}"