# payments/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.db import connection
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import HttpResponse
from django.conf import settings
from django_filters.rest_framework import DjangoFilterBackend
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from datetime import timedelta
from decimal import Decimal
from accounts.models import User
from accounts.permissions import ModulePermissionMixin, HasModulePermission
from accounts.email_service import EmailService
from notifications.services import NotificationService
from properties.models import Unit
from .models import AutoPayEnrollment, AutoPaymentLog, RecurringInvoice
from .serializers import (
    AutoPayEnrollmentSerializer, AutoPayEnrollmentCreateSerializer,
    AutoPaymentLogSerializer, RecurringInvoiceSerializer
)

import json
import hmac
import hashlib
import logging

try:
    import stripe
except ImportError:
    stripe = None

# Razorpay support has been permanently removed

logger = logging.getLogger(__name__)

from .models import (
    PaymentGateway, Invoice, Payment, PaymentMethod, Refund,
    PaymentReminder, PaymentPlan, Installment, Transaction, RazorpayWebhookEvent
)
from .serializers import (
    PaymentGatewaySerializer, InvoiceSerializer, InvoiceCreateSerializer,
    PaymentSerializer, PaymentInitiateSerializer, PaymentMethodSerializer,
    RefundSerializer, PaymentReminderSerializer, PaymentPlanSerializer,
    InstallmentSerializer, TransactionSerializer,
    PaymentDashboardSerializer, RevenueStatisticsSerializer
)
from .services.stripe_service import StripeService
from .utils.fee_calculator import calculate_fee

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema


def get_platform_keys():
    """Retrieve the platform-level Stripe secret and publishable keys,
    falling back to the public schema PaymentGateway if settings are not set."""
    from django.conf import settings as django_settings
    platform_secret = getattr(django_settings, 'STRIPE_PLATFORM_SECRET_KEY', None) or getattr(django_settings, 'STRIPE_SECRET_KEY', None)
    platform_pub = getattr(django_settings, 'STRIPE_PLATFORM_PUBLISHABLE_KEY', None) or getattr(django_settings, 'STRIPE_PUBLISHABLE_KEY', None)
    
    if not platform_secret or not platform_pub:
        from django_tenants.utils import schema_context
        from payments.models import PaymentGateway
        with schema_context('public'):
            gw = PaymentGateway.objects.filter(gateway_type='stripe').first()
            if gw:
                if not platform_secret:
                    platform_secret = gw.secret_key
                if not platform_pub:
                    platform_pub = gw.public_key
    return platform_secret, platform_pub

class PaymentGatewayViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'payments'
    queryset = PaymentGateway.objects.all()
    serializer_class = PaymentGatewaySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['gateway_type', 'is_active']
    
    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        gateway = self.get_object()
        
        if gateway.gateway_type == 'razorpay':
            return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
        elif gateway.gateway_type == 'stripe':
            service = StripeService(gateway)
            result = service.test_connection()
        else:
            return Response({'error': 'Gateway not supported'}, status=status.HTTP_400_BAD_REQUEST)

        
        return Response(result)


class InvoiceViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'payments'
    
    def _base_invoice_qs(self):
        from django.db.models import Prefetch
        from .models import Payment
        return Invoice.objects.all().select_related(
            'user', 'created_by', 'maintenance_request',
            'maintenance_request__unit', 'maintenance_request__unit__building',
            'owner_user', 'responsible_user',
            'transfer_requested_by', 'transfer_reviewed_by',
        ).prefetch_related(
            Prefetch(
                'payments',
                queryset=Payment.objects.filter(status='completed').select_related('user').order_by('-completed_at', '-created_at'),
                to_attr='completed_payments_prefetched'
            )
        )

    def get_queryset(self):
        qs = self._base_invoice_qs()
        user = self.request.user
        if not user or not user.is_authenticated:
            return qs.none()

        if user.role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin'):
            return qs

        if user.role == 'owner':
            legacy_owner_q = Q()
            legacy_owner_q |= Q(maintenance_request__unit__owner_user=user)
            legacy_owner_q |= Q(maintenance_request__unit__owner_email__iexact=getattr(user, 'email', ''))
            legacy_owner_q |= Q(transfer_status='requested', maintenance_request__unit__owner_user=user)

            owner_units = Unit.objects.select_related('building').filter(
                Q(owner_user=user) |
                Q(owner_email__iexact=getattr(user, 'email', ''))
            )
            owner_unit_q = Q()
            for unit in owner_units:
                building_name = getattr(getattr(unit, 'building', None), 'name', '')
                unit_number = unit.unit_number
                if building_name and unit_number:
                    owner_unit_q |= Q(
                        building__iexact=building_name,
                        unit_number__iexact=unit_number,
                    )
            return qs.filter(
                Q(user=user) |
                Q(owner_user=user) |
                Q(owner_email__iexact=getattr(user, 'email', '')) |
                Q(responsible_user=user) |
                legacy_owner_q |
                owner_unit_q
            ).distinct()

        if user.role == 'facility_manager':
            from accounts.fm_scope import get_fm_building_names
            building_names = list(get_fm_building_names(user) or [])
            if not building_names:
                return qs.none()
            return qs.filter(building__in=building_names)

        return qs.filter(user=user)

    def get_permissions(self):
        """
        Facility managers can generate and edit invoices from the manager portal even when
        dynamic role-permission seeds are missing `payments.create` or `payments.update`.
        """
        if self.action in ['create', 'update', 'partial_update']:
            user = getattr(self.request, 'user', None)
            role = getattr(user, 'role', None)
            if role in ['master_admin', 'masteradmin', 'super_admin', 'superadmin', 'facility_manager']:
                return [permissions.IsAuthenticated()]
        return super().get_permissions()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return InvoiceCreateSerializer
        return InvoiceSerializer

    def _resolve_invoice_owner(self, invoice):
        unit = None
        if getattr(invoice, 'maintenance_request', None):
            unit = getattr(invoice.maintenance_request, 'unit', None)

        if not unit and getattr(invoice, 'building', None) and getattr(invoice, 'unit_number', None):
            unit = Unit.objects.select_related('owner_user', 'building').filter(
                building__name__iexact=str(invoice.building).strip(),
                unit_number__iexact=str(invoice.unit_number).strip(),
            ).first()

        owner_user = getattr(invoice, 'owner_user', None)
        if owner_user:
            return owner_user

        if unit:
            unit_owner = getattr(unit, 'owner_user', None)
            if unit_owner:
                return unit_owner
            owner_email = getattr(unit, 'owner_email', '') or ''
            if owner_email:
                return User.objects.filter(email__iexact=owner_email).first()

        owner_email = getattr(invoice, 'owner_email', '') or ''
        if owner_email:
            return User.objects.filter(email__iexact=owner_email).first()

    def filter_queryset(self, queryset):
        """Override to support multi-status and unit_number case-insensitive filtering."""
        queryset = super().filter_queryset(queryset)
        
        # Support comma-separated status values: ?status=sent,draft,viewed
        status_param = self.request.query_params.get('status', '')
        if status_param and ',' in status_param:
            statuses = [s.strip() for s in status_param.split(',') if s.strip()]
            queryset = queryset.filter(status__in=statuses)
        
        # Support case-insensitive unit_number filter
        unit_number_param = self.request.query_params.get('unit_number', '')
        if unit_number_param:
            queryset = queryset.filter(unit_number__iexact=unit_number_param)
        
        return queryset

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        invoice = self.get_object()
        
        if invoice.status == 'draft':
            invoice.status = 'sent'
            invoice.sent_at = timezone.now()
            invoice.save()
            
            # Send email notification
            try:
                EmailService.send_email(
                    to_email=invoice.user.email,
                    subject=f'Invoice {invoice.invoice_number} from HOAConnect',
                    template_name='invoice_sent',
                    context={
                        'user': invoice.user,
                        'invoice': invoice,
                        'invoice_number': invoice.invoice_number,
                        'amount_due': invoice.amount_due,
                        'due_date': invoice.due_date,
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send invoice email for {invoice.invoice_number}: {str(e)}")

            return Response({'message': 'Invoice sent successfully'})
        
        return Response({'error': 'Invoice already sent'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='bulk-generate')
    def bulk_generate(self, request):
        """
        Generate invoices in bulk for amenities, parking, utilities, or maintenance.
        Idempotent: prevents duplicate invoices for the same item/month.
        Supports dry-run.

        OPTIMIZED:
        - Prefetch existing invoice fingerprints into a Python set (N SELECT → 1 SELECT).
        - Collect Invoice objects in a list and bulk_create at end (N INSERT → 1 INSERT).
        - misc_other: prefetch active leases in one query instead of N per unit.
        """
        user = request.user
        user_role = getattr(user, 'role', None)
        ALLOWED_ROLES = ('facility_manager', 'master_admin', 'masteradmin', 'super_admin', 'superadmin')
        if user_role not in ALLOWED_ROLES:
            return Response({'error': 'Only facility managers or master admins can perform this action'}, status=status.HTTP_403_FORBIDDEN)

        invoice_type = request.data.get('invoice_type')
        dry_run = request.data.get('dry_run', False)
        billing_month = request.data.get('billing_month')
        billing_year = request.data.get('billing_year')
        issue_date_str = request.data.get('issue_date')
        due_date_str = request.data.get('due_date')
        target_city = request.data.get('target_city')
        target_building = request.data.get('target_building')
        target_block = request.data.get('target_block')
        target_unit_number = request.data.get('target_unit_number')

        if not all([invoice_type, billing_month, billing_year, issue_date_str]):
            return Response({'error': 'invoice_type, billing_month, billing_year, issue_date are required'}, status=400)

        try:
            billing_month = int(billing_month)
            billing_year = int(billing_year)
            from datetime import datetime, timedelta
            issue_date = datetime.strptime(issue_date_str, '%Y-%m-%d').date()
            if due_date_str:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            else:
                from tenants.models import TenantSettings
                settings = TenantSettings.objects.first()
                due_days = settings.payment_due_days if settings else 5
                due_date = issue_date + timedelta(days=due_days)
        except ValueError:
            return Response({'error': 'Invalid date format or number'}, status=400)

        is_master = user_role in ('master_admin', 'masteradmin', 'super_admin', 'superadmin')
        if is_master:
            from properties.models import Building
            allowed_buildings = list(Building.objects.values_list('name', flat=True))
        else:
            from accounts.fm_scope import get_fm_building_names
            allowed_buildings = list(get_fm_building_names(user) or [])

        if not allowed_buildings:
            return Response({'error': 'No properties found'}, status=403)

        if target_building and target_building != 'all':
            if is_master or target_building in allowed_buildings:
                allowed_buildings = [target_building]
            else:
                return Response({'error': 'You do not have permission for this building'}, status=403)
        elif target_city and target_city != 'all':
            from properties.models import Building
            city_buildings = list(Building.objects.filter(city__iexact=target_city).values_list('name', flat=True))
            allowed_buildings = [b for b in allowed_buildings if b in city_buildings]

        filter_user_ids = None

        if target_unit_number and target_unit_number != 'all':
            from properties.models import Unit, Lease
            unit_qs = Unit.objects.filter(unit_number__iexact=target_unit_number, building__name__in=allowed_buildings)
            owner_ids = list(unit_qs.values_list('owner_user', flat=True))
            tenant_ids = list(Lease.objects.filter(unit__in=unit_qs, status='active').values_list('tenant', flat=True))
            filter_user_ids = set(filter(None, owner_ids + tenant_ids))
        elif target_block and target_block != 'all':
            from properties.models import Unit, Lease
            unit_qs = Unit.objects.filter(block__iexact=target_block, building__name__in=allowed_buildings)
            owner_ids = list(unit_qs.values_list('owner_user', flat=True))
            tenant_ids = list(Lease.objects.filter(unit__in=unit_qs, status='active').values_list('tenant', flat=True))
            filter_user_ids = set(filter(None, owner_ids + tenant_ids))

        from django.db import transaction
        from django.db.models import Q

        generated_count = 0

        with transaction.atomic():
            # ── OPTIMIZATION: Collect Invoice objects in a list ──────────────────────
            invoices_to_create = []
            
            from datetime import datetime, timedelta
            date_str = datetime.now().strftime('%Y%m')
            inv_prefix = f'INV-{date_str}-'
            last_invoice = Invoice.objects.filter(
                invoice_number__startswith=inv_prefix
            ).order_by('-invoice_number').values_list('invoice_number', flat=True).first()
            if last_invoice:
                try:
                    invoice_counter = int(last_invoice.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    invoice_counter = Invoice.objects.filter(invoice_number__startswith=inv_prefix).count() + 1
            else:
                invoice_counter = 1
            inv_expires_at = timezone.now() + timedelta(hours=124)

            if invoice_type == 'amenity_fee':
                from amenities.models import AmenityBooking
                q = Q(payment_status__in=['pending', 'unpaid'], created_at__year=billing_year, created_at__month=billing_month, booked_by__building_name__in=allowed_buildings)
                if filter_user_ids is not None:
                    q &= Q(booked_by__in=filter_user_ids)
                bookings = AmenityBooking.objects.filter(q).select_related('booked_by', 'amenity')

                # OPTIMIZATION: Prefetch all existing fingerprints in 1 query → Python set
                existing_keys = set(
                    Invoice.objects.filter(
                        invoice_type='amenity_fee',
                        billing_month=billing_month,
                        billing_year=billing_year,
                    ).values_list('user_id', 'notes')
                )

                for b in bookings:
                    if getattr(b, 'total_amount', b.booking_fee) <= 0:
                        continue
                    fingerprint_note = f"Booking #{b.booking_number}"
                    # OPTIMIZATION: Check Python set instead of hitting DB per booking
                    if not any(uid == b.booked_by_id and fingerprint_note in (note or '') for uid, note in existing_keys):
                        generated_count += 1
                        if not dry_run:
                            resident_building = getattr(b.booked_by, 'building_name', '')
                            invoices_to_create.append(Invoice(
                                invoice_number=f'{inv_prefix}{invoice_counter:05d}',
                                user=b.booked_by,
                                invoice_type='amenity_fee',
                                building=resident_building or b.amenity.building or "",
                                unit_number=getattr(b.booked_by, 'unit_number', '') or "",
                                subtotal=getattr(b, 'total_amount', b.booking_fee),
                                total_amount=getattr(b, 'total_amount', b.booking_fee),
                                amount_due=getattr(b, 'total_amount', b.booking_fee),
                                issue_date=issue_date,
                                due_date=due_date,
                                billing_month=billing_month,
                                billing_year=billing_year,
                                description=f"Amenity Booking Fee: {b.amenity.name}",
                                notes=fingerprint_note,
                                created_by=user,
                                status='sent',
                                expires_at=inv_expires_at
                            ))
                            invoice_counter += 1

            elif invoice_type == 'parking_fee':
                from parking.models import ParkingSlot
                q = Q(assigned_to__isnull=False, building__in=allowed_buildings, monthly_fee__gt=0)
                if filter_user_ids is not None:
                    q &= Q(assigned_to__in=filter_user_ids)
                slots = ParkingSlot.objects.filter(q).select_related('assigned_to')

                # OPTIMIZATION: Prefetch existing parking fingerprints in 1 query
                existing_keys = set(
                    Invoice.objects.filter(
                        invoice_type='parking_fee',
                        billing_month=billing_month,
                        billing_year=billing_year,
                    ).values_list('user_id', 'notes')
                )

                for s in slots:
                    fingerprint_note = f"Slot #{s.slot_number}"
                    if not any(uid == s.assigned_to_id and fingerprint_note in (note or '') for uid, note in existing_keys):
                        generated_count += 1
                        if not dry_run:
                            invoices_to_create.append(Invoice(
                                invoice_number=f'{inv_prefix}{invoice_counter:05d}',
                                user=s.assigned_to,
                                invoice_type='parking_fee',
                                building=s.building or "",
                                unit_number='',
                                subtotal=s.monthly_fee,
                                total_amount=s.monthly_fee,
                                amount_due=s.monthly_fee,
                                issue_date=issue_date,
                                due_date=due_date,
                                billing_month=billing_month,
                                billing_year=billing_year,
                                description=f"Parking Fee for Slot {s.slot_number}",
                                notes=fingerprint_note,
                                created_by=user,
                                status='sent',
                                expires_at=inv_expires_at
                            ))
                            invoice_counter += 1

            elif invoice_type == 'utility':
                from utilities.models import UtilityBill
                q = Q(invoiced=False, billing_period_start__year=billing_year, billing_period_start__month=billing_month, unit__building__name__in=allowed_buildings)
                if target_block and target_block != 'all':
                    q &= Q(unit__block__iexact=target_block)
                bills = UtilityBill.objects.filter(q).select_related('unit__building', 'unit__owner_user', 'utility_type')

                # OPTIMIZATION: Prefetch existing utility fingerprints in 1 query
                existing_keys = set(
                    Invoice.objects.filter(
                        invoice_type='utility',
                        billing_month=billing_month,
                        billing_year=billing_year,
                    ).values_list('user_id', 'notes')
                )

                bills_to_mark_invoiced = []
                for b in bills:
                    target_user = getattr(b, 'tenant', None)
                    if not target_user:
                        target_user = getattr(b.unit, 'owner_user', None)
                    if not target_user:
                        continue
                    fingerprint_note = f"Bill #{b.bill_number}"
                    if not any(uid == target_user.id and fingerprint_note in (note or '') for uid, note in existing_keys):
                        generated_count += 1
                        if not dry_run:
                            invoices_to_create.append(Invoice(
                                invoice_number=f'{inv_prefix}{invoice_counter:05d}',
                                user=target_user,
                                invoice_type='utility',
                                building=b.unit.building.name if b.unit and b.unit.building else "",
                                unit_number=b.unit.unit_number or "",
                                subtotal=b.total_amount,
                                total_amount=b.total_amount,
                                amount_due=b.total_amount,
                                issue_date=issue_date,
                                due_date=due_date,
                                billing_month=billing_month,
                                billing_year=billing_year,
                                description=f"{b.get_utility_type_display()} Bill",
                                notes=fingerprint_note,
                                created_by=user,
                                status='sent',
                                expires_at=inv_expires_at
                            ))
                            invoice_counter += 1
                            bills_to_mark_invoiced.append(b)

                # OPTIMIZATION: Bulk update utility bills (N UPDATE → 1 UPDATE)
                if bills_to_mark_invoiced:
                    UtilityBill.objects.filter(
                        id__in=[b.id for b in bills_to_mark_invoiced]
                    ).update(invoiced=True)

            elif invoice_type == 'maintenance_fee':
                from maintenance.models import MaintenanceRequest
                q = Q(invoiced=False, status='completed', request_type='personal', building__in=allowed_buildings)
                if filter_user_ids is not None:
                    q &= Q(requested_by__in=filter_user_ids)
                reqs = MaintenanceRequest.objects.filter(q).select_related('requested_by')

                # OPTIMIZATION: Prefetch existing maintenance fingerprints in 1 query
                existing_keys = set(
                    Invoice.objects.filter(
                        invoice_type='maintenance_fee',
                        billing_month=billing_month,
                        billing_year=billing_year,
                    ).values_list('user_id', 'notes')
                )

                reqs_to_mark_invoiced = []
                for r in reqs:
                    cost = r.total_cost if getattr(r, 'total_cost', 0) > 0 else 500
                    target_user = r.requested_by
                    if not target_user:
                        continue
                    fingerprint_note = f"Req #{r.request_number}"
                    if not any(uid == target_user.id and fingerprint_note in (note or '') for uid, note in existing_keys):
                        generated_count += 1
                        if not dry_run:
                            invoices_to_create.append(Invoice(
                                invoice_number=f'{inv_prefix}{invoice_counter:05d}',
                                user=target_user,
                                invoice_type='maintenance_fee',
                                building=r.building or "",
                                unit_number=r.unit_number or "",
                                maintenance_request=r,
                                subtotal=cost,
                                total_amount=cost,
                                amount_due=cost,
                                issue_date=issue_date,
                                due_date=due_date,
                                billing_month=billing_month,
                                billing_year=billing_year,
                                description=f"Maintenance Charge: {r.title}",
                                notes=fingerprint_note,
                                created_by=user,
                                status='sent',
                                expires_at=inv_expires_at
                            ))
                            invoice_counter += 1
                            reqs_to_mark_invoiced.append(r)

                # OPTIMIZATION: Bulk update maintenance requests (N UPDATE → 1 UPDATE)
                if reqs_to_mark_invoiced:
                    MaintenanceRequest.objects.filter(
                        id__in=[r.id for r in reqs_to_mark_invoiced]
                    ).update(invoiced=True)

            elif invoice_type == 'misc_other':
                from decimal import Decimal
                from properties.models import Unit, Lease
                misc_description = request.data.get('misc_description', 'Misc Charge')
                misc_amount_raw = request.data.get('misc_amount', 0)
                try:
                    misc_amount = Decimal(str(misc_amount_raw))
                except Exception:
                    return Response({'error': 'Invalid misc_amount'}, status=400)

                if misc_amount <= 0:
                    return Response({'error': 'misc_amount must be greater than 0'}, status=400)

                unit_qs = Unit.objects.filter(building__name__in=allowed_buildings).select_related('building', 'owner_user')
                if filter_user_ids is not None:
                    unit_qs = unit_qs.filter(
                        Q(owner_user__in=filter_user_ids) |
                        Q(leases__tenant__in=filter_user_ids, leases__status='active')
                    ).distinct()

                # OPTIMIZATION: Prefetch all active leases for all units in 1 query
                all_unit_ids = list(unit_qs.values_list('id', flat=True))
                active_leases_map = {
                    lease.unit_id: lease.tenant
                    for lease in Lease.objects.filter(unit_id__in=all_unit_ids, status='active').select_related('tenant')
                }

                for unit in unit_qs:
                    resident = active_leases_map.get(unit.id) or unit.owner_user
                    if not resident:
                        continue
                    generated_count += 1
                    if not dry_run:
                        invoices_to_create.append(Invoice(
                            invoice_number=f'{inv_prefix}{invoice_counter:05d}',
                            user=resident,
                            invoice_type='other',
                            building=unit.building.name if unit.building else '',
                            unit_number=unit.unit_number or '',
                            subtotal=misc_amount,
                            tax_amount=Decimal('0.00'),
                            late_fee=Decimal('0.00'),
                            discount_amount=Decimal('0.00'),
                            amount_paid=Decimal('0.00'),
                            total_amount=misc_amount,
                            amount_due=misc_amount,
                            issue_date=issue_date,
                            due_date=due_date,
                            billing_month=billing_month,
                            billing_year=billing_year,
                            description=misc_description,
                            notes=f'Misc/Other charge generated by {user.get_full_name() or user.email}',
                            created_by=user,
                            status='sent',
                            expires_at=inv_expires_at
                        ))
                        invoice_counter += 1
            else:
                return Response({'error': f"Unsupported invoice_type for bulk generation: {invoice_type}"}, status=400)

            if dry_run:
                transaction.set_rollback(True)
                return Response({
                    'message': f"Dry run successful. {generated_count} invoices would be generated.",
                    'count': generated_count,
                    'dry_run': True
                })

            # ── OPTIMIZATION: 1 bulk INSERT instead of N individual INSERTs ────────
            if invoices_to_create:
                Invoice.objects.bulk_create(invoices_to_create)

        return Response({
            'message': f"Successfully generated {generated_count} invoices.",
            'count': generated_count,
            'dry_run': False
        })


    @action(detail=False, methods=['get'])
    def backup(self, request):
        """Export all invoices as JSON for backup"""
        invoices = self.get_queryset()
        serializer = self.get_serializer(invoices, many=True)
        response = Response(serializer.data)
        response['Content-Disposition'] = f'attachment; filename="invoices_backup_{timezone.now().strftime("%Y%m%d_%H%M")}.json"'
        return response

    @action(detail=True, methods=['post'])
    def resend(self, request, pk=None):
        """Resend invoice email to the user"""
        invoice = self.get_object()
        try:
            EmailService.send_email(
                to_email=invoice.user.email,
                subject=f'Resent: Invoice {invoice.invoice_number} from HOAConnect',
                template_name='invoice_sent',
                context={
                    'user': invoice.user,
                    'invoice': invoice,
                    'invoice_number': invoice.invoice_number,
                    'amount_due': invoice.amount_due,
                    'due_date': invoice.due_date,
                }
            )
            return Response({'message': 'Invoice email resent successfully'})
        except Exception as e:
            return Response({'error': f'Failed to resend email: {str(e)}'}, status=400)

    @action(detail=True, methods=['post'])
    def regenerate(self, request, pk=None):
        """Regenerate invoice with a fresh 124-hour payment window"""
        invoice = self.get_object()
        # invoice.expires_at = timezone.now() + timedelta(hours=124)
        invoice.status = 'sent'
        invoice.save(update_fields=['status', 'updated_at'])
        return Response({
            'message': 'Invoice regenerated with new 124-hour payment window',
            # 'expires_at': invoice.expires_at
        })

    @action(detail=True, methods=['post'])
    def expire(self, request, pk=None):
        """Manually mark an invoice as expired"""
        invoice = self.get_object()
        invoice.status = 'expired'
        invoice.save(update_fields=['status', 'updated_at'])
        return Response({'message': 'Invoice marked as expired'})

    @action(detail=True, methods=['post'], url_path='verify-payment')
    def verify_payment(self, request, pk=None):
        """Manually verify a payment for an invoice (Admin action)"""
        invoice = self.get_object()
        remarks = request.data.get('remarks', 'Manual verification by admin')
        
        invoice.status = 'paid'
        invoice.paid_at = timezone.now()
        invoice.amount_paid = invoice.total_amount
        invoice.amount_due = 0
        invoice.notes = (invoice.notes + f"\n[Verified: {remarks}]") if invoice.notes else f"[Verified: {remarks}]"
        invoice.save()

        # Send manual payment receipt email
        try:
            EmailService.send_email(
                to_email=invoice.user.email,
                subject=f'Payment Receipt - {invoice.invoice_number}',
                template_name='payment_receipt',
                context={
                    'user': invoice.user,
                    'message': f"We have successfully verified your manual payment of ₹{invoice.total_amount} for {invoice.description or 'your invoice'}.",
                    'amount': invoice.total_amount,
                    'transaction_id': f"MANUAL-{invoice.id}",
                    'date': invoice.paid_at.strftime('%B %d, %Y'),
                    'domain': getattr(settings, 'FRONTEND_DOMAIN', 'hoaconnecthub.com')
                }
            )
            logger.info(f"Manual Payment receipt sent to {invoice.user.email}")
        except Exception as email_err:
            logger.warning(f"Failed to send manual payment receipt to {invoice.user.email}: {email_err}")
        
        return Response({'message': 'Payment verified successfully'})

    @action(detail=True, methods=['post'], url_path='reject-payment')
    def reject_payment(self, request, pk=None):
        """Reject a pending payment and return invoice to sent status"""
        invoice = self.get_object()
        reason = request.data.get('reason', 'Payment rejected by admin')
        
        invoice.status = 'sent'
        invoice.notes = (invoice.notes + f"\n[Rejected: {reason}]") if invoice.notes else f"[Rejected: {reason}]"
        invoice.save()
        
        return Response({'message': 'Payment rejected successfully'})

    @action(detail=False, methods=['delete'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """Delete all invoices (Super Admin only)"""
        count = Invoice.objects.all().count()
        Invoice.objects.all().delete()
        return Response({'message': f'Successfully deleted {count} invoices'}, status=status.HTTP_200_OK)
        
    @action(detail=False, methods=['post'])
    def consolidate(self, request):
        invoice_ids = request.data.get('invoice_ids', [])
        if not invoice_ids:
            return Response({'error': 'No invoices provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        invoices = Invoice.objects.filter(
            id__in=invoice_ids, 
            user=request.user, 
            status__in=['draft', 'sent', 'viewed', 'partially_paid', 'overdue']
        )
        if not invoices.exists():
            return Response({'error': 'Valid active invoices not found'}, status=status.HTTP_404_NOT_FOUND)
            
        first = invoices.first()
        subtotal = sum(i.amount_due for i in invoices)
        if subtotal <= 0:
            return Response({'error': 'Selected invoices have no amount due'}, status=status.HTTP_400_BAD_REQUEST)

        # construct line items
        line_items = []
        for i in invoices:
            desc = i.description or i.get_invoice_type_display()
            line_items.append({
                "description": f"{desc} ({i.invoice_number})",
                "amount": float(i.amount_due),
                "original_invoice_id": str(i.id)
            })
            
        from decimal import Decimal
        from django.utils import timezone
        from datetime import timedelta
        from tenants.models import TenantSettings
        
        settings = TenantSettings.objects.first()
        due_days = settings.payment_due_days if settings else 5
        due_date_val = timezone.now().date() + timedelta(days=due_days)
        
        new_invoice = Invoice.objects.create(
            user=request.user,
            invoice_type='other',
            building=first.building,
            unit_number=first.unit_number,
            subtotal=subtotal,
            tax_amount=Decimal('0.00'),
            late_fee=Decimal('0.00'),
            discount_amount=Decimal('0.00'),
            amount_paid=Decimal('0.00'),
            total_amount=subtotal,
            amount_due=subtotal,
            issue_date=timezone.now().date(),
            due_date=due_date_val,
            status='sent',
            description='Consolidated Payment Invoice',
            notes="Consolidation of multiple pending invoices into one payment.",
            line_items=line_items
        )
        
        # OPTIMIZATION: Replace N individual i.save() calls with 1 bulk_update
        # BEFORE: for i in invoices: i.status='cancelled'; i.save()  -> N UPDATE queries
        # AFTER:  bulk_update on a list -> 1 UPDATE query
        invoices_list = list(invoices)
        new_note_suffix = f"\n[Consolidated into {new_invoice.invoice_number}]"
        for i in invoices_list:
            i.status = 'cancelled'
            i.notes = (i.notes + new_note_suffix) if i.notes else f"[Consolidated into {new_invoice.invoice_number}]"
        Invoice.objects.bulk_update(invoices_list, ['status', 'notes', 'updated_at'])

        serializer = self.get_serializer(new_invoice)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
        
    @action(detail=False, methods=['post'], url_path='targeted-billing')
    def targeted_billing(self, request):
        """
        Record payments for selected invoices or generate a consolidated bill for a specific unit.
        Allows adjusting invoice amounts, and adding a 'misc_item'.
        """
        from decimal import Decimal
        from django.utils import timezone
        from datetime import timedelta
        from tenants.models import TenantSettings
        
        settings = TenantSettings.objects.first()
        due_days = settings.payment_due_days if settings else 5
        due_date_val = timezone.now().date() + timedelta(days=due_days)
        target_building = request.data.get('target_building')
        target_unit_number = request.data.get('target_unit_number')
        mark_as_paid = request.data.get('mark_as_paid', False)
        
        selected_invoices_data = request.data.get('selected_invoices', [])
        misc_item = request.data.get('misc_item')
        
        if not selected_invoices_data and not misc_item:
            return Response({'error': 'No invoices selected and no misc item provided'}, status=400)
            
        invoices_to_process = []
        target_user = None
        
        # 1. Update existing invoices
        for inv_data in selected_invoices_data:
            inv = Invoice.objects.filter(id=inv_data['id']).first()
            if inv:
                if not target_user:
                    target_user = inv.user
                if not target_building:
                    target_building = inv.building
                if not target_unit_number:
                    target_unit_number = inv.unit_number
                    
                adjusted_amount = Decimal(str(inv_data.get('adjusted_amount', inv.amount_due)))
                if adjusted_amount != inv.amount_due:
                    inv.amount_due = adjusted_amount
                    inv.subtotal = adjusted_amount
                    inv.total_amount = adjusted_amount
                    inv.save(update_fields=['amount_due', 'subtotal', 'total_amount'])
                invoices_to_process.append(inv)
                
        # 2. Handle Misc Item
        misc_invoice = None
        if misc_item and misc_item.get('amount') and float(misc_item.get('amount')) > 0:
            if not target_user:
                # Find user from unit
                from properties.models import Unit, Lease
                unit = Unit.objects.filter(building__name=target_building, unit_number=target_unit_number).first()
                if unit:
                    lease = Lease.objects.filter(unit=unit, status='active').first()
                    target_user = lease.tenant if lease else unit.owner_user
            
            if not target_user:
                return Response({'error': 'Could not determine user for the target unit'}, status=400)
                
            amount = Decimal(str(misc_item['amount']))
            misc_invoice = Invoice.objects.create(
                user=target_user,
                invoice_type='other',
                building=target_building or '',
                unit_number=target_unit_number or '',
                subtotal=amount,
                tax_amount=Decimal('0.00'),
                late_fee=Decimal('0.00'),
                discount_amount=Decimal('0.00'),
                amount_paid=Decimal('0.00'),
                total_amount=amount,
                amount_due=amount,
                issue_date=timezone.now().date(),
                due_date=due_date_val,
                status='sent',
                description=misc_item.get('description', 'Misc Charge'),
                line_items=[{
                    "description": misc_item.get('description', 'Misc Charge'),
                    "quantity": misc_item.get('qty', 1),
                    "unit_price": misc_item.get('unit_price', float(amount)),
                    "amount": float(amount)
                }]
            )
            invoices_to_process.append(misc_invoice)
            
        # 3. Process according to mark_as_paid
        if mark_as_paid:
            for inv in invoices_to_process:
                inv.status = 'paid'
                inv.paid_at = timezone.now()
                inv.amount_paid = inv.total_amount
                inv.amount_due = 0
                inv.notes = (inv.notes + f"\n[Targeted Billing: Marked Paid]") if inv.notes else "[Targeted Billing: Marked Paid]"
                inv.save()
            return Response({'message': f'Successfully recorded payment for {len(invoices_to_process)} invoice(s)'})
        else:
            # Generate Consolidated Bill
            if len(invoices_to_process) == 1 and invoices_to_process[0] == misc_invoice:
                return Response({'message': 'Misc invoice generated successfully'})
                
            subtotal = sum(i.amount_due for i in invoices_to_process)
            line_items = []
            for i in invoices_to_process:
                desc = i.description or i.get_invoice_type_display()
                line_items.append({
                    "description": f"{desc} ({i.invoice_number})",
                    "quantity": 1,
                    "unit_price": float(i.amount_due),
                    "amount": float(i.amount_due),
                    "original_invoice_id": str(i.id)
                })
                
            consolidated_invoice = Invoice.objects.create(
                user=invoices_to_process[0].user,
                invoice_type='other',
                building=invoices_to_process[0].building,
                unit_number=invoices_to_process[0].unit_number,
                subtotal=subtotal,
                tax_amount=Decimal('0.00'),
                late_fee=Decimal('0.00'),
                discount_amount=Decimal('0.00'),
                amount_paid=Decimal('0.00'),
                total_amount=subtotal,
                amount_due=subtotal,
                issue_date=timezone.now().date(),
                due_date=due_date_val,
                status='sent',
                description='Consolidated Bill',
                notes="Consolidation of multiple invoices.",
                line_items=line_items
            )
            
            # OPTIMIZATION: Replace N individual i.save() calls with 1 bulk_update
            # BEFORE: for i in invoices_to_process: i.save()  -> N UPDATE queries
            # AFTER:  bulk_update -> 1 UPDATE query
            for i in invoices_to_process:
                i.status = 'cancelled'
                i.notes = (i.notes + f"\n[Consolidated into {consolidated_invoice.invoice_number}]") if i.notes else f"[Consolidated into {consolidated_invoice.invoice_number}]"
            Invoice.objects.bulk_update(invoices_to_process, ['status', 'notes', 'updated_at'])

            return Response({'message': f'Successfully generated consolidated bill: {consolidated_invoice.invoice_number}'})
    
    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        invoice = self.get_object()

        import io
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageTemplate, BaseDocTemplate, Frame, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

        buffer = io.BytesIO()

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('Helvetica', 9)
            canvas.setFillColor(colors.HexColor('#666666'))
            # Line
            canvas.setStrokeColor(colors.HexColor('#CCCCCC'))
            canvas.line(0.75 * inch, 0.75 * inch + 15, letter[0] - 0.75 * inch, 0.75 * inch + 15)
            # Text
            page_num = f"Page {doc.page} of 1"
            canvas.drawCentredString(letter[0]/2.0, 0.75 * inch, page_num)
            canvas.drawCentredString(letter[0]/2.0, 0.75 * inch - 14, "Powered by HOA Connect Hub")
            canvas.restoreState()

        class InvoiceDocTemplate(BaseDocTemplate):
            def __init__(self, filename, **kw):
                super().__init__(filename, **kw)
                frame = Frame(0.75 * inch, 1.2 * inch, letter[0] - 1.5 * inch, letter[1] - 2 * inch, id='F1')
                template = PageTemplate('normal', [frame], onPage=footer)
                self.addPageTemplates(template)

        doc = InvoiceDocTemplate(buffer, pagesize=letter,
                                rightMargin=0.75 * inch, leftMargin=0.75 * inch,
                                topMargin=0.75 * inch, bottomMargin=1.5 * inch)
                                
        styles = getSampleStyleSheet()
        
        # Styles
        title_style = ParagraphStyle('InvoiceTitle', parent=styles['Title'], fontSize=28,
                                     spaceAfter=0, textColor=colors.HexColor('#2E5b7e'), alignment=TA_RIGHT, fontName='Helvetica-Bold')
        normal_style = styles['Normal']
        
        elements = []

        # Header Table: Logo (Left) and Title/Meta (Right)
        import os
        logo_path = os.path.join(os.path.dirname(__file__), 'logo.png')
        
        logo_elements = []
        if os.path.exists(logo_path):
            logo_elements.append(Image(logo_path, width=2.5*inch, height=1.0*inch, kind='proportional'))
        else:
            logo_style = ParagraphStyle('LogoStyle', parent=styles['Normal'], leading=16)
            logo_elements.append(Paragraph("<font size=28 color='#2E5b7e'><b>HOA</b></font><br/><font size=12 color='#333333'>Connect Hub</font>", logo_style))
            
        tenant = getattr(request, 'tenant', None)
        if tenant and hasattr(tenant, 'name'):
            org_name_style = ParagraphStyle(
                'OrgNameStyle', 
                parent=styles['Normal'], 
                fontSize=14, 
                textColor=colors.HexColor('#1A2A3A'), 
                fontName='Helvetica-Bold',
                spaceTop=8,
                spaceAfter=2
            )
            org_subtitle_style = ParagraphStyle(
                'OrgSubtitleStyle', 
                parent=styles['Normal'], 
                fontSize=9, 
                textColor=colors.HexColor('#666666'), 
                fontName='Helvetica'
            )
            logo_elements.append(Spacer(1, 8))
            logo_elements.append(Paragraph(f"{tenant.name}", org_name_style))
            # Also show address if available, or just a small subtitle
            address_lines = []
            if getattr(tenant, 'city', None):
                address_parts = [tenant.city]
                if getattr(tenant, 'state', None): address_parts.append(tenant.state)
                address_lines.append(", ".join(address_parts))
            
            ein = getattr(tenant, 'ein', None)
            if ein:
                address_lines.append(f"EIN: {ein}")
                
            sos_id = getattr(tenant, 'sos_id', None)
            if sos_id:
                address_lines.append(f"SOS ID: {sos_id}")
                
            if address_lines:
                logo_elements.append(Paragraph(" | ".join(address_lines), org_subtitle_style))
            
        left_table = Table([[e] for e in logo_elements], colWidths=[3.0 * inch])
        left_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ]))
        
        status_style = ParagraphStyle('StatusStyle', parent=styles['Normal'], alignment=TA_RIGHT)
        
        meta_data = [
            ['Invoice Number:', str(invoice.invoice_number)],
            ['Date:', str(invoice.issue_date)],
            ['Due Date:', str(invoice.due_date)],
            ['Status:', Paragraph(f"<font color='#2E7D32'>{invoice.get_status_display().title()}</font>", status_style)],
        ]
        
        meta_table = Table(meta_data, colWidths=[1.4 * inch, 1.5 * inch])
        meta_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
            ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#555555')),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BACKGROUND', (1,3), (1,3), colors.HexColor('#E8F5E9')), # Status background
        ]))
        
        right_table = Table([
            [Paragraph('INVOICE', title_style)],
            [Spacer(1, 10)],
            [meta_table]
        ], colWidths=[3.0 * inch])
        right_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        
        header_data = [[left_table, right_table]]
        header_table = Table(header_data, colWidths=[4.0 * inch, 3.0 * inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ]))
        
        elements.append(header_table)
        elements.append(Spacer(1, 20))
        
        # Horizontal Line
        line_table = Table([['']], colWidths=[7.0 * inch])
        line_table.setStyle(TableStyle([
            ('LINEABOVE', (0,0), (-1,-1), 2, colors.HexColor('#2E5b7e')),
        ]))
        elements.append(line_table)
        elements.append(Spacer(1, 10))
        
        # Bill To
        user_name = invoice.user.get_full_name() or invoice.user.username
        elements.append(Paragraph('<b>BILL TO:</b>', styles['Normal']))
        elements.append(Paragraph(user_name, styles['Normal']))
        
        # Add Unit Address
        try:
            from properties.models import Unit
            # Attempt to find the unit by building and unit_number from the invoice
            unit = Unit.objects.filter(building__name=invoice.building, unit_number=invoice.unit_number).first()
            if not unit and invoice.unit_number:
                # Fallback: maybe just using unit_number
                unit = Unit.objects.filter(unit_number=invoice.unit_number).first()
            
            if unit:
                line1_parts = [f"Unit {unit.unit_number}"]
                if unit.block:
                    line1_parts.append(f"Block {unit.block}")
                if unit.building and unit.building.name:
                    line1_parts.append(unit.building.name)
                
                line2_parts = []
                if unit.building:
                    city_state = []
                    for c in [unit.building.city, unit.building.state, unit.building.postal_code, unit.building.country]:
                        if c and str(c).strip():
                            city_state.append(str(c).strip())
                            
                    city_state_lower = [c.lower() for c in city_state]
                    
                    addr_lines = [
                        unit.building.address_line1,
                        unit.building.address_line2,
                        unit.building.address_line3,
                        unit.building.landmark
                    ]
                    for a in addr_lines:
                        if a and str(a).strip():
                            for part in str(a).split(','):
                                p_str = part.strip()
                                if p_str and p_str.lower() not in city_state_lower:
                                    line1_parts.append(p_str)
                                    
                    for c in city_state:
                        line2_parts.append(c)
                
                # Deduplicate line 1
                seen_line1 = set()
                deduped_line1 = []
                for p in line1_parts:
                    if p:
                        p_lower = p.lower().strip()
                        if p_lower not in seen_line1:
                            seen_line1.add(p_lower)
                            deduped_line1.append(p.strip())
                            
                # Deduplicate line 2
                seen_line2 = set()
                deduped_line2 = []
                for p in line2_parts:
                    if p:
                        p_lower = p.lower().strip()
                        if p_lower not in seen_line1 and p_lower not in seen_line2:
                            seen_line2.add(p_lower)
                            deduped_line2.append(p.strip())

                full_address = ", ".join(deduped_line1)
                if deduped_line2:
                    full_address += "<br/>" + ", ".join(deduped_line2)
                
                if full_address:
                    elements.append(Paragraph(full_address, styles['Normal']))
            else:
                if invoice.unit_number or invoice.building:
                    basic_addr = f"Unit {invoice.unit_number or 'N/A'}, {invoice.building or ''}".strip(', ')
                    elements.append(Paragraph(basic_addr, styles['Normal']))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not load unit address for invoice: {e}")
        elements.append(Spacer(1, 20))

        # Tenant reference details for owner-paid tenant invoices.
        latest_completed_payment = invoice.payments.filter(status='completed').select_related('user').order_by('-completed_at', '-created_at').first()
        paid_by_owner = bool(latest_completed_payment and getattr(latest_completed_payment.user, 'role', None) == 'owner')
        tenant_related = getattr(invoice.user, 'role', None) in ('tenant', 'tenant_vendor')
        if paid_by_owner and tenant_related:
            lease = getattr(getattr(invoice, 'maintenance_request', None), 'lease', None)
            lease_start = (lease.start_date if lease else None) or invoice.period_start
            lease_end = (lease.end_date if lease else None) or invoice.period_end

            tenant_contact_lines = [
                '<b>Tenant Reference:</b>',
                f"Name: {invoice.user.get_full_name() or invoice.user.username}",
                f"Email: {invoice.user.email or 'N/A'}",
                f"Phone: {getattr(invoice.user, 'phone', '') or 'N/A'}",
                f"Unit: {invoice.unit_number or 'N/A'}",
            ]
            if lease_start or lease_end:
                tenant_contact_lines.append(
                    f"Lease Period: {lease_start or 'N/A'} to {lease_end or 'N/A'}"
                )

            tenant_info_str = "<br/>".join(tenant_contact_lines)
            elements.append(Paragraph(tenant_info_str, styles['Normal']))
            elements.append(Spacer(1, 15))

        # Item Table
        item_data = [['#', 'Description:', 'Qty:', 'Unit Price:', 'Amount:']]
        
        line_items = invoice.line_items or []
        filtered_items = []
        association_charges = 0.0

        if line_items:
            for item in line_items:
                desc_lower = str(item.get('description', item.get('name', ''))).lower()
                type_lower = str(item.get('type', '')).lower()
                if type_lower == 'platform_fee' or 'association charge' in desc_lower or 'platform' in desc_lower:
                    qty = item.get('quantity', 1)
                    unit_price = item.get('unit_price', item.get('rate', 0))
                    amount = item.get('amount', item.get('total', float(qty) * float(unit_price)))
                    association_charges += float(amount)
                else:
                    filtered_items.append(item)

        if filtered_items:
            for idx, item in enumerate(filtered_items, 1):
                description = item.get('description', item.get('name', ''))
                qty = item.get('quantity', 1)
                unit_price = item.get('unit_price', item.get('rate', 0))
                amount = item.get('amount', item.get('total', float(qty) * float(unit_price)))
                item_data.append([
                    str(idx),
                    str(description),
                    str(qty),
                    f"${float(unit_price):,.2f}",
                    f"${float(amount):,.2f}"
                ])
        else:
            item_data.append([
                '1',
                invoice.description or invoice.get_invoice_type_display(),
                '1',
                f"${float(invoice.subtotal):,.2f}",
                f"${float(invoice.subtotal):,.2f}"
            ])
            
        # Pad with empty rows to maintain consistent table height
        data_rows_count = len(item_data) - 1  # Exclude header
        empty_rows_to_add = max(0, 8 - data_rows_count)
        for _ in range(empty_rows_to_add):
            item_data.append(['', '', '', '', ''])

        item_table = Table(item_data, colWidths=[0.5 * inch, 3.5 * inch, 0.8 * inch, 1.1 * inch, 1.1 * inch])
        item_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#555555')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(item_table)
        
        # Totals block
        totals_data = [
            ['Subtotal:', f"${float(invoice.subtotal):,.2f}"],
        ]
        
        if association_charges > 0:
            totals_data.append(['Association Charges:', f"${association_charges:,.2f}"])
            
        from tenants.models import TenantSettings
        settings = TenantSettings.objects.first()
        tax_percentage = settings.tax_percentage if settings else invoice.tax_percentage
        
        totals_data.extend([
            [f'Tax ({tax_percentage}%):', f"${float(invoice.tax_amount):,.2f}"],
        ])
        
        if invoice.discount_amount > 0:
            totals_data.append(['Discount:', f"-${float(invoice.discount_amount):,.2f}"])
        if invoice.late_fee > 0:
            totals_data.append(['Late Fee:', f"${float(invoice.late_fee):,.2f}"])
        totals_data.extend([
            ['Total:', f"${float(invoice.total_amount):,.2f}"],
        ])
        if invoice.amount_paid > 0:
            totals_data.append(['Amount Paid:', f"${float(invoice.amount_paid):,.2f}"])
        totals_data.append(['Amount Due:', f"${float(invoice.amount_due):,.2f}"])
        
        totals_table = Table(totals_data, colWidths=[1.5 * inch, 1.1 * inch])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('BACKGROUND', (0,0), (-1,-2), colors.HexColor('#2E5b7e')),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#1A3C54')),
            ('TEXTCOLOR', (0,0), (-1,-1), colors.white),
            ('GRID', (0,0), (-1,-1), 0.5, colors.white),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        
        totals_wrapper = Table([['', totals_table]], colWidths=[4.4 * inch, 2.6 * inch])
        totals_wrapper.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
        
        elements.append(totals_wrapper)
        elements.append(Spacer(1, 30))

        # Terms and conditions
        elements.append(Paragraph('<b>TERMS AND CONDITIONS</b>', styles['Normal']))
        terms = [
            "Payment must be received in full by the specified due date.",
            "A late fee will be assessed for any payment received after the due date.",
            "Payments may be completed via bank transfer, credit card, or the community portal.",
            "Unpaid balances exceeding 30 days may result in suspension of community access privileges.",
            "All fee disputes and discrepancies must be submitted in writing within 14 days.",
            "Partial payments do not halt the accrual of late penalties on remaining balances.",
            "Any returned or failed transactions will be subject to a processing surcharge."
        ]
        
        for term in terms:
            bullet_text = f"•  {term}"
            elements.append(Paragraph(bullet_text, styles['Normal']))
            elements.append(Spacer(1, 2))

        # Administrative fee notice
        elements.append(Spacer(1, 10))
        admin_notice_style = ParagraphStyle(
            'AdminNotice',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#b45309'),
            borderPad=6,
            backColor=colors.HexColor('#fffbeb'),
            borderColor=colors.HexColor('#f59e0b'),
            borderWidth=1,
            borderRadius=3,
        )
        elements.append(Paragraph(
            '<b>Note:</b> Additional administrative charges are applied at the time of payment. '
            'The final amount charged may vary based on your selected payment method (e.g., card or ACH).',
            admin_notice_style
        ))

        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{invoice.invoice_number}.pdf"'
        return response
    
    @action(detail=False, methods=['get'])
    def overdue(self, request):
        today = timezone.now().date()
        invoices = self.get_queryset().filter(
            due_date__lt=today,
            status__in=['sent', 'viewed', 'partially_paid']
        )
        serializer = self.get_serializer(invoices, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def my_invoices(self, request):
        invoices = self.get_queryset()
        serializer = self.get_serializer(invoices, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def export(self, request):
        export_format = request.query_params.get('format', 'csv')
        invoices = self.filter_queryset(self.get_queryset())
        
        filename = f"invoices_{timezone.now().strftime('%Y%m%d_%H%M')}"
        
        if export_format == 'csv':
            import csv
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
            
            writer = csv.writer(response)
            writer.writerow(['Invoice #', 'Organization', 'Admin Email', 'Type/Plan', 'Building', 'Unit', 'Amount', 'Amount Due', 'Status', 'Due Date', 'Expiry Time'])
            
            for inv in invoices:
                writer.writerow([
                    inv.invoice_number,
                    inv.building or 'N/A',
                    inv.user.email,
                    inv.get_invoice_type_display(),
                    inv.building,
                    inv.unit_number,
                    f"₹{inv.total_amount}",
                    f"₹{inv.amount_due}",
                    inv.get_status_display(),
                    inv.due_date.strftime("%Y-%m-%d") if inv.due_date else "",
                    # inv.expires_at.strftime("%Y-%m-%d %H:%M") if inv.expires_at else "—"
                ])
            return response
            
        elif export_format == 'excel':
            import pandas as pd
            import io
            
            excel_data = []
            for inv in invoices:
                excel_data.append({
                    'Invoice #': inv.invoice_number,
                    'Organization': inv.building or 'N/A',
                    'Admin Email': inv.user.email,
                    'Type/Plan': inv.get_invoice_type_display(),
                    'Building': inv.building,
                    'Unit': inv.unit_number,
                    'Amount': float(inv.total_amount),
                    'Amount Due': float(inv.amount_due),
                    'Status': inv.get_status_display(),
                    'Due Date': inv.due_date.strftime("%Y-%m-%d") if inv.due_date else "",
                    # 'Expiry Time': inv.expires_at.strftime("%Y-%m-%d %H:%M") if inv.expires_at else "—"
                })
            
            df = pd.DataFrame(excel_data)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Invoices')
            
            response = HttpResponse(
                output.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
            return response
            
        elif export_format == 'pdf':
            return Response({'error': 'Bulk PDF export not yet implemented. Please download individual PDFs.'}, status=400)
            
        return Response({'error': 'Unsupported format'}, status=400)

    @action(detail=True, methods=['post'], url_path='request-transfer')
    def request_transfer(self, request, pk=None):
        invoice = self.get_object()
        if invoice.invoice_type != 'maintenance_fee':
            return Response({'error': 'Only maintenance invoices can be transferred.'}, status=status.HTTP_400_BAD_REQUEST)

        owner_recipient = self._resolve_invoice_owner(invoice)
        if not owner_recipient:
            return Response(
                {'error': 'No owner is linked to this unit/invoice. Please assign an owner before requesting transfer.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invoice.owner_user = owner_recipient
        invoice.owner_email = getattr(owner_recipient, 'email', '') or invoice.owner_email

        invoice.transfer_status = 'requested'
        invoice.transfer_requested_by = request.user
        invoice.transfer_requested_at = timezone.now()
        invoice.payment_responsibility = 'tenant'
        invoice.responsible_user = invoice.user
        invoice.save(update_fields=[
            'transfer_status', 'transfer_requested_by', 'transfer_requested_at',
            'payment_responsibility', 'responsible_user', 'owner_user', 'owner_email', 'updated_at'
        ])

        NotificationService.send(
            user=owner_recipient,
            title=f'Payment Transfer Requested - #{invoice.invoice_number}',
            message=(
                f'Tenant {invoice.user.get_full_name() or invoice.user.email} requested '
                f'transfer of maintenance invoice #{invoice.invoice_number} for Unit {invoice.unit_number}.'
            ),
            notification_type='payment',
            priority='medium',
            send_email=True,
            send_push=True,
            related_object_type='invoice',
            related_object_id=invoice.id,
            action_url=f'/owner/payments?invoice={invoice.id}',
            metadata={
                'invoice_id': str(invoice.id),
                'invoice_number': invoice.invoice_number,
                'transfer_status': invoice.transfer_status,
            },
        )

        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=['post'], url_path='approve-transfer')
    def approve_transfer(self, request, pk=None):
        invoice = self.get_object()
        owner_email = getattr(request.user, 'email', '')
        owner_recipient = self._resolve_invoice_owner(invoice)
        if not (
            invoice.owner_user_id == request.user.id or
            (owner_recipient and owner_recipient.id == request.user.id) or
            (invoice.owner_email and invoice.owner_email.lower() == owner_email.lower())
        ):
            return Response({'error': 'Only the unit owner can approve this transfer.'}, status=status.HTTP_403_FORBIDDEN)

        invoice.transfer_status = 'approved'
        invoice.transfer_reviewed_by = request.user
        invoice.transfer_reviewed_at = timezone.now()
        invoice.payment_responsibility = 'owner'
        invoice.owner_user = owner_recipient or invoice.owner_user or request.user
        invoice.owner_email = getattr(invoice.owner_user, 'email', '') or invoice.owner_email
        invoice.responsible_user = invoice.owner_user or request.user
        invoice.transfer_rejection_reason = ''
        invoice.save(update_fields=[
            'transfer_status', 'transfer_reviewed_by', 'transfer_reviewed_at',
            'payment_responsibility', 'responsible_user', 'owner_user', 'owner_email', 'transfer_rejection_reason', 'updated_at'
        ])

        NotificationService.send(
            user=invoice.user,
            title=f'Payment Transfer Approved - #{invoice.invoice_number}',
            message=(
                f'Your transfer request for maintenance invoice #{invoice.invoice_number} has been approved. '
                f'Owner will now see and manage the payment.'
            ),
            notification_type='payment',
            priority='medium',
            send_email=True,
            send_push=True,
            related_object_type='invoice',
            related_object_id=invoice.id,
            action_url=f'/residents/payments?invoice={invoice.id}',
        )

        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=['post'], url_path='reject-transfer')
    def reject_transfer(self, request, pk=None):
        invoice = self.get_object()
        owner_email = getattr(request.user, 'email', '')
        owner_recipient = self._resolve_invoice_owner(invoice)
        if not (
            invoice.owner_user_id == request.user.id or
            (owner_recipient and owner_recipient.id == request.user.id) or
            (invoice.owner_email and invoice.owner_email.lower() == owner_email.lower())
        ):
            return Response({'error': 'Only the unit owner can reject this transfer.'}, status=status.HTTP_403_FORBIDDEN)

        reason = (request.data.get('reason') or '').strip()
        invoice.transfer_status = 'rejected'
        invoice.transfer_reviewed_by = request.user
        invoice.transfer_reviewed_at = timezone.now()
        invoice.payment_responsibility = 'tenant'
        invoice.responsible_user = invoice.user
        invoice.transfer_rejection_reason = reason
        invoice.save(update_fields=[
            'transfer_status', 'transfer_reviewed_by', 'transfer_reviewed_at',
            'payment_responsibility', 'responsible_user', 'transfer_rejection_reason', 'updated_at'
        ])

        NotificationService.send(
            user=invoice.user,
            title=f'Payment Transfer Rejected - #{invoice.invoice_number}',
            message=(
                f'Your transfer request for maintenance invoice #{invoice.invoice_number} was rejected. '
                f'{reason or "No reason provided."}'
            ),
            notification_type='payment',
            priority='high',
            send_email=True,
            send_push=True,
            related_object_type='invoice',
            related_object_id=invoice.id,
            action_url=f'/residents/payments?invoice={invoice.id}',
        )

        return Response(InvoiceSerializer(invoice).data)


class PaymentViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'payments'
    queryset = Payment.objects.all().select_related('user', 'invoice', 'invoice__user', 'gateway')
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'payment_method', 'user']
    search_fields = ['payment_number', 'receipt_number', 'description', 'user__first_name', 'user__last_name']
    ordering_fields = ['created_at', 'amount', 'completed_at']
    ordering = ['-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Add date range filtering
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)

        user = self.request.user
        if user.role in ['master_admin', 'masteradmin', 'super_admin', 'superadmin']:
            return queryset
        if user.role == 'owner':
            return queryset.filter(
                Q(user=user) |
                Q(invoice__owner_user=user) |
                Q(invoice__owner_email__iexact=getattr(user, 'email', ''))
            ).distinct()
        if user.role == 'facility_manager':
            from accounts.fm_scope import get_fm_building_names
            building_names = list(get_fm_building_names(user) or [])
            if not building_names:
                return queryset.none()
            
            # Show payments linked to invoices in FM's buildings
            # OR payments made by users who live in FM's buildings
            fm_users = User.objects.filter(
                Q(owned_units__building__name__in=building_names) | 
                Q(leases__unit__building__name__in=building_names) |
                Q(building_name__in=building_names)
            ).values_list('id', flat=True)

            return queryset.filter(
                Q(invoice__building__in=building_names) | 
                Q(user_id__in=fm_users)
            ).distinct()
        if not user.is_staff:
            return queryset.filter(user=user)
        return queryset

    def perform_create(self, serializer):
        """Handle manual payment recordings and notify relevant users."""
        payment = serializer.save()
        user = self.request.user

        # If a Facility Manager records a payment, notify Master Admin and the Tenant
        if getattr(user, 'role', None) == 'facility_manager':
            # Notify the user (tenant) who made the payment
            if payment.user:
                NotificationService.send(
                    user=payment.user,
                    title=f'Payment Recorded - #{payment.payment_number}',
                    message=f'Facility Manager {user.get_full_name()} has recorded a payment of ₹{payment.amount}.',
                    notification_type='payment',
                    priority='low',
                    send_email=True,
                    action_url=f'/residents/payments',
                )
            # Notify Master Admins about FM activity
            master_admins = User.objects.filter(role__in=['master_admin', 'masteradmin'])
            for admin in master_admins:
                NotificationService.send(
                    user=admin,
                    title='FM Activity: Payment Recorded',
                    message=f'Facility Manager {user.get_full_name()} recorded a payment of ₹{payment.amount} for {payment.user.get_full_name() if payment.user else "a tenant"}.',
                    notification_type='system',
                    priority='low',
                    send_email=True,
                    action_url='/admin/payments',
                )

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary of total payments for the user"""
        from django.db.models import Sum
        user = self.request.user
        qs = Payment.objects.filter(status='completed')

        if user.role == 'facility_manager':
            from accounts.fm_scope import get_fm_unit_pairs
            unit_pairs = list(get_fm_unit_pairs(user) or [])
            if not unit_pairs:
                qs = qs.none()
            else:
                location_q = Q()
                for building_name, unit_number in unit_pairs:
                    location_q |= Q(
                        invoice__building__iexact=building_name,
                        invoice__unit_number__iexact=unit_number,
                    )
                qs = qs.filter(location_q)
        elif not (user.is_staff or user.role in ['master_admin', 'masteradmin', 'super_admin', 'superadmin']):
            qs = qs.filter(user=user)
            
        total_paid = qs.aggregate(total=Sum('amount'))['total'] or 0.00
        return Response({'total_paid': total_paid})

    @action(detail=False, methods=['get'], url_path='platform-transactions')
    def platform_transactions(self, request):
        """Get platform fee transactions with hierarchy filtering."""
        user = self.request.user
        if getattr(user, 'role', None) not in ['master_admin', 'masteradmin', 'super_admin', 'superadmin']:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_403_FORBIDDEN)
            
        from django.db import connection
        is_public = connection.schema_name == 'public'
        
        # Hierarchy Filters
        colony_id = request.query_params.get('colony')
        block_id = request.query_params.get('block')
        building_id = request.query_params.get('building')
        unit_id = request.query_params.get('unit')
        
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        status_filter = request.query_params.get('status')
        
        def process_schema(schema_name=None):
            from properties.models import Building, Unit, Block
            from .models import Payment
            
            try:
                queryset = Payment.objects.select_related('user', 'invoice').filter(platform_fee__gt=0).order_by('-created_at')
            except Exception:
                return []
                
            if unit_id:
                try:
                    unit = Unit.objects.get(id=unit_id)
                    queryset = queryset.filter(invoice__building=unit.building.name, invoice__unit_number=unit.unit_number)
                except Unit.DoesNotExist:
                    pass
            elif building_id:
                try:
                    building = Building.objects.get(id=building_id)
                    queryset = queryset.filter(invoice__building=building.name)
                except Building.DoesNotExist:
                    pass
            elif block_id:
                try:
                    block = Block.objects.get(id=block_id)
                    queryset = queryset.filter(invoice__building=block.building.name)
                    units_in_block = Unit.objects.filter(building=block.building, block=block.name).values_list('unit_number', flat=True)
                    queryset = queryset.filter(invoice__unit_number__in=units_in_block)
                except Block.DoesNotExist:
                    pass
            elif colony_id:
                buildings = Building.objects.filter(township_id=colony_id).values_list('name', flat=True)
                queryset = queryset.filter(invoice__building__in=buildings)

            if start_date:
                queryset = queryset.filter(created_at__date__gte=start_date)
            if end_date:
                queryset = queryset.filter(created_at__date__lte=end_date)
            if status_filter:
                queryset = queryset.filter(status=status_filter)
                
            data = []
            for p in queryset:
                unit_number = "N/A"
                if p.user:
                    unit_number = getattr(p.user, 'unit_number', 'N/A') or 'N/A'
                elif p.invoice:
                    unit_number = p.invoice.unit_number or 'N/A'
                    
                owner_cut = 0.00
                master_cut = 0.00
                platform_cut = float(p.platform_fee)
                
                if p.metadata and 'split_owner_amount' in p.metadata:
                    owner_cut = float(p.metadata.get('split_owner_amount', 0.0))
                    master_cut = float(p.metadata.get('split_master_amount', 0.0))
                    platform_cut = float(p.metadata.get('split_platform_fee', platform_cut))
                else:
                    if p.invoice and p.invoice.unit_number:
                        unit = Unit.objects.filter(unit_number=p.invoice.unit_number, building__name=p.invoice.building).first()
                        net_for_hoa = float(p.amount) - platform_cut
                        if unit and unit.owner_user:
                            fee_type = unit.management_fee_override_type
                            fee_val = unit.management_fee_override_value
                            if not fee_type or fee_type == 'none':
                                from tenants.models import TenantSettings
                                settings = TenantSettings.objects.first()
                                if settings:
                                    fee_type = settings.management_fee_type
                                    fee_val = settings.management_fee_value
                            if fee_type == 'percentage' and fee_val:
                                master_cut = (net_for_hoa * float(fee_val)) / 100.0
                            elif fee_type == 'fixed' and fee_val:
                                master_cut = float(fee_val)
                            owner_cut = net_for_hoa - master_cut
                        else:
                            master_cut = net_for_hoa
                    else:
                        master_cut = float(p.amount) - platform_cut

                data.append({
                    'id': str(p.id),
                    'date': p.completed_at.isoformat() if p.completed_at else p.created_at.isoformat(),
                    'resident_name': p.user.get_full_name() if p.user else 'Unknown',
                    'resident_unit': unit_number,
                    'method': p.get_payment_method_display() if hasattr(p, 'get_payment_method_display') else p.payment_method,
                    'amount': float(p.amount),
                    'platform_fee': platform_cut,
                    'owner_cut': owner_cut,
                    'master_admin_cut': master_cut,
                    'status': p.status.capitalize() if p.status else 'Pending',
                    'community': schema_name if schema_name else 'Current'
                })
            return data

        all_data = []
        if is_public:
            from tenants.models import Client
            from django_tenants.utils import schema_context
            tenants = Client.objects.exclude(schema_name='public')
            for t in tenants:
                with schema_context(t.schema_name):
                    try:
                        all_data.extend(process_schema(t.schema_name))
                    except Exception as e:
                        print(f"Error processing schema {t.schema_name}: {e}")
            all_data.sort(key=lambda x: x['date'], reverse=True)
        else:
            all_data = process_schema(connection.schema_name)
            
        page = self.paginate_queryset(all_data)
        if page is not None:
            return self.get_paginated_response(page)
            
        return Response(all_data)

    @action(detail=False, methods=['get'], url_path='owner-rent-transactions')
    def owner_rent_transactions(self, request):
        """
        Returns transactions for units owned by the current owner user.
        Exposes the exact splits: total rent, platform fee, master admin cut, and owner cut.
        """
        if not request.user.role.lower() == 'owner':
            return Response({'error': 'Unauthorized'}, status=403)
            
        from properties.models import Unit
        owned_units = Unit.objects.filter(owner_user=request.user)
        unit_numbers = [u.unit_number for u in owned_units]
        
        # Get completed payments where the invoice belongs to an owned unit
        queryset = Payment.objects.filter(
            invoice__unit_number__in=unit_numbers,
            status='completed'
        ).order_by('-completed_at')
        
        data = []
        for p in queryset:
            unit_number = p.invoice.unit_number if p.invoice else 'N/A'
                
            owner_cut = 0.00
            master_cut = 0.00
            platform_cut = float(p.platform_fee)
            
            if p.metadata and 'split_owner_amount' in p.metadata:
                owner_cut = float(p.metadata.get('split_owner_amount', 0.0))
                master_cut = float(p.metadata.get('split_master_amount', 0.0))
                platform_cut = float(p.metadata.get('split_platform_fee', platform_cut))
            else:
                if p.invoice and p.invoice.unit_number:
                    unit = Unit.objects.filter(unit_number=p.invoice.unit_number, building__name=p.invoice.building).first()
                    net_for_hoa = float(p.amount) - platform_cut
                    if unit and unit.owner_user:
                        fee_type = unit.management_fee_override_type
                        fee_val = unit.management_fee_override_value
                        if not fee_type or fee_type == 'none':
                            from tenants.models import TenantSettings
                            settings = TenantSettings.objects.first()
                            if settings:
                                fee_type = settings.management_fee_type
                                fee_val = settings.management_fee_value
                        if fee_type == 'percentage' and fee_val:
                            master_cut = (net_for_hoa * float(fee_val)) / 100.0
                        elif fee_type == 'fixed' and fee_val:
                            master_cut = float(fee_val)
                        owner_cut = net_for_hoa - master_cut
                    else:
                        master_cut = net_for_hoa
                else:
                    master_cut = float(p.amount) - platform_cut
                    
            data.append({
                'id': str(p.id),
                'date': p.completed_at.isoformat() if p.completed_at else p.created_at.isoformat(),
                'resident_name': p.user.get_full_name() if p.user else 'Unknown',
                'resident_unit': unit_number,
                'method': p.get_payment_method_display() if hasattr(p, 'get_payment_method_display') else p.payment_method,
                'amount': float(p.amount),
                'platform_fee': platform_cut,
                'owner_cut': owner_cut,
                'master_admin_cut': master_cut,
                'status': p.status.capitalize() if p.status else 'Pending'
            })
            
        return Response(data)
    
    @action(detail=False, methods=['post'])
    def initiate(self, request):
        """Initiate a payment transaction"""
        serializer = PaymentInitiateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        gateway_type = data['gateway_type']
        
        # Get active gateway
        try:
            gateway = PaymentGateway.objects.get(gateway_type=gateway_type, is_active=True)
        except PaymentGateway.DoesNotExist:
            return Response({'error': f'{gateway_type} gateway not configured'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        # Create payment record
        payment = Payment.objects.create(
            user=request.user,
            invoice_id=data.get('invoice_id'),
            amount=data['amount'],
            payment_method=data['payment_method'],
            gateway=gateway,
            status='pending'
        )
        
        # Initialize payment with gateway
        metadata = {
            'payment_id': str(payment.id),
            'save_payment_method': str(data.get('save_payment_method', False)).lower()
        }

        if gateway_type == 'razorpay':
            payment.delete()
            return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
        elif gateway_type == 'stripe':
            service = StripeService(gateway)
            result = service.create_payment_intent(
                amount=float(data['amount']),
                currency=gateway.currency,
                metadata=metadata
            )
        else:
            payment.delete()
            return Response({'error': 'Gateway not supported'}, status=status.HTTP_400_BAD_REQUEST)

        
        if result.get('success'):
            payment.gateway_order_id = result.get('order_id') or result.get('payment_intent_id') or result.get('intent_id')
            payment.gateway_response = result
            payment.status = 'processing'
            payment.save()
            
            return Response({
                'payment_id': str(payment.id),
                'payment_number': payment.payment_number,
                **result
            })
        else:
            payment.status = 'failed'
            payment.failure_reason = result.get('error', 'Unknown error')
            payment.save()
            
            return Response({'error': result.get('error')}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def initiate_or_update(self, request):
        """
        Initiates a new payment or updates an existing draft payment.
        Calculates dynamic fees based on payment method.
        """
        invoice_id = request.data.get('invoice_id')
        payment_method_type = request.data.get('payment_method_type', 'card')
        payment_id = request.data.get('payment_id')

        if not invoice_id:
            return Response({'error': 'invoice_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            invoice = Invoice.objects.get(id=invoice_id)
        except Invoice.DoesNotExist:
            return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            gateway = PaymentGateway.objects.get(gateway_type='stripe', is_active=True)
        except PaymentGateway.DoesNotExist:
            return Response({'error': 'Stripe gateway not configured'}, status=status.HTTP_400_BAD_REQUEST)

        # Calculate fees
        base_amount = Decimal(str(invoice.amount_due))
        fee_data = calculate_fee(base_amount, payment_method_type, gateway.settings)
        total_charge = Decimal(str(fee_data['total_charge']))
        platform_fee = Decimal(str(fee_data['fee_amount']))

        payment = None
        is_new = False
        
        if payment_id:
            try:
                payment = Payment.objects.get(id=payment_id, user=request.user, status__in=['pending', 'processing', 'draft'])
            except Payment.DoesNotExist:
                pass
        
        if not payment:
            # Look for existing draft for this invoice
            payment = Payment.objects.filter(
                invoice_id=invoice_id, 
                user=request.user, 
                status__in=['pending', 'draft']
            ).order_by('-created_at').first()

        service = StripeService(gateway)

        metadata = {
            'payment_id': '', # Placeholder, set below
            'invoice_id': str(invoice.id),
            'selected_method': payment_method_type,
            'base_amount': int(base_amount * 100),
            'platform_fee': int(platform_fee * 100),
        }

        is_new = False
        method_changed = False
        
        if payment and payment.payment_method:
            old_method = payment.payment_method.replace('stripe_', '')
            if old_method != payment_method_type:
                method_changed = True

        if payment and payment.gateway_response and payment.gateway_response.get('intent_id') and not method_changed:
            # Update existing
            payment.amount = total_charge
            payment.platform_fee = platform_fee
            payment.payment_method = f"stripe_{payment_method_type}"
            payment.save()
            
            metadata['payment_id'] = str(payment.id)
            
            result = service.update_payment_intent(
                intent_id=payment.gateway_response['intent_id'],
                amount=total_charge,
                metadata=metadata,
                payment_method_type=payment_method_type
            )
            
            # If the old intent uses automatic_payment_methods, we cannot lock it.
            # We must recreate it.
            if not result.get('success') and result.get('requires_recreate'):
                service.cancel_payment_intent(payment.gateway_response['intent_id'])
                payment.gateway_response = {}
                payment.save()
                
                result = service.create_payment_intent(
                    amount=total_charge,
                    payment_method_type=payment_method_type,
                    currency=gateway.currency,
                    metadata=metadata,
                )
        else:
            # If method changed, cancel old intent so we get a fresh one with new allowed methods
            if method_changed and payment and payment.gateway_response and payment.gateway_response.get('intent_id'):
                service.cancel_payment_intent(payment.gateway_response['intent_id'])
            
            # Create new or update existing payment record
            if not payment:
                is_new = True
                payment = Payment.objects.create(
                    user=request.user,
                    invoice_id=invoice_id,
                    amount=total_charge,
                    platform_fee=platform_fee,
                    payment_method=f"stripe_{payment_method_type}",
                    gateway=gateway,
                    status='draft'
                )
            else:
                payment.amount = total_charge
                payment.platform_fee = platform_fee
                payment.payment_method = f"stripe_{payment_method_type}"
                payment.gateway_response = {}  # Clear old response
                payment.save()

            metadata['payment_id'] = str(payment.id)
            
            result = service.create_payment_intent(
                amount=total_charge,
                payment_method_type=payment_method_type,
                currency=gateway.currency,
                metadata=metadata,
            )

        if result.get('success'):
            payment.gateway_order_id = result.get('order_id') or result.get('payment_intent_id') or result.get('intent_id')
            # Only update response if it's new or intent changed, to preserve publishable_key if we want
            if is_new or 'publishable_key' in result:
                payment.gateway_response = result
            else:
                resp = payment.gateway_response
                resp.update(result)
                payment.gateway_response = resp
            payment.status = 'pending' # or draft
            payment.save()
            
            return Response({
                'payment_id': str(payment.id),
                'payment_number': payment.payment_number,
                'fee_breakdown': fee_data,
                **payment.gateway_response
            })
        else:
            if is_new:
                payment.status = 'failed'
                payment.failure_reason = result.get('error', 'Unknown error')
                payment.save()
            
            return Response({'error': result.get('error')}, status=status.HTTP_400_BAD_REQUEST)


    @action(detail=True, methods=['get'])
    def receipt(self, request, pk=None):
        """Generate a PDF receipt for a payment"""
        payment = self.get_object()
        
        import io
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageTemplate, BaseDocTemplate, Frame
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT

        buffer = io.BytesIO()
        
        def border_bg(canvas, doc):
            canvas.saveState()
            # Draw green borders like in screenshot
            canvas.setFillColor(colors.HexColor('#2E5b4c')) # Dark green
            # Top right accent block
            canvas.rect(letter[0] - inch, letter[1] - inch, 0.5*inch, 0.5*inch, stroke=0, fill=1)
            # Left strip
            canvas.rect(0.5*inch, letter[1] - 1.5*inch, 0.15*inch, 1*inch, stroke=0, fill=1)
            # Bottom right triangle/accent frame
            canvas.rect(letter[0] - inch, 0.5*inch, 0.5*inch, 0.5*inch, stroke=0, fill=1)
            # A border running up from bottom right
            canvas.setStrokeColor(colors.HexColor('#2E5b4c'))
            canvas.setLineWidth(4)
            canvas.line(letter[0] - inch, 0.5*inch, letter[0] - inch, 1.5*inch)
            # Horizontal bottom border
            canvas.line(letter[0] - 2*inch, 0.5*inch, letter[0] - inch, 0.5*inch)
            canvas.restoreState()

        class ReceiptDocTemplate(BaseDocTemplate):
            def __init__(self, filename, **kw):
                super().__init__(filename, **kw)
                frame = Frame(0.75 * inch, 0.75 * inch, letter[0] - 1.5 * inch, letter[1] - 1.5 * inch, id='F1')
                template = PageTemplate('normal', [frame], onPage=border_bg)
                self.addPageTemplates(template)

        doc = ReceiptDocTemplate(buffer, pagesize=letter)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('ReceiptTitle', parent=styles['Title'], fontSize=28,
                                     spaceAfter=20, textColor=colors.HexColor('#1A2A3A'), alignment=TA_LEFT, fontName='Helvetica-Bold')

        heading_style = ParagraphStyle('ReceiptHeading', parent=styles['Heading2'], fontSize=16,
                                       spaceBefore=20, spaceAfter=10, textColor=colors.HexColor('#1A2A3A'), fontName='Helvetica-Bold')
        normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontSize=11, spaceAfter=3)
        
        elements = []

        # Header
        elements.append(Paragraph("PAYMENT RECEIPT", title_style))
        elements.append(Spacer(1, 12))

        # Receipt info table
        info_data = [
            ["Receipt Number:", payment.payment_number],
            ["Date:", payment.created_at.strftime("%B %d, %Y")],
            ["Status:", ''], # Placeholder for status paragraph
        ]
        if payment.invoice:
            info_data.append(["Invoice Number:", payment.invoice.invoice_number])
        
        # Build status element
        status_style = ParagraphStyle('StatusStyle', parent=styles['Normal'], textColor=colors.white, backColor=colors.HexColor('#388E3C'), borderPadding=(3,8,3,8), fontName='Helvetica-Bold', alignment=TA_CENTER)
        status_p = Paragraph(f"<font color='white'>{payment.status.upper()}</font>", status_style)
        info_data[2][1] = status_p
        
        info_table = Table(info_data, colWidths=[1.8 * inch, 4.0 * inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#EFEFEF')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        
        elements.append(info_table)

        # Payer Information
        elements.append(Paragraph("Payer Information", heading_style))
        elements.append(Paragraph(payment.user.get_full_name(), normal_style))
        elements.append(Paragraph(payment.user.email, normal_style))
        elements.append(Spacer(1, 10))

        # Payment details table
        elements.append(Paragraph("Payment Details", heading_style))
        
        base_amount = float(payment.amount) - float(payment.platform_fee or 0)
        
        details_data = [
            ["Description", "Amount"],
            [f"Payment for {payment.invoice.invoice_number}" if payment.invoice else "Direct Payment", 
             f"${base_amount:,.2f}"]
        ]
        
        if payment.platform_fee and float(payment.platform_fee) > 0:
            details_data.append(["Administrative Fee", f"${float(payment.platform_fee):,.2f}"])
        
        if payment.invoice:
            from tenants.models import TenantSettings
            settings = TenantSettings.objects.first()
            tax_percentage = settings.tax_percentage if settings else payment.invoice.tax_percentage
            details_data.append([f"    - Includes Tax ({tax_percentage}%)", f"${float(payment.invoice.tax_amount):,.2f}"])
        
        # Add total row
        details_data.append(["TOTAL PAID:", f"${float(payment.amount):,.2f}"])
        
        details_table = Table(details_data, colWidths=[4.3 * inch, 1.5 * inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EFEFEF')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#1A2A3A')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), # Total row bold
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(details_table)
        
        elements.append(Spacer(1, 60))
        elements.append(Paragraph("Thank you for your payment!", 
                                 ParagraphStyle('ThankYou', parent=styles['Normal'], alignment=TA_CENTER, fontSize=14, textColor=colors.HexColor('#1A2A3A'))))

        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="receipt_{payment.payment_number}.pdf"'
        return response
    
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirm payment after gateway processing (Razorpay is disabled)"""
        return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'])
    def verify_razorpay(self, request):
        """Verify Razorpay payment signature (permanently disabled)"""
        return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def verify_stripe(self, request, pk=None):
        """Verify Stripe payment intent"""
        payment = self.get_object()
        intent_id = request.data.get('intent_id') or request.data.get('payment_intent_id')
        
        if not intent_id:
            return Response({'error': 'Missing intent_id'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            gateway = payment.gateway
            
            if not gateway or gateway.gateway_type != 'stripe':
                return Response({'error': 'Invalid gateway for verification'}, status=status.HTTP_400_BAD_REQUEST)
                
            service = StripeService(gateway)
            result = service.verify_payment(intent_id)
            
            if result.get('success'):
                payment.refresh_from_db()
                # Update invoice is also handled by process_successful_payment
                if payment.invoice:
                    invoice = payment.invoice
                    if invoice.status != 'paid':
                        invoice.status = 'paid'
                        invoice.paid_at = timezone.now()
                        invoice.save()

                # Send payment receipt email
                try:
                    from accounts.email_service import EmailService
                    EmailService.send_email(
                        to_email=payment.user.email,
                        subject=f'Payment Receipt - {payment.transaction_id or intent_id}',
                        template_name='payment_receipt',
                        context={
                            'user': payment.user,
                            'message': f"We have successfully received your Stripe payment of ₹{payment.amount} for {payment.invoice.description if payment.invoice else 'your payment'}.",
                            'amount': payment.amount,
                            'transaction_id': intent_id or payment.transaction_id,
                            'date': payment.completed_at.strftime('%B %d, %Y') if payment.completed_at else timezone.now().strftime('%B %d, %Y'),
                            'domain': getattr(settings, 'FRONTEND_DOMAIN', 'hoaconnecthub.com')
                        }
                    )
                    logger.info(f"Payment receipt sent to {payment.user.email} (Stripe)")
                except Exception as email_err:
                    logger.warning(f"Failed to send Stripe payment receipt to {payment.user.email}: {email_err}")
                
                return Response({
                    'message': 'Payment verified successfully',
                    'payment': PaymentSerializer(payment).data
                })
            else:
                payment.status = 'failed'
                payment.failed_at = timezone.now()
                payment.failure_reason = result.get('error')
                payment.save()
                return Response({'error': result.get('error')}, status=status.HTTP_400_BAD_REQUEST)
                
        except Payment.DoesNotExist:
            return Response({'error': 'Payment record not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    @action(detail=False, methods=['get'])
    def my_payments(self, request):
        payments = self.get_queryset().filter(user=request.user)
        serializer = self.get_serializer(payments, many=True)
        return Response(serializer.data)


class PaymentMethodViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'payments'
    staff_actions = []  # Residents can manage their own payment methods
    queryset = PaymentMethod.objects.all().select_related('user', 'gateway')
    serializer_class = PaymentMethodSerializer

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        method = self.get_object()
        
        # Remove default from other methods
        self.get_queryset().update(is_default=False)
        
        # Set this as default
        method.is_default = True
        method.save()
        
        return Response({'message': 'Payment method set as default'})

    @action(detail=False, methods=['post'])
    def initiate_setup(self, request):
        """Initiate adding a new payment method (verification or SetupIntent)"""
        from django.conf import settings as django_settings
        gateway_type = request.data.get('gateway_type', 'stripe')
        gateway = PaymentGateway.objects.filter(gateway_type=gateway_type, is_active=True).first()
        
        if not gateway:
            gateway = PaymentGateway.objects.filter(is_active=True).first()
        
        if not User.objects.filter(id=request.user.id).exists():
            return Response({'error': 'User record not found in this property schema.'}, status=403)

        # ── Fallback: use platform-level Stripe keys when no tenant gateway exists ──
        if not gateway or gateway.gateway_type != 'stripe':
            platform_secret, platform_pub = get_platform_keys()
            if not platform_secret:
                return Response(
                    {'error': 'No active payment gateway configured. Please ask your administrator to set up Stripe.'},
                    status=400
                )

            # Build a virtual (unsaved) gateway so StripeService works without DB object
            gateway = PaymentGateway(
                gateway_type='stripe',
                secret_key=platform_secret,
                public_key=platform_pub or '',
                stripe_connected_account_id=None,
                charges_enabled=False,
                is_active=True,
            )
            
        if gateway.gateway_type == 'stripe':
            service = StripeService(gateway)
            result = service.create_setup_intent(request.user)
            return Response(result)
        
        elif gateway.gateway_type == 'razorpay':
            return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({'error': f'Gateway {gateway.gateway_type} does not support setup intents'}, status=400)

    @action(detail=False, methods=['post'])
    def verify_setup(self, request):
        """Verify and save a payment method after SetupIntent success"""
        from django.conf import settings as django_settings
        setup_intent_id = request.data.get('setup_intent_id')
        gateway_type = request.data.get('gateway_type', 'stripe')
        
        if not setup_intent_id:
            return Response({'error': 'Missing setup_intent_id'}, status=400)
            
        gateway = PaymentGateway.objects.filter(gateway_type=gateway_type, is_active=True).first()

        # ── Fallback: use platform-level Stripe keys when no tenant gateway exists ──
        use_virtual_gateway = False
        if not gateway or gateway.gateway_type != 'stripe':
            platform_secret, platform_pub = get_platform_keys()
            if not platform_secret:
                return Response({'error': 'Active gateway not found'}, status=404)
            gateway = PaymentGateway(
                gateway_type='stripe',
                secret_key=platform_secret,
                public_key=platform_pub or '',
                stripe_connected_account_id=None,
                charges_enabled=False,
                is_active=True,
            )
            use_virtual_gateway = True
            
        try:
            import stripe
            
            platform_secret, _ = get_platform_keys()
            api_key = gateway.secret_key
            if gateway.stripe_connected_account_id or not api_key:
                api_key = platform_secret
            
            logger.info(f"verify_setup: gateway_type={gateway.gateway_type}, has_secret={bool(gateway.secret_key)}, "
                        f"connected_acct={gateway.stripe_connected_account_id}, using_platform_key={api_key == platform_secret}, "
                        f"use_virtual_gateway={use_virtual_gateway}")
                
            stripe.api_key = api_key
            setup_intent = stripe.SetupIntent.retrieve(setup_intent_id)
            
            if setup_intent.status == 'succeeded':
                payment_method_id = setup_intent.payment_method
                pm_details = stripe.PaymentMethod.retrieve(payment_method_id)

                # For virtual (platform) gateway, we save without gateway FK so we get or create the real one later
                if use_virtual_gateway:
                    # Try to get/create a persisted platform gateway record for linking
                    real_gateway, _ = PaymentGateway.objects.get_or_create(
                        gateway_type='stripe',
                        defaults={
                            'secret_key': gateway.secret_key,
                            'public_key': gateway.public_key,
                            'is_active': True,
                        }
                    )
                    gateway = real_gateway
                
                method, created = PaymentMethod.objects.update_or_create(
                    user=request.user,
                    gateway=gateway,
                    gateway_payment_method_id=payment_method_id,
                    defaults={
                        'method_type': f'stripe_{pm_details.type}',
                        'card_brand': pm_details.card.brand if hasattr(pm_details, 'card') and pm_details.card else '',
                        'card_last4': pm_details.card.last4 if hasattr(pm_details, 'card') and pm_details.card else '',
                        'card_exp_month': pm_details.card.exp_month if hasattr(pm_details, 'card') and pm_details.card else None,
                        'card_exp_year': pm_details.card.exp_year if hasattr(pm_details, 'card') and pm_details.card else None,
                        'is_default': not PaymentMethod.objects.filter(user=request.user).exists()
                    }
                )
                
                return Response({
                    'success': True,
                    'message': 'Payment method saved successfully',
                    'payment_method': PaymentMethodSerializer(method).data
                })
            else:
                return Response({'error': f'Setup failed: {setup_intent.status}'}, status=400)
        except Exception as e:
            import traceback
            logger.error(f"verify_setup FAILED: {str(e)}\n{traceback.format_exc()}")
            return Response({'error': str(e)}, status=500)


    @action(detail=False, methods=['get'])
    def debug_test_autopay(self, request):
        """Debug endpoint to test autopay flow (GreenWood only)"""
        from django_tenants.utils import schema_context
        from .tasks import process_scheduled_autopay_payments
        
        # This will simulate a charge for the first active enrollment found
        enrollment = AutoPayEnrollment.objects.filter(status='active').first()
        if not enrollment:
            return Response({'error': 'No active enrollment found for testing'}, status=404)
            
        logger.info(f"DEBUG: Manually triggering charge for enrollment {enrollment.id}")
        
        # We try to charge it
        if enrollment.gateway.gateway_type == 'stripe':
            try:
                from .services.stripe_autopay_service import StripeAutoPayService
                service = StripeAutoPayService(enrollment.gateway)
                result = service.charge_customer_off_session(
                    customer_id=enrollment.stripe_customer_id or 'cust_test_123',
                    amount=float(enrollment.amount),
                    metadata={'test': 'true', 'enrollment_id': str(enrollment.id)}
                )
                return Response({
                    'message': 'Debug charge triggered',
                    'target_enrollment': enrollment.enrollment_number,
                    'gateway': enrollment.gateway.gateway_type,
                    'result': result
                })
            except Exception as e:
                return Response({'error': str(e)}, status=500)
        else:
            return Response({'error': f'Gateway {enrollment.gateway.gateway_type} is not supported for debugging.'}, status=status.HTTP_400_BAD_REQUEST)


class RefundViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'payments'
    queryset = Refund.objects.all().select_related('payment', 'payment__invoice', 'requested_by', 'approved_by')
    serializer_class = RefundSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']
    ordering = ['-created_at']
    
    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """Process refund through payment gateway"""
        refund = self.get_object()
        
        if refund.status != 'pending':
            return Response({'error': 'Refund already processed'}, status=status.HTTP_400_BAD_REQUEST)
        
        payment = refund.payment
        
        # Process refund with gateway
        if payment.gateway.gateway_type == 'stripe':
            from .services.stripe_service import StripeService
            service = StripeService(payment.gateway)
            result = service.create_refund(
                intent_id=payment.gateway_payment_id,
                amount=float(refund.amount)
            )
        else:
            return Response({'error': 'Gateway not supported'}, status=status.HTTP_400_BAD_REQUEST)
        
        if result.get('success'):
            refund.status = 'completed'
            refund.processed_at = timezone.now()
            refund.approved_by = request.user
            refund.gateway_refund_id = result.get('refund_id')
            refund.gateway_response = result
            refund.save()
            
            # Update payment
            payment.refund_amount += refund.amount
            payment.save()
            
            return Response({
                'message': 'Refund processed successfully',
                'refund': RefundSerializer(refund).data
            })
        else:
            refund.status = 'failed'
            refund.save()
            
            return Response({'error': result.get('error')}, status=status.HTTP_400_BAD_REQUEST)


class PaymentPlanViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'payments'
    queryset = PaymentPlan.objects.all().select_related('user', 'invoice')
    serializer_class = PaymentPlanSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'user']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        return queryset


class PaymentReminderViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'payments'
    queryset = PaymentReminder.objects.select_related('invoice', 'invoice__user').all()
    serializer_class = PaymentReminderSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['reminder_type', 'is_sent', 'invoice']
    search_fields = ['invoice__invoice_number']
    ordering_fields = ['scheduled_for', 'created_at']
    ordering = ['-scheduled_for']

    @action(detail=True, methods=['post'])
    def mark_sent(self, request, pk=None):
        reminder = self.get_object()
        reminder.is_sent = True
        reminder.sent_at = timezone.now()
        reminder.save()
        return Response({'message': 'Reminder marked as sent', 'reminder': PaymentReminderSerializer(reminder).data})

class InstallmentViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'payments'
    queryset = Installment.objects.select_related('payment_plan', 'payment_plan__user').all()
    serializer_class = InstallmentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'payment_plan']
    ordering_fields = ['due_date', 'installment_number']
    ordering = ['due_date']

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        installment = self.get_object()
        installment.status = 'paid'
        installment.paid_date = timezone.now().date()
        installment.save()
        return Response({'message': 'Installment marked as paid', 'installment': InstallmentSerializer(installment).data})

class TransactionViewSet(ModulePermissionMixin, viewsets.ReadOnlyModelViewSet):
    module = 'payments'
    queryset = Transaction.objects.select_related('user').all()
    serializer_class = TransactionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['transaction_type', 'user']
    search_fields = ['transaction_number', 'description']
    ordering_fields = ['created_at', 'amount']
    ordering = ['-created_at']


@extend_schema(responses=PaymentDashboardSerializer)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def payment_dashboard(request):
    """Get payment dashboard statistics"""
    
    from django.utils import timezone
    today = timezone.now().date()
    current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Combine total and monthly revenue into a single query
    from django.db.models import Q, Count, Sum
    payment_stats = Payment.objects.filter(status='completed').aggregate(
        total_revenue=Sum('amount'),
        revenue_this_month=Sum('amount', filter=Q(completed_at__gte=current_month))
    )
    total_revenue = payment_stats['total_revenue'] or 0
    revenue_this_month = payment_stats['revenue_this_month'] or 0
    
    # Combine all invoice statistics into a single query
    from django.db.models import Count, Q
    invoice_stats = Invoice.objects.aggregate(
        total_invoices=Count('id'),
        paid_invoices=Count('id', filter=Q(status='paid')),
        pending_invoices=Count('id', filter=Q(status__in=['sent', 'viewed', 'partially_paid'])),
        pending_payments=Sum('amount_due', filter=Q(status__in=['sent', 'viewed', 'partially_paid'])),
        overdue_count=Count('id', filter=Q(due_date__lt=today, status__in=['sent', 'viewed', 'partially_paid'])),
        overdue_amount=Sum('amount_due', filter=Q(due_date__lt=today, status__in=['sent', 'viewed', 'partially_paid']))
    )

    # Use combined stats
    pending_payments = invoice_stats['pending_payments'] or 0
    overdue_count = invoice_stats['overdue_count'] or 0
    overdue_amount = invoice_stats['overdue_amount'] or 0
    total_invoices = invoice_stats['total_invoices'] or 0
    paid_invoices = invoice_stats['paid_invoices'] or 0
    pending_invoices = invoice_stats['pending_invoices'] or 0
    
    data = {
        'total_revenue': total_revenue,
        'revenue_this_month': revenue_this_month,
        'pending_payments': pending_payments,
        'overdue_invoices_count': overdue_count,
        'overdue_amount': overdue_amount,
        'total_invoices': total_invoices,
        'paid_invoices': paid_invoices,
        'pending_invoices': pending_invoices
    }
    
    serializer = PaymentDashboardSerializer(data)
    return Response(serializer.data)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def webhook_razorpay(request):
    """Handle Razorpay webhooks (permanently disabled)"""
    return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)


class AutoPayEnrollmentViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing auto-pay enrollments"""
    module = 'payments'
    staff_actions = ['update', 'partial_update', 'destroy']

    queryset = AutoPayEnrollment.objects.all().select_related('user', 'gateway', 'payment_method')
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['status', 'frequency', 'user']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return AutoPayEnrollmentCreateSerializer
        return AutoPayEnrollmentSerializer
    
    def get_permissions(self):
        if self.action == 'debug_migrate':
            return [permissions.AllowAny()]
        return super().get_permissions()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        return queryset
    
    def create(self, request, *args, **kwargs):
        """Enroll user in auto-pay (Stripe only; Razorpay is disabled)."""
        serializer = AutoPayEnrollmentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        gateway_type = data.get('gateway_type')

        # Get the requested gateway or the default active one
        try:
            if gateway_type:
                gateway = PaymentGateway.objects.get(gateway_type=gateway_type, is_active=True)
            else:
                # If no gateway specified, use the first active one for this tenant
                gateway = PaymentGateway.objects.filter(is_active=True).first()
                if not gateway:
                    return Response({'error': 'No active payment gateway configured'},
                                  status=status.HTTP_400_BAD_REQUEST)
                gateway_type = gateway.gateway_type
        except PaymentGateway.DoesNotExist:
            return Response({'error': f'{gateway_type} gateway not configured'},
                          status=status.HTTP_400_BAD_REQUEST)

        # Get payment method
        try:
            payment_method = PaymentMethod.objects.get(
                id=data['payment_method_id'],
                user=request.user,
                gateway=gateway,
            )
        except PaymentMethod.DoesNotExist:
            return Response(
                {'error': 'Invalid payment method for this user/gateway'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription_metadata = {
            'user_id': str(request.user.id),
            'enrollment_type': data['enrollment_type'],
            'product_name': f"{data['enrollment_type'].title()} - {data['frequency']}"
        }
        if data.get('mandate_limit_amount') is not None:
            subscription_metadata['mandate_limit_amount'] = str(data['mandate_limit_amount'])

        if gateway_type == 'razorpay':
            return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)

        elif gateway_type == 'stripe':
            # --- Native Stripe Subscription enrollment ---
            try:
                from .services.stripe_autopay_service import StripeAutoPayService
                service = StripeAutoPayService(gateway)
                
                # 1. Ensure customer has the payment method attached as default
                if stripe is None:
                    return Response({'error': 'Stripe library is not installed'}, status=400)
                
                platform_secret, _ = get_platform_keys()
                api_key = gateway.secret_key
                if gateway.stripe_connected_account_id or not api_key:
                    api_key = platform_secret
                
                stripe.api_key = api_key
                
                # Attach payment method to customer if not already (Stripe might have done it in SetupIntent)
                customer_id = payment_method.gateway_customer_id or payment_method.metadata.get('stripe_customer_id')
                if not customer_id:
                    # Fallback: get or create customer
                    cust_res = service.create_or_get_customer(request.user)
                    customer_id = cust_res['customer_id']
                
                # Update customer's default payment method
                stripe.Customer.modify(
                    customer_id,
                    invoice_settings={'default_payment_method': payment_method.gateway_payment_method_id}
                )
                
                # 2. Create subscription
                sub_res = service.create_subscription(
                    customer_id=customer_id,
                    amount=data['amount'],
                    frequency=data['frequency'],
                    metadata=subscription_metadata
                )
                
                if not sub_res['success']:
                    return Response({'error': sub_res['error']}, status=400)
                
                enrollment = AutoPayEnrollment.objects.create(
                    user=request.user,
                    gateway=gateway,
                    payment_method=payment_method,
                    enrollment_type=data['enrollment_type'],
                    frequency=data['frequency'],
                    amount=data['amount'],
                    mandate_limit_amount=data.get('mandate_limit_amount') or data['amount'],
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=sub_res['subscription_id'],
                    start_date=data['start_date'],
                    next_payment_date=data['start_date'],
                    billing_day=data['billing_day'],
                    notify_before_days=data.get('notify_before_days', 3),
                    description=data.get('description', ''),
                    status='active' if sub_res['status'] == 'active' else 'pending'
                )
                
                return Response({
                    'message': 'Stripe auto-pay enrolled successfully',
                    'enrollment': AutoPayEnrollmentSerializer(enrollment).data,
                    'stripe': sub_res
                }, status=status.HTTP_201_CREATED)
                
            except Exception as e:
                return Response({'error': f'Stripe enrollment failed: {str(e)}'}, status=400)

        return Response({'error': 'Gateway not supported for auto-pay enrollment.'}, status=status.HTTP_400_BAD_REQUEST)

    
    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Pause auto-pay enrollment"""
        enrollment = self.get_object()

        if enrollment.status != 'active':
            return Response({'error': 'Can only pause active enrollments'},
                          status=status.HTTP_400_BAD_REQUEST)

        # Pause subscription based on gateway type
        if enrollment.gateway.gateway_type == 'razorpay':
            return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
        elif enrollment.gateway.gateway_type == 'stripe':
            from .services.stripe_autopay_service import StripeAutoPayService
            stripe_service = StripeAutoPayService(enrollment.gateway)
            result = stripe_service.pause(enrollment.stripe_subscription_id)
        else:
            return Response({'error': 'Gateway not supported.'}, status=status.HTTP_400_BAD_REQUEST)


        if result['success']:
            enrollment.status = 'paused'
            enrollment.paused_at = timezone.now()
            enrollment.paused_reason = request.data.get('reason', '')
            enrollment.save()

            return Response({
                'message': 'Auto-pay paused successfully',
                'enrollment': AutoPayEnrollmentSerializer(enrollment).data
            })

        return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """Resume paused auto-pay enrollment"""
        enrollment = self.get_object()

        if enrollment.status != 'paused':
            return Response({'error': 'Can only resume paused enrollments'},
                          status=status.HTTP_400_BAD_REQUEST)

        # Resume subscription based on gateway type
        if enrollment.gateway.gateway_type == 'razorpay':
            return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
        elif enrollment.gateway.gateway_type == 'stripe':
            from .services.stripe_autopay_service import StripeAutoPayService
            stripe_service = StripeAutoPayService(enrollment.gateway)
            result = stripe_service.resume(enrollment.stripe_subscription_id)
        else:
            return Response({'error': 'Gateway not supported.'}, status=status.HTTP_400_BAD_REQUEST)


        if result['success']:
            enrollment.status = 'active'
            enrollment.paused_at = None
            enrollment.paused_reason = ''
            enrollment.save()

            return Response({
                'message': 'Auto-pay resumed successfully',
                'enrollment': AutoPayEnrollmentSerializer(enrollment).data
            })

        return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel auto-pay enrollment"""
        enrollment = self.get_object()

        if enrollment.status == 'cancelled':
            return Response({'error': 'Enrollment already cancelled'},
                          status=status.HTTP_400_BAD_REQUEST)

        cancel_immediately = request.data.get('cancel_immediately', False)

        # Attempt to cancel on the gateway
        gateway_error = None
        if enrollment.gateway.gateway_type == 'razorpay':
            return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
        elif enrollment.gateway.gateway_type == 'stripe' and enrollment.stripe_subscription_id:
            from .services.stripe_autopay_service import StripeAutoPayService
            stripe_service = StripeAutoPayService(enrollment.gateway)
            # Stripe cancel (delete) is immediate by default in our service
            result = stripe_service.cancel(enrollment.stripe_subscription_id)
            if not result['success']:
                gateway_error = result.get('error')

        # Always mark the enrollment as cancelled locally
        enrollment.status = 'cancelled'
        enrollment.cancelled_at = timezone.now()
        enrollment.cancellation_reason = request.data.get('reason', '')
        enrollment.save()

        return Response({
            'message': 'Auto-pay cancelled successfully',
            'enrollment': AutoPayEnrollmentSerializer(enrollment).data,
            'cancel_at_period_end': not cancel_immediately,
            'gateway_error': gateway_error,
        })

    @action(detail=True, methods=['post'])
    def confirm_mandate(self, request, pk=None):
        """Confirm mandate authorization (Razorpay is permanently disabled)"""
        return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def update_amount(self, request, pk=None):
        """Update auto-pay amount"""
        enrollment = self.get_object()
        new_amount = request.data.get('amount')

        if not new_amount:
            return Response({'error': 'Amount is required'},
                          status=status.HTTP_400_BAD_REQUEST)

        # Update subscription amount based on gateway type
        if enrollment.gateway.gateway_type == 'razorpay':
            return Response({'error': 'Razorpay payment gateway is not supported.'}, status=status.HTTP_400_BAD_REQUEST)
        elif enrollment.gateway.gateway_type == 'stripe':
            try:
                if stripe is None:
                    return Response({'error': 'Stripe library is not installed'}, status=status.HTTP_400_BAD_REQUEST)
                
                platform_secret, _ = get_platform_keys()
                api_key = enrollment.gateway.secret_key
                if enrollment.gateway.stripe_connected_account_id or not api_key:
                    api_key = platform_secret
                
                stripe.api_key = api_key
                # In Stripe, we usually update the subscription item with a new price
                # Simplified: modify subscription (this might need a more complex price logic)
                result = {'success': True} # Placeholder for complex price migration logic
            except Exception as e:
                result = {'success': False, 'error': str(e)}
        else:
            return Response({'error': 'Gateway not supported.'}, status=status.HTTP_400_BAD_REQUEST)


        return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def update_payment_method(self, request, pk=None):
        """Update payment method for auto-pay"""
        enrollment = self.get_object()
        payment_method_id = request.data.get('payment_method_id')

        if not payment_method_id:
            return Response({'error': 'Payment method ID is required'},
                          status=status.HTTP_400_BAD_REQUEST)

        try:
            new_payment_method = PaymentMethod.objects.get(id=payment_method_id, user=request.user)
        except PaymentMethod.DoesNotExist:
            return Response({'error': 'Invalid payment method'},
                          status=status.HTTP_404_NOT_FOUND)

        try:
            if enrollment.gateway.gateway_type == 'stripe':
                # Update payment method for Stripe
                enrollment.payment_method = new_payment_method
                enrollment.save()
            else:
                return Response({'error': 'Gateway not supported.'}, status=status.HTTP_400_BAD_REQUEST)

            return Response({
                'message': 'Payment method updated successfully',
                'enrollment': AutoPayEnrollmentSerializer(enrollment).data
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def my_enrollments(self, request):
        """Get user's auto-pay enrollments"""
        enrollments = self.get_queryset().filter(user=request.user)
        serializer = self.get_serializer(enrollments, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def payment_history(self, request, pk=None):
        """Get payment history for enrollment"""
        enrollment = self.get_object()
        logs = AutoPaymentLog.objects.filter(enrollment=enrollment).order_by('-scheduled_date')
        serializer = AutoPaymentLogSerializer(logs, many=True)
        return Response(serializer.data)


class AutoPaymentLogViewSet(ModulePermissionMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing auto-payment logs"""
    module = 'payments'
    queryset = AutoPaymentLog.objects.all().select_related('enrollment', 'enrollment__user', 'payment')
    serializer_class = AutoPaymentLogSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'enrollment']
    ordering = ['-scheduled_date']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(enrollment__user=self.request.user)
        return queryset


class RecurringInvoiceViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """ViewSet for managing recurring invoices"""
    module = 'payments'
    queryset = RecurringInvoice.objects.all().select_related('user', 'autopay_enrollment')
    serializer_class = RecurringInvoiceSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'frequency', 'user']
    ordering = ['-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        return queryset
    
    @action(detail=True, methods=['post'])
    def enable_autopay(self, request, pk=None):
        """Enable auto-pay for recurring invoice"""
        recurring_invoice = self.get_object()
        enrollment_id = request.data.get('enrollment_id')
        
        try:
            enrollment = AutoPayEnrollment.objects.get(
                id=enrollment_id,
                user=request.user,
                status='active'
            )
        except AutoPayEnrollment.DoesNotExist:
            return Response({'error': 'Invalid or inactive enrollment'}, 
                          status=status.HTTP_404_NOT_FOUND)
        
        recurring_invoice.auto_pay_enabled = True
        recurring_invoice.autopay_enrollment = enrollment
        recurring_invoice.save()
        
        return Response({
            'message': 'Auto-pay enabled for recurring invoice',
            'recurring_invoice': RecurringInvoiceSerializer(recurring_invoice).data
        })

@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def webhook_stripe(request):
    """Handle Stripe webhooks for one-time payments and subscriptions"""
    from django_tenants.utils import schema_context
    from payments.models import WebhookEventLog
    
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    # Get webhook secret from settings or DB
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)
    if not webhook_secret or webhook_secret == 'whsec_test_placeholder':
        try:
            gateway = PaymentGateway.objects.get(gateway_type='stripe', is_active=True)
            webhook_secret = gateway.webhook_secret
        except PaymentGateway.DoesNotExist:
            return Response({'error': 'Stripe gateway not configured'}, 
                          status=status.HTTP_404_NOT_FOUND)

    try:
        if stripe is None:
            return Response({'error': 'Stripe library is not installed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        # Invalid payload
        return Response({'error': 'Invalid payload'}, status=status.HTTP_400_BAD_REQUEST)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)

    # Idempotency check
    with schema_context('public'):
        if WebhookEventLog.objects.filter(stripe_event_id=event['id']).exists():
            return Response({'status': 'success', 'message': 'already processed'})
            
        WebhookEventLog.objects.create(
            stripe_event_id=event['id'],
            event_type=event['type'],
            payload=event
        )

    # Resolve tenant schema name
    metadata = event['data']['object'].get('metadata', {})
    tenant_schema = metadata.get('tenant_schema')
    
    if not tenant_schema:
        connected_acct = metadata.get('connected_acct') or event['data']['object'].get('transfer_data', {}).get('destination')
        if connected_acct:
            from tenants.models import Client
            with schema_context('public'):
                clients = Client.objects.exclude(schema_name='public')
                for c in clients:
                    with schema_context(c.schema_name):
                        if PaymentGateway.objects.filter(stripe_connected_account_id=connected_acct).exists():
                            tenant_schema = c.schema_name
                            break
                            
    if not tenant_schema:
        from django.db import connection
        tenant_schema = getattr(connection, 'schema_name', 'public')

    with schema_context(tenant_schema):
        # Handle the event
        if event['type'] == 'payment_intent.succeeded':
            intent = event['data']['object']
            payment_id = intent.get('metadata', {}).get('payment_id')
            
            if payment_id:
                try:
                    payment = Payment.objects.get(id=payment_id)
                    from payments.services.stripe_service import StripeService
                    service = StripeService(payment.gateway)
                    service.process_successful_payment(intent.id, intent_data=intent)
                    
                    # Create transaction record if not exists
                    if not Transaction.objects.filter(payment=payment, transaction_type='payment').exists():
                        Transaction.objects.create(
                            transaction_type='payment',
                            user=payment.user,
                            payment=payment,
                            amount=payment.amount,
                            currency=payment.currency,
                            description=f'Payment succeeded via Stripe - {payment.payment_number}',
                            metadata={'stripe_intent_id': intent.id}
                        )
                except Payment.DoesNotExist:
                    logger.error(f"Stripe webhook: Payment {payment_id} not found in schema {tenant_schema}")

        elif event['type'] == 'payment_intent.payment_failed':
            intent = event['data']['object']
            payment_id = intent.get('metadata', {}).get('payment_id')
            if payment_id:
                try:
                    payment = Payment.objects.get(id=payment_id)
                    old_status = payment.status
                    payment.status = 'failed'
                    payment.failed_at = timezone.now()
                    payment.failure_reason = intent.get('last_payment_error', {}).get('message', 'Payment failed')
                    payment.save()

                    # Revert invoice if it was processing
                    if payment.invoice:
                        invoice = payment.invoice
                        if invoice.status == 'processing':
                            invoice.status = 'sent'
                            invoice.save()
                        elif invoice.status == 'paid' and old_status == 'completed':
                            # In case it was prematurely marked completed before the fix
                            invoice.amount_paid = max(Decimal('0.00'), Decimal(str(invoice.amount_paid or 0)) - Decimal(str(payment.amount or 0)))
                            invoice.status = 'sent'
                            invoice.paid_at = None
                            invoice.save()
                except Payment.DoesNotExist:
                    pass

        elif event['type'] == 'charge.refunded':
            charge = event['data']['object']
            intent_id = charge.get('payment_intent')
            if intent_id:
                try:
                    payment = Payment.objects.get(gateway_payment_id=intent_id)
                    refunds = charge.get('refunds', {}).get('data', [])
                    if refunds:
                        latest_refund = refunds[0]
                        refund_amount = Decimal(str(latest_refund.get('amount', 0))) / 100
                        payment.status = 'refunded'
                        payment.refund_amount = refund_amount
                        payment.refunded_at = timezone.now()
                        payment.save()
                        
                        if payment.invoice:
                            invoice = payment.invoice
                            invoice.status = 'refunded'
                            invoice.save()
                            
                        # Update/create Refund model record if not exists
                        from payments.models import Refund
                        Refund.objects.update_or_create(
                            payment=payment,
                            gateway_refund_id=latest_refund.id,
                            defaults={
                                'amount': refund_amount,
                                'reason': latest_refund.get('reason') or 'Refunded via Stripe Dashboard',
                                'status': 'completed',
                                'processed_at': timezone.now(),
                            }
                        )
                except Payment.DoesNotExist:
                    pass

        elif event['type'] == 'charge.dispute.created':
            dispute = event['data']['object']
            intent_id = dispute.get('payment_intent')
            if intent_id:
                try:
                    payment = Payment.objects.get(gateway_payment_id=intent_id)
                    payment.status = 'failed'
                    payment.failure_reason = f"Payment disputed: {dispute.get('reason')}"
                    payment.save()
                    
                    if payment.invoice:
                        payment.invoice.status = 'overdue'
                        payment.invoice.save()
                        
                    try:
                        NotificationService.send(
                            user=payment.user,
                            title='Dispute Opened on Payment',
                            message=f"A dispute has been opened on your payment {payment.payment_number} for amount ${payment.amount}.",
                            notification_type='payment',
                            priority='high',
                            send_email=True
                        )
                    except Exception as e:
                        logger.error(f"Error sending dispute notification: {e}")
                except Payment.DoesNotExist:
                    pass

    return Response({'status': 'success'})


