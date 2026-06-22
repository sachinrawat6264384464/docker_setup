# accounts/bulk_upload_view.py
"""
Smart Bulk Upload Resident View
================================
- Reads a CSV file row by row
- For each row: auto-creates Building → Block → Floor → Unit if missing
- Creates the resident (User + UserProfile) exactly like ResidentCreateSerializer
- Creates a Lease record if lease dates are provided
- Returns a comprehensive result JSON immediately (synchronous, no Celery)
- Routes: POST /api/auth/csv/bulk-upload/
          GET  /api/auth/csv/template/
"""
import csv
import io
import re
import logging
import uuid
from urllib.parse import urlparse
from decimal import Decimal, InvalidOperation
import requests

from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse

from properties.models import Building, Block, Floor, Unit, Lease, Township, PropertyDocument
from .models import UserProfile, ActivityLog

User = get_user_model()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# PERMISSION GUARD  (same as IsPropertyManagerOrStaff in people_hub_views)
# ─────────────────────────────────────────────────────────────
def _is_authorized(user):
    """Only master_admin / super_admin / facility_manager / property_staff can upload."""
    return (
        user
        and user.is_authenticated
        and hasattr(user, 'can_manage_property')
        and user.can_manage_property
    )


# ─────────────────────────────────────────────────────────────
# CLEANING HELPERS
# ─────────────────────────────────────────────────────────────
def _clean_str(value, default=''):
    return str(value).strip() if value else default


def _clean_phone(value):
    """Strip non-digits, allow 10–15 chars."""
    digits = re.sub(r'\D', '', str(value or ''))
    return digits if 10 <= len(digits) <= 15 else None


def _clean_decimal(value, default=None):
    if not value:
        return default
    try:
        return Decimal(str(value).strip().replace(',', ''))
    except InvalidOperation:
        return default


def _clean_int(value, default=None):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def _clean_date(value):
    """Parse YYYY-MM-DD  or  DD-MM-YYYY  or  DD/MM/YYYY."""
    if not value:
        return None
    v = str(value).strip()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            from datetime import datetime
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _clean_email(value):
    value = str(value or '').strip().lower()
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return value if re.match(pattern, value) else None


# ─────────────────────────────────────────────────────────────
# HIERARCHY AUTO-CREATE HELPERS
# ─────────────────────────────────────────────────────────────
def _get_or_create_township(colony_name, city='', state='', country='India', cache=None):
    """Find township/colony by name (case-insensitive) or create it."""
    colony_name = _clean_str(colony_name)
    if not colony_name:
        return None, False

    if cache is not None:
        township = cache['townships'].get(colony_name.lower())
        if township:
            return township, False

    township = Township.objects.filter(name__iexact=colony_name).first()
    if township:
        if cache is not None:
            cache['townships'][colony_name.lower()] = township
        return township, False

    township = Township.objects.create(
        name=colony_name,
        address=colony_name,
        address_line1=colony_name,
        city=city or '',
        state=state or '',
        country=country or 'India',
    )
    if cache is not None:
        cache['townships'][colony_name.lower()] = township
    logger.info(f"[BulkUpload] Created new Township/Colony: '{township.name}'")
    return township, True


def _get_or_create_building(building_name, township=None, city='', state='', country='India', cache=None):
    """Find building by name (and township when provided) or create it."""
    building_name = building_name.strip()
    building = None
    if cache is not None:
        if township:
            building = next((b for b in cache['buildings'] if b.name.lower() == building_name.lower() and b.township_id == township.id), None)
        else:
            building = next((b for b in cache['buildings'] if b.name.lower() == building_name.lower()), None)
            
    if not building:
        if township:
            building = Building.objects.filter(
                name__iexact=building_name,
                township=township,
            ).first()
        else:
            building = Building.objects.filter(name__iexact=building_name).first()

    if building:
        # Keep existing records enriched when better location data is supplied.
        changed_fields = []
        if township and building.township_id != township.id:
            building.township = township
            changed_fields.append('township')
        if city and not _clean_str(building.city):
            building.city = city
            changed_fields.append('city')
        if state and not _clean_str(building.state):
            building.state = state
            changed_fields.append('state')
        if country and not _clean_str(building.country):
            building.country = country
            changed_fields.append('country')
        if changed_fields:
            building.save(update_fields=changed_fields)
        return building, False

    building = Building.objects.create(
        township=township,
        name=building_name,
        address=building_name,
        address_line1=building_name,
        city=city or '',
        state=state or '',
        country=country or 'India',
        building_type='residential',
    )
    if cache is not None:
        cache['buildings'].append(building)
    logger.info(f"[BulkUpload] Created new Building: '{building.name}'")
    return building, True


def _get_or_create_block(building, block_name, cache=None):
    """Find block under building or create it."""
    block = None
    if cache is not None:
        block = next((b for b in cache['blocks'] if b.building_id == building.id and b.name.lower() == block_name.strip().lower()), None)
    if not block:
        block = Block.objects.filter(
            building=building,
            name__iexact=block_name.strip()
        ).first()
    if block:
        return block, False
    block = Block.objects.create(
        building=building,
        name=block_name.strip(),
        building_type='residential',
        total_floors=1,
    )
    if cache is not None:
        cache['blocks'].append(block)
    logger.info(f"[BulkUpload] Created new Block: '{block.name}' in Building '{building.name}'")
    return block, True


def _get_or_create_floor(block, floor_number, cache=None):
    """Find floor under block or create it."""
    try:
        floor_number = int(floor_number)
    except (ValueError, TypeError):
        floor_number = 1

    floor = None
    if cache is not None:
        floor = next((f for f in cache['floors'] if f.block_id == block.id and f.floor_number == floor_number), None)
    if not floor:
        floor = Floor.objects.filter(block=block, floor_number=floor_number).first()
    if floor:
        return floor, False
    floor = Floor.objects.create(
        block=block,
        floor_number=floor_number,
        label=f'Floor {floor_number}',
    )
    if cache is not None:
        cache['floors'].append(floor)
    logger.info(f"[BulkUpload] Created new Floor {floor_number} in Block '{block.name}'")
    return floor, True


def _get_or_create_unit(building, block_name, floor_number, unit_number,
                         bedrooms=None, bathrooms=None, square_feet=None,
                         monthly_rent=None, floor_obj=None, cache=None):
    """
    Find unit by (building, unit_number) or create it.
    Links the unit to the Floor hierarchy if floor_obj is provided.
    """
    unit = None
    if cache is not None:
        unit = next((u for u in cache['units'] if u.building_id == building.id and u.unit_number.lower() == unit_number.strip().lower()), None)
    if not unit:
        unit = Unit.objects.filter(
            building=building,
            unit_number__iexact=unit_number.strip()
        ).first()
    if unit:
        # Enrich existing unit with hierarchy/spec data when currently empty or outdated.
        changed_fields = []
        cleaned_block = block_name.strip() if block_name else ''
        cleaned_floor = _clean_int(floor_number, default=None)
        if cleaned_block and _clean_str(unit.block) != cleaned_block:
            unit.block = cleaned_block
            changed_fields.append('block')
        if cleaned_floor is not None and unit.floor != cleaned_floor:
            unit.floor = cleaned_floor
            changed_fields.append('floor')
        if floor_obj and unit.floor_ref_id != floor_obj.id:
            unit.floor_ref = floor_obj
            changed_fields.append('floor_ref')

        clean_bedrooms = _clean_int(bedrooms)
        clean_bathrooms = _clean_decimal(bathrooms)
        clean_sqft = _clean_int(square_feet)
        clean_rent = _clean_decimal(monthly_rent)

        if clean_bedrooms is not None and unit.bedrooms is None:
            unit.bedrooms = clean_bedrooms
            changed_fields.append('bedrooms')
        if clean_bathrooms is not None and unit.bathrooms is None:
            unit.bathrooms = clean_bathrooms
            changed_fields.append('bathrooms')
        if clean_sqft is not None and unit.square_feet is None:
            unit.square_feet = clean_sqft
            changed_fields.append('square_feet')
        if clean_rent is not None and unit.monthly_rent is None:
            unit.monthly_rent = clean_rent
            changed_fields.append('monthly_rent')

        if changed_fields:
            unit.save(update_fields=changed_fields)
        return unit, False

    unit = Unit.objects.create(
        building=building,
        unit_number=unit_number.strip(),
        block=block_name.strip() if block_name else '',
        floor=_clean_int(floor_number, default=None),
        floor_ref=floor_obj,
        unit_type='vacant',
        status='available',
        is_occupied=False,
        bedrooms=_clean_int(bedrooms),
        bathrooms=_clean_decimal(bathrooms),
        square_feet=_clean_int(square_feet),
        monthly_rent=_clean_decimal(monthly_rent),
    )
    if cache is not None:
        cache['units'].append(unit)
    logger.info(f"[BulkUpload] Created new Unit '{unit.unit_number}' in Building '{building.name}'")
    return unit, True


# ─────────────────────────────────────────────────────────────
# RESIDENT CREATION (mirrors ResidentCreateSerializer.create)
# ─────────────────────────────────────────────────────────────
def _create_or_skip_resident(admin_user, validated_row, unit, cache=None):
    """
    Create User + UserProfile. If email already exists, returns (None, 'skipped', msg).
    Returns (user, 'created', '') on success.
    Raises Exception on failure.
    """
    email = validated_row['email']
    if cache is not None:
        if email.lower() in cache['emails']:
            return None, 'skipped', f"Email '{email}' already exists"
    else:
        if User.objects.filter(email=email).exists():
            return None, 'skipped', f"Email '{email}' already exists"

    # Generate unique username
    base_username = email.split('@')[0].lower()
    username = base_username
    counter = 1
    if cache is not None:
        while username in cache['usernames']:
            username = f"{base_username}{counter}"
            counter += 1
    else:
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

    import secrets
    password = secrets.token_urlsafe(12)

    user = User.objects.create_user(
        username=username,
        email=email,
        first_name=validated_row.get('first_name', ''),
        last_name=validated_row.get('last_name', ''),
        phone=validated_row.get('phone') or '',
        unit_number=unit.unit_number,
        building_name=unit.building.name,
        emergency_contact_name=validated_row.get('emergency_contact_name', ''),
        emergency_contact_phone=validated_row.get('emergency_contact_phone', ''),
        password=password,
    )
    user.role = 'tenant'
    user.tenant_id = admin_user.tenant_id
    user.is_approved = True
    user.save(update_fields=['role', 'tenant_id', 'is_approved'])
    
    if cache is not None:
        cache['emails'].add(email.lower())
        cache['usernames'].add(username)

    # Create UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Mirror key profile_data fields used in resident add/edit dialogs.
    profile_updates = {}
    profile_dob = validated_row.get('date_of_birth')
    profile_occupation = _clean_str(validated_row.get('occupation'))
    if profile_dob:
        profile_updates['date_of_birth'] = profile_dob
    if profile_occupation:
        profile_updates['occupation'] = profile_occupation
    if profile_updates:
        for key, value in profile_updates.items():
            setattr(profile, key, value)
        profile.save(update_fields=list(profile_updates.keys()))

    return user, 'created', ''


def _mark_unit_occupied(unit, user):
    """Mark unit as occupied — mirrors LeaseViewSet.perform_create."""
    unit.status = 'occupied'
    unit.is_occupied = True
    unit.unit_type = 'tenant_occupied'
    unit.current_resident = user.get_full_name() or user.email
    unit.save(update_fields=['status', 'is_occupied', 'unit_type', 'current_resident'])


def _create_lease(admin_user, unit, user, row_data):
    """Deprecated: lease creation is deferred until rental document workflow."""
    return None


def _create_lease_direct(
    admin_user, unit, user,
    start_date, end_date,
    monthly_rent, security_deposit, maintenance_charge
):
    """Deprecated: lease creation is deferred until rental document workflow."""
    return None


# VALIDATE CSV HEADERS
# ─────────────────────────────────────────────────────────────
REQUIRED_COLUMNS = {
    # Resident identity
    'first_name', 'last_name', 'email',
    # Property hierarchy
    'building_name', 'unit_number',
}

OPTIONAL_COLUMNS = {
    # Optional resident contact
    'phone',
    # Optional hierarchy and location fields
    'colony_name', 'township_name',
    'block_name', 'wing_name', 'floor_number',
    'city', 'state', 'country',
    # Optional lease fields
    'lease_start_date', 'lease_end_date',
    'monthly_rent', 'security_deposit', 'maintenance_charge',
    # Unit specs
    'bedrooms', 'bathrooms', 'square_feet',
    # Resident extras
    'emergency_contact_name', 'emergency_contact_phone',
    'occupation', 'date_of_birth',
    # Optional document import fields
    'document_title', 'document_type', 'document_pdf_url', 'document_file_name',
}

VALID_DOCUMENT_TYPES = {
    'lease_agreement', 'property_deed', 'insurance', 'tax_document',
    'utility_bill', 'maintenance_record', 'inspection_report', 'other'
}


def _validate_headers(headers):
    """Return (normalized_headers, missing_required_cols)."""
    normalized = [h.strip().lower().replace(' ', '_') for h in headers]
    missing = REQUIRED_COLUMNS - set(normalized)
    return normalized, missing


def validate_safe_url(url):
    """
    Validates that a URL is safe for server-side requests (prevents SSRF).
    Ensures:
    1. Scheme is http or https.
    2. Host exists and resolves to public IP addresses only.
    3. Blocks localhost, private IP subnets, link-local, multicast, etc.
    """
    import socket
    import ipaddress
    from urllib.parse import urlparse

    if not url:
        raise ValueError("URL is empty.")
    
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError("Only http and https schemes are allowed.")
    
    host = parsed.hostname
    if not host:
        raise ValueError("Invalid URL hostname.")
        
    try:
        # Resolve hostname to IP address
        # Note: If the host is already an IP, getaddrinfo handles it correctly.
        addr_info = socket.getaddrinfo(host, parsed.port or (80 if parsed.scheme == 'http' else 443))
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve hostname '{host}': {e}")
        
    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise ValueError(f"Invalid IP address resolved: {ip_str}")
            
        # Check if the IP is private or loopback or link-local
        if ip.is_loopback:
            raise ValueError(f"Loopback IP {ip_str} is blocked.")
        if ip.is_private:
            raise ValueError(f"Private IP {ip_str} is blocked.")
        if ip.is_link_local:
            raise ValueError(f"Link-local IP {ip_str} is blocked.")
        if ip.is_multicast:
            raise ValueError(f"Multicast IP {ip_str} is blocked.")
        if ip.is_reserved:
            raise ValueError(f"Reserved IP {ip_str} is blocked.")
            
        # Extra check for AWS Metadata IP
        if ip_str == '169.254.169.254':
            raise ValueError("AWS Metadata endpoint is blocked.")
            
    return True


def _download_document_pdf(document_url: str) -> bytes:
    """Download PDF content for CSV-provided document URL."""
    try:
        # VAPT-2026-015 / VAPT-2026-023: Prevent SSRF
        validate_safe_url(document_url)
    except ValueError as ve:
        raise ValueError(f"SSRF warning: {ve}")

    try:
        response = requests.get(document_url, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"Failed to download document_pdf_url: {exc}")

    content_type = (response.headers.get('Content-Type') or '').lower()
    if 'pdf' not in content_type and not document_url.lower().endswith('.pdf'):
        raise ValueError('document_pdf_url must point to a PDF file')

    if not response.content:
        raise ValueError('Downloaded PDF is empty')

    return response.content


def _derive_document_filename(document_url: str, provided_name: str = '') -> str:
    """Create a safe .pdf file name for PropertyDocument.file."""
    file_name = _clean_str(provided_name)
    if not file_name:
        parsed = urlparse(document_url)
        candidate = (parsed.path or '').split('/')[-1]
        file_name = candidate or f'document-{uuid.uuid4().hex}.pdf'

    if not file_name.lower().endswith('.pdf'):
        file_name = f'{file_name}.pdf'

    return file_name


def _create_unit_document(admin_user, building, unit, lease, row_data):
    """Create PropertyDocument from CSV row when document_pdf_url is provided."""
    document_url = _clean_str(row_data.get('document_pdf_url'))
    if not document_url:
        return None

    document_title = _clean_str(row_data.get('document_title')) or f'Lease Document - {unit.unit_number}'
    document_type = _clean_str(row_data.get('document_type'), default='lease_agreement').lower()
    if document_type not in VALID_DOCUMENT_TYPES:
        raise ValueError(
            f"Invalid document_type '{document_type}'. Allowed: {', '.join(sorted(VALID_DOCUMENT_TYPES))}"
        )

    file_bytes = _download_document_pdf(document_url)
    file_name = _derive_document_filename(document_url, _clean_str(row_data.get('document_file_name')))

    document = PropertyDocument(
        building=building,
        unit=unit,
        lease=lease,
        title=document_title,
        document_type=document_type,
        description=f'Imported from bulk upload CSV. Source URL: {document_url}',
        uploaded_by=admin_user,
    )
    document.file.save(file_name, ContentFile(file_bytes), save=False)
    document.save()
    return document


def _build_block_identifier(block_name, wing_name):
    """
    Build a stable block identifier from block and wing values.
    We persist a single Block model value in this codebase, so when both values
    are provided we combine them to preserve both levels from CSV.
    """
    block_name = _clean_str(block_name)
    wing_name = _clean_str(wing_name)

    if block_name and wing_name:
        if block_name.lower() == wing_name.lower():
            return block_name
        return f"{block_name} - {wing_name}"
    return wing_name or block_name or 'A'


# ─────────────────────────────────────────────────────────────
# MAIN VIEW: POST /api/auth/csv/bulk-upload/
# ─────────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_upload_residents(request):
    """
    Upload a CSV file to bulk-create residents.
    Auto-creates: Building → Block → Floor → Unit if not found.
    Creates: User + UserProfile + Lease (if dates provided).
    Returns comprehensive per-row results.
    """
    if not _is_authorized(request.user):
        return Response(
            {'error': 'You do not have permission to upload residents.'},
            status=status.HTTP_403_FORBIDDEN
        )

    # ── File validation ──────────────────────────────────────
    csv_file = request.FILES.get('file')
    if not csv_file:
        return Response({'error': 'No file uploaded. Send file as multipart/form-data with key "file".'}, status=400)

    if not csv_file.name.lower().endswith('.csv'):
        return Response({'error': 'Only .csv files are accepted.'}, status=400)

    if csv_file.size > 10 * 1024 * 1024:  # 10 MB
        return Response({'error': 'File size must be under 10 MB.'}, status=400)

    # ── Read CSV ─────────────────────────────────────────────
    try:
        raw = csv_file.read().decode('utf-8-sig')  # Handle BOM
    except UnicodeDecodeError:
        try:
            csv_file.seek(0)
            raw = csv_file.read().decode('latin-1')
        except Exception:
            return Response({'error': 'Could not decode file. Please use UTF-8 encoding.'}, status=400)

    reader = csv.DictReader(io.StringIO(raw))
    headers = reader.fieldnames or []

    normalized_headers, missing = _validate_headers(headers)
    if missing:
        return Response({
            'error': f'Missing required columns: {", ".join(sorted(missing))}',
            'hint': 'Download the template to see the correct column names.'
        }, status=400)

    # ── Process rows ─────────────────────────────────────────
    results = {
        'total': 0,
        'success': 0,
        'skipped': 0,
        'failed': 0,
        'created_colonies': [],
        'created_buildings': [],
        'created_blocks': [],
        'created_floors': [],
        'created_units': [],
        'created_documents': [],
        'rows': [],          # per-row detail
    }

    # Normalise reader to use lowercase keys
    rows = []
    for r in reader:
        rows.append({k.strip().lower().replace(' ', '_'): v for k, v in r.items()})

    results['total'] = len(rows)

    if results['total'] == 0:
        return Response({'error': 'CSV file is empty (no data rows found).'}, status=400)

    if results['total'] > 1000:
        return Response({'error': 'Maximum 1000 rows per upload. Please split your file.'}, status=400)

    admin_user = request.user

    # -- Cache all lookups --
    cache = {
        'townships': {t.name.lower(): t for t in Township.objects.all()},
        'buildings': list(Building.objects.all()),
        'blocks': list(Block.objects.all()),
        'floors': list(Floor.objects.all()),
        'units': list(Unit.objects.all()),
        'emails': set(User.objects.values_list('email', flat=True)),
        'usernames': set(User.objects.values_list('username', flat=True)),
        'active_leases': {lease.unit_id: lease.tenant.email.lower() for lease in Lease.objects.filter(status='active').select_related('tenant') if lease.tenant}
    }

    for row_idx, row in enumerate(rows, start=2):  # row 1 = header
        row_result = {
            'row': row_idx,
            'status': 'failed',
            'name': '',
            'email': '',
            'reason': '',
            'warnings': [],
        }

        try:
            # ── Extract & validate required fields ─────────
            first_name = _clean_str(row.get('first_name'))
            last_name = _clean_str(row.get('last_name'))
            email = _clean_email(row.get('email'))
            phone_raw = row.get('phone', '')
            phone = _clean_phone(phone_raw)
            building_name = _clean_str(row.get('building_name'))
            unit_number = _clean_str(row.get('unit_number'))

            row_result['name'] = f"{first_name} {last_name}".strip()
            row_result['email'] = email or _clean_str(row.get('email'))

            if not first_name:
                raise ValueError('first_name is required')
            if not last_name:
                raise ValueError('last_name is required')
            if not email:
                raise ValueError(f"Invalid email: '{row.get('email', '')}'")
            if _clean_str(phone_raw) and not phone:
                raise ValueError(f"Invalid phone number: '{phone_raw}'. Must be 10–15 digits.")
            if not building_name:
                raise ValueError('building_name is required')
            if not unit_number:
                raise ValueError('unit_number is required')

            # ── Hierarchy fields (auto-default if missing) ─
            colony_name = _clean_str(row.get('colony_name')) or _clean_str(row.get('township_name'))
            block_name = _clean_str(row.get('block_name'), default='')
            wing_name = _clean_str(row.get('wing_name'), default='')
            floor_number_raw = _clean_str(row.get('floor_number'), default='')
            floor_number = _clean_int(floor_number_raw, default=None)
            city = _clean_str(row.get('city'), default='')
            state = _clean_str(row.get('state'), default='')
            country = _clean_str(row.get('country'), default='India')

            # In this codebase, wings are represented through a single Block record.
            block_identifier = _build_block_identifier(block_name, wing_name)

            # If any hierarchy/location values are missing in CSV, auto-fill defaults.
            floor_number = floor_number if floor_number is not None else 1

            existing_building = Building.objects.filter(name__iexact=building_name.strip()).first()
            if existing_building:
                city = city or _clean_str(existing_building.city, default='')
                state = state or _clean_str(existing_building.state, default='')
                country = country or _clean_str(existing_building.country, default='India')

            if colony_name:
                existing_township = Township.objects.filter(name__iexact=colony_name).first()
                if existing_township:
                    city = city or _clean_str(existing_township.city, default='')
                    state = state or _clean_str(existing_township.state, default='')
                    country = country or _clean_str(existing_township.country, default='India')

            city = city or 'Unknown City'
            state = state or 'Unknown State'
            country = country or 'India'

            # ── Lease fields (optional; create lease only when valid) ──
            lease_start_raw = row.get('lease_start_date', '')
            lease_end_raw = row.get('lease_end_date', '')
            lease_start_date_val = _clean_date(lease_start_raw)
            lease_end_date_val = _clean_date(lease_end_raw)
            monthly_rent_val = _clean_decimal(row.get('monthly_rent'))
            security_deposit_val = _clean_decimal(row.get('security_deposit'))
            maintenance_charge_val = _clean_decimal(row.get('maintenance_charge'))

            has_any_lease_input = any([
                _clean_str(lease_start_raw),
                _clean_str(lease_end_raw),
                row.get('monthly_rent') not in (None, ''),
                row.get('security_deposit') not in (None, ''),
                row.get('maintenance_charge') not in (None, ''),
            ])

            should_create_lease = False
            if has_any_lease_input:
                if lease_start_date_val and lease_end_date_val and lease_end_date_val > lease_start_date_val:
                    should_create_lease = True
                else:
                    row_result['reason'] = (
                        'Lease not created for this row because lease dates are missing/invalid. '
                        'Resident and unit were still created.'
                    )

            # ── Optional unit specs ───────────────────────
            monthly_rent_unit = row.get('monthly_rent')  # also seeds unit's monthly_rent field
            bedrooms = row.get('bedrooms')
            bathrooms = row.get('bathrooms')
            square_feet = row.get('square_feet')

            with transaction.atomic():
                # 0. Colony / Township (optional)
                township, t_created = _get_or_create_township(
                    colony_name,
                    city=city,
                    state=state,
                    country=country,
                    cache=cache
                )
                if t_created and township and township.name not in results['created_colonies']:
                    results['created_colonies'].append(township.name)

                # Re-resolve/create building scoped by township if colony is provided.
                building, b_created = _get_or_create_building(
                    building_name,
                    township=township,
                    city=city,
                    state=state,
                    country=country,
                    cache=cache
                )
                if b_created and building.name not in results['created_buildings']:
                    results['created_buildings'].append(building.name)

                # 2. Wing/Block (stored as Block model)
                block, bl_created = _get_or_create_block(building, block_identifier, cache=cache)
                if bl_created:
                    results['created_blocks'].append(f"{building.name} / {block.name}")

                # 3. Floor
                floor_obj, fl_created = _get_or_create_floor(block, floor_number, cache=cache)
                if fl_created:
                    results['created_floors'].append(
                        f"{building.name} / {block.name} / Floor {floor_number}"
                    )

                # 4. Unit
                unit, u_created = _get_or_create_unit(
                    building=building,
                    block_name=block_identifier,
                    floor_number=floor_number,
                    unit_number=unit_number,
                    bedrooms=bedrooms,
                    bathrooms=bathrooms,
                    square_feet=square_feet,
                    monthly_rent=monthly_rent_unit,  # seed unit's monthly_rent field
                    floor_obj=floor_obj,
                    cache=cache
                )
                if u_created:
                    results['created_units'].append(f"{building.name} / {unit.unit_number}")

                # Check if unit is occupied by another resident
                if (not u_created) and unit.is_occupied:
                    # Check if the resident in this row is already the occupant
                    tenant_email = cache['active_leases'].get(unit.id)
                    if tenant_email and tenant_email == email.lower():
                        # Same resident, treat as skip
                        row_result['status'] = 'skipped'
                        row_result['reason'] = 'Resident already assigned to this unit'
                        results['skipped'] += 1
                        results['rows'].append(row_result)
                        continue
                    raise ValueError(
                        f"Unit '{unit_number}' in '{building_name}' is already occupied by another resident."
                    )

                # 5. Resident (User)
                validated = {
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'phone': phone or '',
                    'emergency_contact_name': _clean_str(row.get('emergency_contact_name')),
                    'emergency_contact_phone': _clean_str(row.get('emergency_contact_phone')),
                    'occupation': _clean_str(row.get('occupation')),
                    'date_of_birth': _clean_date(row.get('date_of_birth')),
                }
                user, create_status, skip_reason = _create_or_skip_resident(
                    admin_user, validated, unit, cache=cache
                )

                if create_status == 'skipped':
                    row_result['status'] = 'skipped'
                    row_result['reason'] = skip_reason
                    results['skipped'] += 1
                    results['rows'].append(row_result)
                    continue

                # 6. Mark unit occupied
                _mark_unit_occupied(unit, user)

                # 7. Lease (optional)
                created_lease = None
                if should_create_lease:
                    monthly_rent_for_lease = monthly_rent_val if monthly_rent_val is not None else _clean_decimal(unit.monthly_rent, Decimal('0'))
                    security_deposit_for_lease = security_deposit_val if security_deposit_val is not None else Decimal('0')
                    maintenance_charge_for_lease = maintenance_charge_val if maintenance_charge_val is not None else Decimal('0')

                    created_lease = _create_lease_direct(
                        admin_user, unit, user,
                        lease_start_date_val, lease_end_date_val,
                        monthly_rent_for_lease, security_deposit_for_lease, maintenance_charge_for_lease,
                    )

                # 8. Optional document import (PDF URL)
                try:
                    created_document = _create_unit_document(
                        admin_user=admin_user,
                        building=building,
                        unit=unit,
                        lease=created_lease,
                        row_data=row,
                    )
                    if created_document:
                        results['created_documents'].append(
                            f"{building.name} / {unit.unit_number} / {created_document.title}"
                        )
                except ValueError as doc_error:
                    # Do not fail resident creation for document URL/download issues.
                    row_result['warnings'].append(f"Document skipped: {doc_error}")
                except Exception as doc_error:
                    row_result['warnings'].append(f"Document skipped: unexpected error: {doc_error}")

            # ── Success ─────────────────────────────────────
            row_result['status'] = 'success'
            row_result['reason'] = row_result['reason'] or ''
            results['success'] += 1

        except ValueError as ve:
            row_result['status'] = 'failed'
            row_result['reason'] = str(ve)
            results['failed'] += 1
            logger.warning(f"[BulkUpload] Row {row_idx} validation error: {ve}")

        except Exception as exc:
            row_result['status'] = 'failed'
            row_result['reason'] = f"Unexpected error: {str(exc)}"
            results['failed'] += 1
            logger.error(f"[BulkUpload] Row {row_idx} unexpected error: {exc}", exc_info=True)

        results['rows'].append(row_result)

    # ── Activity log ─────────────────────────────────────────
    try:
        ActivityLog.objects.create(
            user=admin_user,
            action='bulk_upload_residents',
            description=(
                f"Bulk upload: {results['total']} rows — "
                f"{results['success']} created, {results['skipped']} skipped, {results['failed']} failed"
            ),
            metadata={
                'total': results['total'],
                'success': results['success'],
                'skipped': results['skipped'],
                'failed': results['failed'],
                'created_colonies': results['created_colonies'],
                'created_buildings': results['created_buildings'],
                'created_units': results['created_units'],
                'created_documents': results['created_documents'],
            }
        )
    except Exception:
        pass

    return Response(results, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# TEMPLATE DOWNLOAD: GET /api/auth/csv/template/
# ─────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_bulk_template(request):
    """
    Returns a demo CSV file with correct headers and example rows.
    """
    if not _is_authorized(request.user):
        return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="resident_bulk_upload_template.csv"'

    writer = csv.writer(response)

    # Header row — exactly what the bulk_upload_residents view expects
    writer.writerow([
        'first_name', 'last_name', 'email', 'phone',
        'colony_name', 'building_name', 'block_name', 'wing_name', 'floor_number', 'unit_number',
        'city', 'state', 'country',
        'bedrooms', 'bathrooms', 'square_feet',
        'emergency_contact_name', 'emergency_contact_phone',
        'lease_start_date', 'lease_end_date',
        'monthly_rent', 'security_deposit', 'maintenance_charge',
        'occupation', 'date_of_birth',
        'document_title', 'document_type', 'document_pdf_url', 'document_file_name',
    ])

    # Example rows
    example_rows = [
        [
            'Ravi', 'Kumar', 'ravi.kumar@example.com', '9876543210',
            'Sunflower Greens', 'Sunflower Towers', 'A', 'East Wing', '3', 'A-301',
            'Mumbai', 'Maharashtra', 'India',
            '2', '2.0', '950',
            'Sunita Kumar', '9876543211',
            '2024-01-01', '2024-12-31',
            '25000', '50000', '1000',
            'Software Engineer', '1990-06-15',
            'Rental Agreement - A-301', 'lease_agreement', 'https://example.com/docs/ravi-lease.pdf', 'ravi-lease.pdf',
        ],
        [
            'Priya', 'Sharma', 'priya.sharma@example.com', '9123456780',
            'Sunflower Greens', 'Sunflower Towers', 'B', 'West Wing', '5', 'B-501',
            'Mumbai', 'Maharashtra', 'India',
            '3', '2.5', '1200',
            'Ankit Sharma', '9123456781',
            '2024-02-01', '2025-01-31',
            '32000', '64000', '1500',
            'Doctor', '1985-03-22',
            'Insurance Policy - B-501', 'insurance', 'https://example.com/docs/priya-insurance.pdf', 'priya-insurance.pdf',
        ],
        [
            'Arjun', 'Mehta', 'arjun.mehta@example.com', '8800001234',
            'Green Valley Estate', 'Green Valley Residency', 'C', '', '1', 'C-102',
            'Pune', 'Maharashtra', 'India',
            '1', '1.0', '600',
            '', '',
            '2024-03-01', '2025-02-28',
            '18000', '36000', '500',
            'Student', '2000-11-01',
            '', '', '', '',
        ],
    ]

    for row in example_rows:
        writer.writerow(row)

    return response
