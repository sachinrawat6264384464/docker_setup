# accounts/people_hub_views.py - COMPLETE FILE WITH ALL FIXES
from rest_framework import status, permissions, filters, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Q, Count, Exists, OuterRef, Sum, Case, When, IntegerField
from django.utils import timezone
from datetime import timedelta
from django_filters.rest_framework import DjangoFilterBackend
import logging
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from notifications.services import NotificationService

from .people_hub_serializers import (
    ResidentListSerializer, ResidentDetailSerializer,
    ResidentCreateSerializer, ResidentUpdateSerializer,
    BulkResidentActionSerializer, ResidentStatsSerializer
)
from .models import ActivityLog, UserProfile

User = get_user_model()
logger = logging.getLogger(__name__)


def _get_tenant_scope_id(user):
    tenant_id = getattr(user, 'tenant_id', None)
    if tenant_id:
        return tenant_id
    return getattr(connection, 'schema_name', None)


def _get_manager_building_names(user):
    if not user or getattr(user, 'role', None) != 'facility_manager':
        return None
    try:
        from properties.models import Building
        names = Building.objects.filter(
            Q(managed_by=user) | Q(township__managed_by=user)
        ).values_list('name', flat=True)
        return [name for name in names if name]
    except Exception:
        return []


def _get_manager_block_ids(user):
    if not user or getattr(user, 'role', None) != 'facility_manager':
        return None
    try:
        from accounts.fm_scope import get_fm_block_ids
        ids = get_fm_block_ids(user)
        return list(ids) if ids is not None else []
    except Exception:
        return []


def _get_manager_unit_pairs(user):
    if not user or getattr(user, 'role', None) != 'facility_manager':
        return None
    try:
        from accounts.fm_scope import get_fm_unit_pairs
        return list(get_fm_unit_pairs(user) or [])
    except Exception:
        return []


def _filter_residents_to_manager_blocks(queryset, user):
    """
    Filters residents based on FM scope (Direct Building management OR explicit unit assignments).
    """
    building_names = _get_manager_building_names(user)
    unit_pairs = _get_manager_unit_pairs(user)
    
    # If no scope at all, return empty
    if not building_names and not unit_pairs:
        return queryset.none()

    q_filter = Q()
    
    # 1. Include all residents in buildings managed directly
    if building_names:
        q_filter |= Q(building_name__in=building_names)
        # Also check via lease linkage
        q_filter |= Q(leases__unit__building__name__in=building_names)

    # 2. Include residents in specific assigned units
    if unit_pairs:
        for b_name, u_num in unit_pairs:
            if not b_name or not u_num:
                continue
            q_filter |= Q(building_name__iexact=b_name, unit_number__iexact=u_num)
            q_filter |= Q(leases__unit__building__name__iexact=b_name, leases__unit__unit_number__iexact=u_num)

    return queryset.filter(q_filter).distinct()


class IsPropertyManagerOrStaff(permissions.BasePermission):
    """Permission for property managers and staff"""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return hasattr(request.user, 'can_manage_property') and request.user.can_manage_property


class PeopleHubViewSet(viewsets.ModelViewSet):
    """
    Complete People Hub ViewSet for managing residents
    Handles: List, Create, Update, Delete, Bulk Actions
    """
    permission_classes = [IsPropertyManagerOrStaff]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['first_name', 'last_name', 'email', 'phone', 'username', 'unit_number']
    ordering_fields = ['first_name', 'last_name', 'email', 'created_at', 'last_activity']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get residents (owners + tenants) for current tenant with filters"""
        user = self.request.user
        tenant_scope_id = _get_tenant_scope_id(user)

        # Base queryset in current tenant schema
        if connection.schema_name == 'public':
            queryset = User.objects.filter(
                tenant_id=tenant_scope_id,
            ).select_related('profile')
        else:
            queryset = User.objects.all().select_related('profile')

        # Default to tenants and owners for list action unless role/resident_type is specified
        if self.action == 'list':
            resident_type = self.request.query_params.get('resident_type')
            role_param = self.request.query_params.get('role')
            if role_param:
                queryset = queryset.filter(role=role_param)
            elif resident_type == 'owner':
                queryset = queryset.filter(role='owner')
            elif resident_type == 'tenant':
                queryset = queryset.filter(role='tenant')
            else:
                queryset = queryset.filter(role__in=['tenant', 'owner'])
                
            from django.db.models import Prefetch
            from properties.models import Lease
            queryset = queryset.prefetch_related(
                Prefetch('leases', queryset=Lease.objects.filter(status='active'), to_attr='prefetched_active_leases')
            )

        # No filtering for Facility Managers - let them see all residents in the organization as requested
        # if getattr(user, 'role', None) == 'facility_manager':
        #     queryset = _filter_residents_to_manager_blocks(queryset, user)

        # Apply filters from query params
        building = self.request.query_params.get('building')
        if building:
            queryset = queryset.filter(building_name__icontains=building)

        unit_number = self.request.query_params.get('unit_number')
        if unit_number:
            queryset = queryset.filter(unit_number__icontains=unit_number)

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        is_approved = self.request.query_params.get('is_approved')
        if is_approved is not None:
            queryset = queryset.filter(is_approved=is_approved.lower() == 'true')

        email_verified = self.request.query_params.get('email_verified')
        if email_verified is not None:
            queryset = queryset.filter(email_verified=email_verified.lower() == 'true')

        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'list':
            return ResidentListSerializer
        elif self.action == 'create':
            return ResidentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ResidentUpdateSerializer
        return ResidentDetailSerializer
    
    def create(self, request, *args, **kwargs):
        """Override create to support validate_only mode for pre-flight duplicate checks."""
        # ── DEBUG LOGGING ──────────────────────────────────────────────────────
        safe_data = {k: v for k, v in request.data.items() if k != 'password'}
        logger.info(f"🔴 RESIDENT CREATE REQUEST | validate_only={request.data.get('validate_only')} | data={safe_data}")
        # ───────────────────────────────────────────────────────────────────────

        validate_only = str(request.data.get('validate_only', '')).lower() in ('true', '1', 'yes')
        if validate_only:
            # Strip non-serializer fields before validation
            data = {k: v for k, v in request.data.items() if k not in ('validate_only', 'unit_id', 'is_active', 'is_approved', 'is_owner')}
            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                logger.info(f"✅ VALIDATE ONLY PASSED for email={data.get('email')}")
                return Response({'valid': True, 'message': 'Validation passed'}, status=status.HTTP_200_OK)
            logger.error(f"🔴 VALIDATE ONLY ERRORS | email={data.get('email')} | errors={serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Actual create — log errors if serializer fails
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            logger.error(f"🔴 ACTUAL CREATE ERRORS | email={request.data.get('email')} | errors={serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Create resident and log activity"""
        try:
            resident = serializer.save()
            
            # Create profile if it doesn't exist (safe against concurrent creation/signals)
            UserProfile.objects.get_or_create(user=resident)
            
            # Log activity
            try:
                ActivityLog.objects.create(
                    user=self.request.user,
                    action='resident_created',
                    description=f'Created resident: {resident.get_full_name()}',
                    affected_user=resident,
                    metadata={
                        'resident_id': str(resident.id),
                        'email': resident.email
                    }
                )
            except Exception as log_error:
                logger.warning(f"Could not log activity: {str(log_error)}")
            
            # Automatically send welcome email upon creation
            try:
                from .email_service import EmailService
                raw_pwd = getattr(resident, '_raw_password', self.request.data.get('password'))
                EmailService.send_welcome_email(resident, raw_password=raw_pwd)
                logger.info(f"Auto-sent welcome email to {resident.email}")
            except Exception as email_error:
                logger.warning(f"Could not send welcome email to {resident.email}: {email_error}")

            logger.info(f"Resident created: {resident.email} by {self.request.user.email}")
            
        except Exception as e:
            logger.error(f"Error creating resident: {str(e)}")
            raise
    
    def perform_update(self, serializer):
        """Update resident and log activity"""
        try:
            resident = serializer.save()
            
            # Log activity
            try:
                ActivityLog.objects.create(
                    user=self.request.user,
                    action='resident_updated',
                    description=f'Updated resident: {resident.get_full_name()}',
                    affected_user=resident,
                    metadata={'resident_id': str(resident.id)}
                )
            except Exception as log_error:
                logger.warning(f"Could not log activity: {str(log_error)}")
            
            logger.info(f"Resident updated: {resident.email} by {self.request.user.email}")
            
        except Exception as e:
            logger.error(f"Error updating resident: {str(e)}")
            raise

    def _vacate_assigned_unit(self, resident):
        """Mark resident's assigned units as vacant/available before deleting resident."""
        try:
            from properties.models import Unit, Lease
        except Exception:
            logger.warning("Could not import properties models while vacating unit")
            return

        unit_ids = set()

        # 1. Units connected via any lease (active or not)
        leases = Lease.objects.filter(tenant=resident).select_related('unit')
        for lease in leases:
            if lease.unit_id:
                unit_ids.add(lease.unit_id)

        # 2. Units connected via building_name + unit_number mapping
        if resident.building_name and resident.unit_number:
            matching_units = Unit.objects.filter(
                building__name__iexact=resident.building_name.strip(),
                unit_number__iexact=resident.unit_number.strip(),
            )
            for u in matching_units:
                unit_ids.add(u.id)

        # 3. Units connected via current_resident matching name or email
        resident_identifiers = [
            resident.get_full_name(),
            resident.email,
            f"{resident.first_name} {resident.last_name}".strip(),
        ]
        for identifier in resident_identifiers:
            if not identifier or not identifier.strip():
                continue
            matching_res_units = Unit.objects.filter(current_resident__icontains=identifier.strip())
            for u in matching_res_units:
                unit_ids.add(u.id)

        if unit_ids:
            logger.info(f"Vacating {len(unit_ids)} unit(s) for resident {resident.email}")
            units = Unit.objects.filter(id__in=unit_ids)
            for unit in units:
                # If we're deleting an owner but the unit has an active tenant, DO NOT make it vacant!
                is_tenant_occupied = unit.unit_type == 'tenant_occupied' or unit.leases.filter(status='active').exists()
                
                if getattr(resident, 'role', None) == 'owner':
                    unit.owner_user = None
                    unit.owner_first_name = ''
                    unit.owner_last_name = ''
                    unit.owner_email = ''
                    unit.owner_phone = ''
                    unit.owner_address = ''
                    
                    if not is_tenant_occupied:
                        unit.status = 'available'
                        unit.is_occupied = False
                        unit.unit_type = 'vacant'
                        unit.current_resident = ''
                else:
                    # Deleting a tenant
                    unit.status = 'available'
                    unit.is_occupied = False
                    unit.unit_type = 'vacant'
                    unit.current_resident = ''
                    # If it has an owner, it reverts to owner_occupied
                    if unit.owner_user or unit.owner_email:
                        unit.status = 'occupied'
                        unit.is_occupied = True
                        unit.unit_type = 'owner_occupied'
                        unit.current_resident = unit.owner_first_name + ' ' + unit.owner_last_name if unit.owner_first_name else unit.owner_email

                unit.save()
    
    def destroy(self, request, *args, **kwargs):
        """
        Custom destroy with proper error handling and transaction management
        CRITICAL: Deletes ActivityLog FIRST to avoid foreign key constraint
        """
        from django.db import transaction, connection
        from django.db.utils import ProgrammingError
        
        try:
            instance = self.get_object()
            user_id = instance.id
            user_email = instance.email
            user_name = instance.get_full_name()
            
            logger.info(f"Attempting to delete resident: {user_email} (ID: {user_id})")
            
            # Try normal deletion with transaction
            try:
                with transaction.atomic():
                    self._vacate_assigned_unit(instance)
                    instance.delete()
                
                logger.info(f"Resident deleted successfully: {user_email}")
                
                return Response(
                    {
                        'success': True,
                        'message': f'Resident "{user_name}" deleted successfully'
                    },
                    status=status.HTTP_200_OK
                )
                
            except ProgrammingError as e:
                # Handle missing tables
                error_msg = str(e).lower()
                
                if 'does not exist' in error_msg:
                    logger.warning(f"Missing table during deletion: {str(e)}")
                    logger.warning("Attempting manual deletion...")
                    
                    # Manual deletion - DELETE IN CORRECT ORDER!
                    try:
                        with connection.cursor() as cursor:
                            # CRITICAL: Delete ActivityLog FIRST (foreign key constraint)
                            cursor.execute(
                                "DELETE FROM accounts_activitylog WHERE affected_user_id = %s",
                                [str(user_id)]
                            )
                            logger.info("Deleted ActivityLog (affected_user_id)")
                            
                            cursor.execute(
                                "DELETE FROM accounts_activitylog WHERE user_id = %s",
                                [str(user_id)]
                            )
                            logger.info("Deleted ActivityLog (user_id)")
                            
                            # Delete UserProfile
                            cursor.execute(
                                "DELETE FROM accounts_userprofile WHERE user_id = %s",
                                [str(user_id)]
                            )
                            logger.info("Deleted UserProfile")

                            # Try to vacate assigned unit before deleting user row
                            try:
                                self._vacate_assigned_unit(instance)
                            except Exception as vacate_error:
                                logger.warning(f"Failed to vacate unit during manual delete: {vacate_error}")
                            
                            # Finally delete User (no foreign keys blocking now)
                            cursor.execute(
                                "DELETE FROM accounts_user WHERE id = %s",
                                [str(user_id)]
                            )
                            logger.info("Deleted User")
                        
                        logger.info(f"Manual deletion successful for: {user_email}")
                        
                        return Response(
                            {
                                'success': True,
                                'message': f'Resident "{user_name}" deleted successfully'
                            },
                            status=status.HTTP_200_OK
                        )
                        
                    except Exception as manual_error:
                        logger.error(f"Manual deletion failed: {str(manual_error)}", exc_info=True)
                        raise
                else:
                    # Re-raise if not a missing table error
                    raise
                    
        except User.DoesNotExist:
            logger.error(f"Resident not found: {kwargs.get('pk')}")
            return Response(
                {
                    'success': False,
                    'error': 'Resident not found'
                },
                status=status.HTTP_404_NOT_FOUND
            )
            
        except Exception as e:
            logger.error(
                f"Error deleting resident: {str(e)}", 
                exc_info=True,
                extra={'resident_id': kwargs.get('pk'), 'user': request.user.email}
            )
            return Response(
                {
                    'success': False,
                    'error': 'Failed to delete resident',
                    'detail': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def bulk_action(self, request):
        """
        Perform bulk actions on multiple residents
        Actions: approve, disapprove, activate, deactivate, delete
        CRITICAL: Deletes ActivityLog FIRST for delete action
        """
        from django.db import transaction, connection
        from django.db.utils import ProgrammingError
        
        serializer = BulkResidentActionSerializer(
            data=request.data, 
            context={'request': request}
        )
        
        if not serializer.is_valid():
            return Response(
                serializer.errors, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        resident_ids = serializer.validated_data['resident_ids']
        action_type = serializer.validated_data['action']
        
        # Get residents/owners for current tenant only. Include owners so that
        # bulk-deleting owner accounts also triggers unit vacating.
        tenant_scope_id = _get_tenant_scope_id(request.user)
        if connection.schema_name == 'public':
            residents = User.objects.filter(
                id__in=resident_ids,
                tenant_id=tenant_scope_id,
                role__in=['tenant', 'tenant_vendor', 'owner']
            )
        else:
            residents = User.objects.filter(
                id__in=resident_ids,
                role__in=['tenant', 'tenant_vendor', 'owner']
            )

        requested_ids = {str(rid) for rid in resident_ids}
        found_ids = {str(uid) for uid in residents.values_list('id', flat=True)}
        invalid_ids = sorted(list(requested_ids - found_ids))

        if not residents.exists():
            return Response(
                {
                    'error': 'No valid resident IDs found',
                    'invalid_resident_ids': invalid_ids,
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        success_count = 0
        failed_count = 0
        errors = []
        
        # Perform action based on type
        if action_type == 'delete':
            # Handle delete action with proper error handling
            for resident in residents:
                try:
                    user_id = resident.id
                    user_email = resident.email
                    user_name = resident.get_full_name()
                    
                    logger.info(f"Bulk deleting resident: {user_email}")
                    
                    try:
                        with transaction.atomic():
                            self._vacate_assigned_unit(resident)
                            resident.delete()
                        success_count += 1
                        logger.info(f"Deleted: {user_email}")
                        
                    except ProgrammingError as e:
                        if 'does not exist' in str(e).lower():
                            # Manual deletion for missing tables
                            logger.warning(f"Missing table, using manual deletion for {user_email}")
                            
                            try:
                                with connection.cursor() as cursor:
                                    # CRITICAL: Delete ActivityLog FIRST (foreign key constraint)
                                    cursor.execute(
                                        "DELETE FROM accounts_activitylog WHERE affected_user_id = %s",
                                        [str(user_id)]
                                    )
                                    cursor.execute(
                                        "DELETE FROM accounts_activitylog WHERE user_id = %s",
                                        [str(user_id)]
                                    )
                                    logger.info(f"Deleted ActivityLog for {user_email}")
                                    
                                    cursor.execute(
                                        "DELETE FROM accounts_userprofile WHERE user_id = %s",
                                        [str(user_id)]
                                    )
                                    logger.info(f"Deleted UserProfile for {user_email}")

                                    try:
                                        self._vacate_assigned_unit(resident)
                                    except Exception as vacate_error:
                                        logger.warning(f"Failed to vacate unit in bulk manual delete for {user_email}: {vacate_error}")
                                    
                                    cursor.execute(
                                        "DELETE FROM accounts_user WHERE id = %s",
                                        [str(user_id)]
                                    )
                                    logger.info(f"Deleted User for {user_email}")
                                
                                success_count += 1
                                logger.info(f"Manual deletion successful: {user_email}")
                                
                            except Exception as manual_error:
                                failed_count += 1
                                error_msg = f"Manual deletion failed for {user_email}: {str(manual_error)}"
                                errors.append(error_msg)
                                logger.error(error_msg)
                        else:
                            raise
                            
                except Exception as e:
                    failed_count += 1
                    error_msg = f"Failed to delete {resident.email}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
        
        elif action_type in ['approve', 'disapprove', 'activate', 'deactivate']:
            # Handle non-delete bulk actions
            for resident in residents:
                try:
                    if action_type == 'approve':
                        resident.is_approved = True
                    elif action_type == 'disapprove':
                        resident.is_approved = False
                    elif action_type == 'activate':
                        resident.is_active = True
                    elif action_type == 'deactivate':
                        resident.is_active = False
                    
                    resident.save()
                    success_count += 1
                    
                    # Log activity
                    try:
                        ActivityLog.objects.create(
                            user=request.user,
                            action=f'bulk_{action_type}',
                            description=f'Bulk {action_type}: {resident.get_full_name()}',
                            affected_user=resident,
                            metadata={'action': action_type}
                        )
                    except Exception:
                        pass
                    
                except Exception as e:
                    failed_count += 1
                    error_msg = f"Failed {action_type} for {resident.email}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
        
        # Prepare response
        message = f'{action_type.title()} completed'
        if failed_count > 0:
            message += f' with {failed_count} failures'
        
        response_data = {
            'success': True,
            'message': message,
            'success_count': success_count,
            'failed_count': failed_count,
            'total_count': len(resident_ids)
        }

        if invalid_ids:
            response_data['invalid_count'] = len(invalid_ids)
            response_data['invalid_resident_ids'] = invalid_ids
        
        if errors:
            response_data['errors'] = errors[:10]  # Limit to first 10 errors
        
        return Response(response_data)
    
    @action(detail=False, methods=['post'], url_path='bulk-action', url_name='bulk-action')
    def bulk_action_dash(self, request):
        """
        Backward/forward compatibility alias for clients calling
        /residents/bulk-action/ instead of /residents/bulk_action/.
        """
        return self.bulk_action(request)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a single resident"""
        resident = self.get_object()
        resident.is_approved = True
        resident.save()
        
        try:
            ActivityLog.objects.create(
                user=request.user,
                action='resident_approved',
                description=f'Approved resident: {resident.get_full_name()}',
                affected_user=resident
            )
        except Exception:
            pass
        
        return Response({
            'success': True,
            'message': f'Resident {resident.get_full_name()} approved successfully'
        })
    
    @action(detail=True, methods=['post'])
    def send_welcome_email(self, request, pk=None):
        """Send welcome email to resident"""
        resident = self.get_object()
        
        # Send welcome email
        try:
            from .email_service import EmailService
            EmailService.send_welcome_email(resident)
        except Exception as email_error:
            logger.warning(f"Failed to send welcome email to {resident.email}: {str(email_error)}")

        try:
            ActivityLog.objects.create(
                user=request.user,
                action='welcome_email_sent',
                description=f'Sent welcome email to: {resident.get_full_name()}',
                affected_user=resident
            )
        except Exception:
            pass
        
        return Response({
            'success': True,
            'message': f'Welcome email sent to {resident.email}'
        })
    
    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """Reset resident password"""
        resident = self.get_object()
        
        # Generate temporary password
        import secrets
        temp_password = secrets.token_urlsafe(12)
        resident.set_password(temp_password)
        resident.save()

        # Send password reset email
        try:
            from .email_service import EmailService
            EmailService.send_password_reset_email(resident, temp_password)
        except Exception as email_error:
            logger.warning(f"Failed to send password reset email to {resident.email}: {str(email_error)}")
        
        try:
            ActivityLog.objects.create(
                user=request.user,
                action='password_reset',
                description=f'Reset password for: {resident.get_full_name()}',
                affected_user=resident
            )
        except Exception:
            pass
        
        return Response({
            'success': True,
            'message': f'Password reset for {resident.get_full_name()}',
            'temporary_password': temp_password  # In production, send via email only
        })


# ==================== FUNCTION-BASED VIEWS ====================

@extend_schema(responses=ResidentStatsSerializer)
@api_view(['GET'])
@permission_classes([IsPropertyManagerOrStaff])
def people_hub_stats(request):
    """
    Get statistics for People Hub dashboard
    Returns: total residents, active, pending approval, etc.
    """
    user = request.user
    tenant_scope_id = _get_tenant_scope_id(user)
    
    # Get all residents for current tenant
    if connection.schema_name == 'public':
        residents = User.objects.filter(
            tenant_id=tenant_scope_id,
            role__in=['tenant', 'owner'] # Include owners too for correct stats
        )
    else:
        residents = User.objects.filter(
            role__in=['tenant', 'owner'] # Include owners too for correct stats
        )

    # Calculate statistics in a single consolidated database query
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    stats_aggregate = residents.aggregate(
        total=Count('id'),
        active=Sum(Case(When(is_active=True, then=1), default=0, output_field=IntegerField())),
        inactive=Sum(Case(When(is_active=False, then=1), default=0, output_field=IntegerField())),
        approved=Sum(Case(When(is_approved=True, then=1), default=0, output_field=IntegerField())),
        pending=Sum(Case(When(is_approved=False, then=1), default=0, output_field=IntegerField())),
        verified=Sum(Case(When(email_verified=True, then=1), default=0, output_field=IntegerField())),
        recent=Sum(Case(When(created_at__gte=thirty_days_ago, then=1), default=0, output_field=IntegerField()))
    )
    
    total_residents = stats_aggregate['total'] or 0
    active_residents = stats_aggregate['active'] or 0
    inactive_residents = stats_aggregate['inactive'] or 0
    approved_residents = stats_aggregate['approved'] or 0
    pending_approval = stats_aggregate['pending'] or 0
    verified_emails = stats_aggregate['verified'] or 0
    recent_registrations = stats_aggregate['recent'] or 0
    
    # Residents with active leases (if leases exist) - 1 distinct join query
    with_active_leases = 0
    try:
        from properties.models import Lease
        with_active_leases = residents.filter(
            leases__status='active'
        ).distinct().count()
    except:
        pass
    
    # Occupancy rate (if units exist) - 1 consolidated aggregate query
    occupancy_rate = 0
    try:
        from properties.models import Unit
        unit_stats = Unit.objects.aggregate(
            total_units=Count('id'),
            occupied_units=Sum(Case(When(status='occupied', then=1), default=0, output_field=IntegerField()))
        )
        total_units = unit_stats['total_units'] or 0
        occupied_units = unit_stats['occupied_units'] or 0
        occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0
    except:
        pass
    
    stats = {
        'total_residents': total_residents,
        'active_residents': active_residents,
        'inactive_residents': inactive_residents,
        'approved_residents': approved_residents,
        'pending_approval': pending_approval,
        'verified_emails': verified_emails,
        'with_active_leases': with_active_leases,
        'recent_registrations': recent_registrations,
        'occupancy_rate': round(occupancy_rate, 2)
    }
    
    serializer = ResidentStatsSerializer(stats)
    return Response(serializer.data)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsPropertyManagerOrStaff])
def resident_activity(request, resident_id):
    """Get activity history for a specific resident"""
    try:
        resident_qs = User.objects.filter(
            id=resident_id,
            tenant_id=_get_tenant_scope_id(request.user),
            role='tenant'
        )
        if getattr(request.user, 'role', None) == 'facility_manager':
            resident_qs = _filter_residents_to_manager_blocks(resident_qs, request.user)
        resident = resident_qs.get()
    except User.DoesNotExist:
        return Response(
            {'error': 'Resident not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Get activity logs for this resident
    activities = ActivityLog.objects.filter(
        Q(user=resident) | Q(affected_user=resident)
    ).order_by('-created_at')[:50]
    
    activities_data = []
    for activity in activities:
        activities_data.append({
            'action': activity.action,
            'description': activity.description,
            'performed_by': activity.user.get_full_name() if activity.user else 'System',
            'timestamp': activity.created_at,
            'metadata': activity.metadata
        })
    
    return Response({
        'resident': {
            'id': str(resident.id),
            'name': resident.get_full_name(),
            'email': resident.email
        },
        'activities': activities_data
    })


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsPropertyManagerOrStaff])
def residents_by_building(request):
    """Get resident count grouped by building"""
    residents = User.objects.filter(
        tenant_id=_get_tenant_scope_id(request.user),
        role='tenant'
    )

    if getattr(request.user, 'role', None) == 'facility_manager':
        residents = _filter_residents_to_manager_blocks(residents, request.user)

    residents = residents.values('building_name').annotate(
        count=Count('id')
    ).order_by('-count')
    
    return Response({'buildings': list(residents)})


@extend_schema(responses=OpenApiTypes.BINARY)
@api_view(['GET'])
@permission_classes([IsPropertyManagerOrStaff])
def export_residents(request):
    """Export residents data to CSV"""
    import csv
    from django.http import HttpResponse
    
    residents = User.objects.filter(
        tenant_id=_get_tenant_scope_id(request.user),
        role='tenant'
    ).select_related('profile')

    if getattr(request.user, 'role', None) == 'facility_manager':
        residents = _filter_residents_to_manager_blocks(residents, request.user)
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="residents_export.csv"'
    
    writer = csv.writer(response)
    
    # Write header
    writer.writerow([
        'First Name', 'Last Name', 'Email', 'Phone', 'Unit Number',
        'Building', 'Emergency Contact', 'Emergency Phone', 'Status',
        'Approved', 'Email Verified', 'Created Date'
    ])
    
    # Write data
    for resident in residents:
        writer.writerow([
            resident.first_name,
            resident.last_name,
            resident.email,
            resident.phone,
            resident.unit_number,
            resident.building_name,
            resident.emergency_contact_name,
            resident.emergency_contact_phone,
            'Active' if resident.is_active else 'Inactive',
            'Yes' if resident.is_approved else 'No',
            'Yes' if resident.email_verified else 'No',
            resident.created_at.strftime('%Y-%m-%d')
        ])
    
    # Log export activity
    try:
        ActivityLog.objects.create(
            user=request.user,
            action='residents_exported',
            description=f'Exported {residents.count()} residents to CSV',
            metadata={'count': residents.count()}
        )
    except Exception:
        pass
    
    return response


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([IsPropertyManagerOrStaff])
def send_bulk_notification(request):
    """Send notification to multiple residents"""
    resident_ids = request.data.get('resident_ids', [])
    message = request.data.get('message', '')
    notification_type = request.data.get('type', 'email')  # email, sms, push
    
    if not resident_ids or not message:
        return Response(
            {'error': 'resident_ids and message are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    residents = User.objects.filter(
        id__in=resident_ids,
        tenant_id=_get_tenant_scope_id(request.user),
        role='tenant'
    )

    if getattr(request.user, 'role', None) == 'facility_manager':
        residents = _filter_residents_to_manager_blocks(residents, request.user)
    
    # Send notifications via notification system
    sent_count = 0
    try:
        for resident in residents:
            NotificationService.send(
                user=resident,
                title='Message from Management',
                message=message,
                notification_type=notification_type,
                priority='medium',
                send_email=(notification_type == 'email'),
                send_sms=(notification_type == 'sms'),
                send_push=(notification_type == 'push')
            )
            sent_count += 1
    except Exception as notif_error:
        logger.warning(f"Notification module error: {str(notif_error)}")

    for resident in residents:
        try:
            ActivityLog.objects.create(
                user=request.user,
                action='notification_sent',
                description=f'Sent {notification_type} notification to {resident.get_full_name()}',
                affected_user=resident,
                metadata={
                    'type': notification_type,
                    'message': message[:100]
                }
            )
        except Exception:
            pass
    
    return Response({
        'message': f'Notification sent to {residents.count()} residents',
        'count': residents.count()
    })


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([IsPropertyManagerOrStaff])
def residents_directory(request):
    """Get simplified residents directory for quick reference"""
    residents = User.objects.filter(
        tenant_id=request.user.tenant_id,
        role='tenant',
        is_active=True
    ).order_by('building_name', 'unit_number')
    
    directory = []
    for resident in residents:
        directory.append({
            'id': str(resident.id),
            'name': resident.get_full_name(),
            'email': resident.email,
            'phone': resident.phone,
            'unit': f"{resident.building_name} - {resident.unit_number}",
        })
    
    return Response({'directory': directory})


@api_view(['POST'])
@permission_classes([IsPropertyManagerOrStaff])
def bulk_import(request):
    """
    Bulk import residents from CSV file
    Expected CSV format: first_name, last_name, email, phone, building, unit
    """
    import csv
    import io
    import secrets

    if 'file' not in request.FILES:
        return Response(
            {'error': 'No file uploaded'},
            status=status.HTTP_400_BAD_REQUEST
        )

    file = request.FILES['file']

    # Validate file type
    if not file.name.lower().endswith('.csv'):
        return Response(
            {'error': 'Invalid file type. Only CSV files are accepted.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Read and decode file content
    try:
        decoded_file = file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            file.seek(0)
            decoded_file = file.read().decode('latin-1')
        except Exception:
            return Response(
                {'error': 'Unable to read file. Please ensure it is a valid CSV with UTF-8 encoding.'},
                status=status.HTTP_400_BAD_REQUEST
            )

    reader = csv.DictReader(io.StringIO(decoded_file))

    # Validate CSV headers
    if reader.fieldnames is None:
        return Response(
            {'error': 'CSV file is empty or has no header row.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Normalize headers: strip whitespace and lowercase
    normalized_headers = [h.strip().lower().replace(' ', '_') for h in reader.fieldnames]

    # Map expected column names to possible variations
    column_map = {}
    for idx, header in enumerate(normalized_headers):
        if header in ('first_name', 'firstname', 'first'):
            column_map['first_name'] = reader.fieldnames[idx]
        elif header in ('last_name', 'lastname', 'last'):
            column_map['last_name'] = reader.fieldnames[idx]
        elif header in ('email', 'email_address', 'emailaddress'):
            column_map['email'] = reader.fieldnames[idx]
        elif header in ('phone', 'phone_number', 'phonenumber', 'mobile', 'contact'):
            column_map['phone'] = reader.fieldnames[idx]
        elif header in ('building', 'building_name', 'buildingname'):
            column_map['building'] = reader.fieldnames[idx]
        elif header in ('unit', 'unit_number', 'unitnumber', 'unit_no', 'apt', 'apartment'):
            column_map['unit'] = reader.fieldnames[idx]

    required_columns = ['first_name', 'last_name', 'email']
    missing_columns = [col for col in required_columns if col not in column_map]
    if missing_columns:
        return Response(
            {
                'error': f'Missing required CSV columns: {", ".join(missing_columns)}',
                'expected_columns': 'first_name, last_name, email, phone, building, unit',
                'found_columns': reader.fieldnames,
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Collect existing emails for duplicate checking (within this tenant)
    existing_emails = set(
        User.objects.filter(tenant_id=request.user.tenant_id)
        .values_list('email', flat=True)
    )

    success_count = 0
    failed_count = 0
    errors = []
    created_residents = []

    # Track emails seen within this import to catch intra-file duplicates
    seen_emails_in_file = set()

    for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is the header
        row_errors = []

        # Extract and clean values
        first_name = row.get(column_map.get('first_name', ''), '').strip()
        last_name = row.get(column_map.get('last_name', ''), '').strip()
        email = row.get(column_map.get('email', ''), '').strip().lower()
        phone = row.get(column_map.get('phone', ''), '').strip() if 'phone' in column_map else ''
        building = row.get(column_map.get('building', ''), '').strip() if 'building' in column_map else ''
        unit = row.get(column_map.get('unit', ''), '').strip() if 'unit' in column_map else ''

        # Validate required fields
        if not first_name:
            row_errors.append('first_name is required')
        if not last_name:
            row_errors.append('last_name is required')
        if not email:
            row_errors.append('email is required')

        # Basic email format validation
        if email and ('@' not in email or '.' not in email.split('@')[-1]):
            row_errors.append(f'Invalid email format: {email}')

        # Check for duplicate email in database
        if email and email in existing_emails:
            row_errors.append(f'Email already exists: {email}')

        # Check for duplicate email within the CSV file itself
        if email and email in seen_emails_in_file:
            row_errors.append(f'Duplicate email in CSV: {email}')

        if row_errors:
            failed_count += 1
            errors.append({
                'row': row_num,
                'email': email or '(empty)',
                'errors': row_errors,
            })
            continue

        # Mark email as seen for intra-file duplicate detection
        seen_emails_in_file.add(email)

        # Generate a unique username from email
        base_username = email.split('@')[0]
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base_username}_{counter}'
            counter += 1

        # Generate temporary password
        temp_password = secrets.token_urlsafe(12)

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=temp_password,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                building_name=building,
                unit_number=unit,
                role='tenant',
                tenant_id=request.user.tenant_id,
                is_approved=True,
                is_active=True,
            )

            # Create UserProfile if it does not already exist
            UserProfile.objects.get_or_create(user=user)

            existing_emails.add(email)
            success_count += 1
            created_residents.append({
                'id': str(user.id),
                'name': user.get_full_name(),
                'email': user.email,
            })

        except Exception as e:
            failed_count += 1
            errors.append({
                'row': row_num,
                'email': email,
                'errors': [str(e)],
            })
            logger.error(f'Bulk import error at row {row_num} ({email}): {str(e)}')

    # Log the bulk import activity
    try:
        ActivityLog.objects.create(
            user=request.user,
            action='bulk_import',
            description=f'Bulk imported {success_count} residents from CSV ({failed_count} failed)',
            metadata={
                'success_count': success_count,
                'failed_count': failed_count,
                'filename': file.name,
            }
        )
    except Exception as log_error:
        logger.warning(f'Could not log bulk import activity: {str(log_error)}')

    logger.info(
        f'Bulk import completed by {request.user.email}: '
        f'{success_count} success, {failed_count} failed, file={file.name}'
    )

    response_data = {
        'success': True,
        'message': f'Bulk import completed: {success_count} imported, {failed_count} failed',
        'success_count': success_count,
        'failed_count': failed_count,
        'total_rows': success_count + failed_count,
        'created_residents': created_residents[:50],  # Limit to first 50 in response
    }

    if errors:
        response_data['errors'] = errors[:50]  # Limit to first 50 errors in response

    return Response(
        response_data,
        status=status.HTTP_201_CREATED if success_count > 0 else status.HTTP_400_BAD_REQUEST
    )