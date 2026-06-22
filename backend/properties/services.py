# properties/services.py - Updated to fix server synchronization
from django.db import transaction
import logging

logger = logging.getLogger(__name__)


def toggle_township_user_roles(township, set_active: bool, triggered_by_user):
    """
    Backward-compatible alias — delegates to the full cascade function.
    """
    toggle_township_cascade(township, set_active, triggered_by_user)


def toggle_township_cascade(township, set_active: bool, triggered_by_user):
    """
    ER-style cascade: toggling a Township's is_active propagates down the full
    hierarchy:

        Township
            └── Building  (is_active)
                    └── Block  (is_active)
                            └── Floor  (is_active)
                                    └── Unit  (is_active)
                                            └── Lease  (status → suspended / active)
        All residents whose primary building is in this township:
            └── UserRole  (is_active)

    Invoices / Payment records are intentionally left untouched so they
    remain visible for historical reference.
    """
    from .models import Building, Block, Floor, Unit, Lease
    from accounts.models import User, UserRole

    with transaction.atomic():
        # ── 1. Buildings ──────────────────────────────────────────────────────
        # In a multi-tenant single-property setup, catching orphaned buildings (township_id=None) is critical.
        from properties.models import Township
        from django.db.models import Q
        
        total_townships = Township.objects.count()
        if total_townships <= 1:
            buildings = Building.objects.all()
        else:
            buildings = Building.objects.filter(Q(township=township) | Q(township__isnull=True))
            
        building_ids = list(buildings.values_list('id', flat=True))
        building_names = list(buildings.values_list('name', flat=True))

        buildings.update(is_active=set_active)
        logger.info(
            f"[CascadeToggle] {len(building_ids)} buildings -> is_active={set_active} "
            f"for Township '{township.name}' ({township.id})"
        )

        if not building_ids:
            return

        # ── 2. Blocks ─────────────────────────────────────────────────────────
        blocks = Block.objects.filter(building_id__in=building_ids)
        block_ids = list(blocks.values_list('id', flat=True))
        blocks.update(is_active=set_active)
        logger.info(f"[CascadeToggle] {len(block_ids)} blocks -> is_active={set_active}")

        # ── 3. Floors ─────────────────────────────────────────────────────────
        floors = Floor.objects.filter(block_id__in=block_ids)
        floor_ids = list(floors.values_list('id', flat=True))
        floors.update(is_active=set_active)
        logger.info(f"[CascadeToggle] {len(floor_ids)} floors -> is_active={set_active}")

        # ── 4. Units ──────────────────────────────────────────────────────────
        units = Unit.objects.filter(building_id__in=building_ids)
        unit_ids = list(units.values_list('id', flat=True))
        units.update(is_active=set_active)
        logger.info(f"[CascadeToggle] {len(unit_ids)} units -> is_active={set_active}")

        # ── 5. Leases ─────────────────────────────────────────────────────────
        # When deactivating: suspend active leases (keep record, just flag them).
        # When activating: restore suspended leases back to active.
        if set_active:
            lease_qs = Lease.objects.filter(unit_id__in=unit_ids, status='suspended')
            lease_count = lease_qs.update(status='active')
        else:
            lease_qs = Lease.objects.filter(unit_id__in=unit_ids, status='active')
            lease_count = lease_qs.update(status='suspended')
        logger.info(
            f"[CascadeToggle] {lease_count} leases -> "
            f"status={'active' if set_active else 'suspended'}"
        )

        # ── 6. User Roles and Users ───────────────────────────────────────────
        # If there's only one colony, deactivating it deactivates all tenant-schema users except super Admins.
        if total_townships <= 1:
            users_in_township = User.objects.all()
        else:
            users_in_township = User.objects.filter(
                Q(building_name__in=building_names) | 
                Q(leases__unit__in=unit_ids)
            ).distinct()
            
        users_in_township = users_in_township.exclude(
            role__in=['master_admin', 'super_admin']
        )

        users_count = users_in_township.update(is_active=set_active)
        logger.info(
            f"[CascadeToggle] {users_count} users (accounts) -> is_active={set_active} "
            f"for Township '{township.name}'"
        )

        user_roles = UserRole.objects.filter(
            user__in=users_in_township
        ).exclude(
            role__name__in=['master_admin', 'super_admin']
        )

        updated_roles = 0
        for ur in user_roles:
            ur.is_active = set_active

            if not set_active:
                msg = f"[System: Auto-deactivated due to Township '{township.name}' shutdown]"
                if msg not in (ur.notes or ''):
                    ur.notes = f"{ur.notes or ''}\n{msg}".strip()
            else:
                # Strip the auto-deactivation note on re-activation
                tag = f"[System: Auto-deactivated due to Township '{township.name}' shutdown]"
                ur.notes = (ur.notes or '').replace(tag, '').strip()

            ur.save(update_fields=['is_active', 'notes'])
            updated_roles += 1

        logger.info(
            f"[CascadeToggle] {updated_roles} user roles -> is_active={set_active} "
            f"for Township '{township.name}'"
        )
