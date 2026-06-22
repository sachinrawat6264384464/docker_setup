"""Facility Manager scope utilities backed by FacilityManagerAssignment."""

from django.db.models import Q


def get_fm_scope(user):
    """
    Returns a dict of accessible property PKs (as strings) for a facility manager:

        {
            'township_ids': frozenset[str],
            'building_ids': frozenset[str],
            'block_ids':    frozenset[str],
        }

    Returns None when the user is not a facility_manager (caller should apply
    no restriction in that case).
    """
    if not (user and getattr(user, 'is_authenticated', False)):
        return None
    if getattr(user, 'role', None) != 'facility_manager':
        return None

    from properties.models import FacilityManagerAssignment, Block, Building

    assignments = list(
        FacilityManagerAssignment.objects.filter(
            facility_manager=user, is_active=True
        ).select_related('block__building')
    )

    township_ids = set()
    direct_building_ids = set()
    direct_block_ids = set()

    for a in assignments:
        if a.scope_type == 'township' and a.township_id:
            township_ids.add(str(a.township_id))
        elif a.scope_type == 'building' and a.building_id:
            direct_building_ids.add(str(a.building_id))
        elif a.scope_type == 'block' and a.block_id:
            direct_block_ids.add(str(a.block_id))

    # Expand township → buildings (full access)
    township_building_ids = set()
    if township_ids:
        t_bld = Building.objects.filter(
            township_id__in=township_ids
        ).values_list('id', flat=True)
        township_building_ids.update(str(pk) for pk in t_bld)

    scoped_building_ids = set(direct_building_ids) | township_building_ids

    # Blocks from building/township scopes are fully accessible.
    block_ids = set(direct_block_ids)
    if scoped_building_ids:
        b_blk = Block.objects.filter(building_id__in=scoped_building_ids).values_list('id', flat=True)
        block_ids.update(str(pk) for pk in b_blk)

    # Buildings implied by direct block scopes are visible but do not expand to all blocks.
    building_ids = set(scoped_building_ids)
    if direct_block_ids:
        blk_bld = Block.objects.filter(id__in=direct_block_ids).values_list('building_id', flat=True)
        building_ids.update(str(pk) for pk in blk_bld)

    return {
        'township_ids': frozenset(township_ids),
        'building_ids': frozenset(building_ids),
        'block_ids':    frozenset(block_ids),
    }


def get_fm_building_ids(user):
    """Returns frozenset of accessible building PKs (strings), or None if not an FM."""
    scope = get_fm_scope(user)
    return None if scope is None else scope['building_ids']


def get_fm_block_ids(user):
    """Returns frozenset of accessible block PKs (strings), or None if not an FM."""
    scope = get_fm_scope(user)
    return None if scope is None else scope['block_ids']


def get_fm_building_names(user):
    """
    Returns frozenset of building *names* accessible to this FM.
    Used for filtering models that store building as a plain CharField
    (e.g. MaintenanceRequest, Invoice).
    """
    scope = get_fm_scope(user)
    if scope is None:
        return None
    if not scope['building_ids']:
        return frozenset()
    from properties.models import Building
    names = Building.objects.filter(
        id__in=scope['building_ids']
    ).values_list('name', flat=True)
    return frozenset(names)


def get_fm_unit_pairs(user):
    """
    Returns frozenset of (building_name, unit_number) accessible to this FM.
    Includes legacy Unit.block matching for units without floor_ref.
    """
    scope = get_fm_scope(user)
    if scope is None:
        return None
    if not scope['building_ids'] and not scope['block_ids']:
        return frozenset()

    from properties.models import Unit, Block

    units_q = Q()
    if scope['building_ids']:
        units_q |= Q(building_id__in=scope['building_ids'])
    if scope['block_ids']:
        units_q |= Q(floor_ref__block_id__in=scope['block_ids'])

        legacy_block_pairs = Block.objects.filter(id__in=scope['block_ids']).values_list('building__name', 'name')
        legacy_q = Q()
        for building_name, block_name in legacy_block_pairs:
            if building_name and block_name:
                legacy_q |= Q(building__name__iexact=building_name, block__iexact=block_name)
        if legacy_q.children:
            units_q |= legacy_q

    if not units_q.children:
        return frozenset()

    pairs = Unit.objects.filter(units_q).values_list('building__name', 'unit_number').distinct()
    return frozenset((b, u) for b, u in pairs if b and u)


def is_building_accessible(user, building_id):
    """True if building_id is in FM's scope (always True for non-FM users)."""
    ids = get_fm_building_ids(user)
    if ids is None:
        return True
    return str(building_id) in ids


def is_block_accessible(user, block_id):
    """True if block_id is in FM's scope (always True for non-FM users)."""
    ids = get_fm_block_ids(user)
    if ids is None:
        return True
    return str(block_id) in ids

def is_facility_manager(user):
    """Returns True if the user is a Facility Manager."""
    return bool(user and getattr(user, 'is_authenticated', False) and getattr(user, 'role', None) == 'facility_manager')


def get_manager_building_ids(user):
    """
    Returns a list of building UUIDs (strings) accessible to this FM, or None if
    the user is not a facility manager (no restriction).
    """
    if not is_facility_manager(user):
        return None
    ids = get_fm_building_ids(user)
    return list(ids) if ids is not None else []


def get_manager_block_ids(user):
    """
    Returns a list of block UUIDs (strings) accessible to this FM, or None.
    """
    if not is_facility_manager(user):
        return None
    ids = get_fm_block_ids(user)
    return list(ids) if ids is not None else []
