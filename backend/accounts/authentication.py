# accounts/authentication.py
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.settings import api_settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils.translation import gettext_lazy as _

User = get_user_model()

class MultiTenantJWTAuthentication(JWTAuthentication):
    user_id_field = api_settings.USER_ID_FIELD
    user_id_claim = api_settings.USER_ID_CLAIM

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
        else:
            raw_token = request.COOKIES.get('access_token')

        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)

        # VAPT-2026-035: Check if the access token has been blacklisted upon logout
        jti = validated_token.get('jti')
        if jti:
            from django.core.cache import cache
            if cache.get(f"blacklist_access_{jti}"):
                raise AuthenticationFailed(_('Token has been invalidated (logged out).'), code='token_blacklisted')

        return self.get_user(validated_token), validated_token

    def get_user(self, validated_token):
        """
        Attempts to find and return a user using the given validated token.
        Enforces strict multi-tenant boundary isolation.
        """
        try:
            user_id = validated_token[self.user_id_claim]
        except KeyError:
            raise AuthenticationFailed(_('Token contained no recognizable user identification'))
            
        try:
            user = User.objects.get(**{self.user_id_field: user_id})
        except User.DoesNotExist:
            raise AuthenticationFailed(_('User not found'), code='user_not_found')

        if not user.is_active:
            raise AuthenticationFailed(_('User is inactive'), code='user_inactive')

        current_schema = getattr(connection, 'schema_name', 'public')
        
        # Define roles that have platform-wide access across all schemas
        global_system_roles = (
            'super_admin', 'superadmin', 'super_admin_admin', 
            'operations_manager', 'tech_support_lead', 
            'finance_billing_manager', 'sales_marketing_admin', 
            'system_auditor'
        )

        # Enforce multi-tenant boundary validation
        if current_schema != 'public':
            if user.role not in global_system_roles:
                # Heal tenant_id if missing/blank/public
                tenant_val = getattr(user, 'tenant_id', None)
                if not tenant_val or tenant_val == 'public':
                    user.tenant_id = current_schema
                    user.save(update_fields=['tenant_id'])

                # 1. Check if user's registered tenant matches current schema
                if getattr(user, 'tenant_id', None) != current_schema:
                    raise AuthenticationFailed(
                        _('Tenant isolation violation: You do not have access to this organization.'),
                        code='tenant_violation'
                    )
                
                # 2. Check if the token was specifically issued for this schema context
                token_tenant = validated_token.get('tenant')
                if token_tenant and token_tenant != current_schema:
                    raise AuthenticationFailed(
                        _('Token tenant mismatch: This session token is not valid for this organization.'),
                        code='tenant_mismatch'
                    )
        else:
            # Public schema context: only global system roles or public users are allowed
            if user.role not in global_system_roles and getattr(user, 'tenant_id', None) != 'public':
                raise AuthenticationFailed(
                    _('Access denied: Tenant users are not allowed to access the system hub.'),
                    code='public_access_denied'
                )

        return user

