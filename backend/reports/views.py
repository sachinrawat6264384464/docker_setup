# reports/views.py
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.db.models import Count, Q, Sum, Avg, ExpressionWrapper, DurationField, F
import csv
import io
import json
import logging

logger = logging.getLogger(__name__)

from accounts.permissions import ModulePermissionMixin, HasModulePermission
from .models import ReportTemplate, GeneratedReport, ScheduledReport
from .serializers import (
    ReportTemplateSerializer, GeneratedReportSerializer,
    GenerateReportSerializer, ScheduledReportSerializer,
)


# ─────────────────────────────────────────────────────────────────
#  DATA COLLECTORS  (one per report type)
# ─────────────────────────────────────────────────────────────────

def _collect_financial_data(date_from, date_to, building_filter=None):
    """Return structured financial data within the date range."""
    from django.db import connection
    from payments.models import Payment, Invoice

    # CRITICAL: If we are in the public schema, payments tables might not exist
    # or should not be accessed directly for resident invoices.
    is_public = connection.schema_name == 'public'
    
    if is_public:
        # For public schema, we should ideally query Platform Invoices 
        # or return empty data to prevent crash
        return {
            'summary': {
                'Completed payments (count)': 0,
                'Completed payments (total amount)': '0.00',
                'Invoices issued in period': 0,
                'Outstanding amount due (open invoices)': '0.00',
                'Overdue invoices (count)': 0,
                'Overdue amount due': '0.00',
            },
            'status_breakdown': [],
            'transactions': [],
        }

    pay_qs = Payment.objects.filter(created_at__date__gte=date_from, created_at__date__lte=date_to)
    inv_qs = Invoice.objects.filter(issue_date__gte=date_from, issue_date__lte=date_to)

    if building_filter:
        pay_qs = pay_qs.filter(invoice__building=building_filter)
        inv_qs = inv_qs.filter(building=building_filter)

    completed_payments = pay_qs.filter(status='completed')
    completed_count = completed_payments.count()
    completed_total = completed_payments.aggregate(s=Sum('amount'))['s'] or 0

    inv_total = inv_qs.count()
    outstanding = inv_qs.exclude(status='paid').aggregate(s=Sum('amount_due'))['s'] or 0
    overdue_qs  = inv_qs.filter(status='overdue')
    overdue_count  = overdue_qs.count()
    overdue_amount = overdue_qs.aggregate(s=Sum('amount_due'))['s'] or 0

    # Invoice-by-status breakdown
    status_breakdown = list(
        inv_qs.values('status').annotate(count=Count('id')).order_by('status')
    )

    # All payment transactions (log)
    transactions = list(
        pay_qs.select_related('user', 'invoice', 'gateway')
               .order_by('created_at')
               .values(
                   'payment_number', 'created_at',
                   'user__first_name', 'user__last_name',
                   'invoice__invoice_number', 'invoice__building',
                   'payment_method', 'status',
                   'amount', 'gateway__gateway_type',
                   'gateway_transaction_id', 'gateway_order_id',
               )
    )

    return {
        'summary': {
            'Completed payments (count)':       completed_count,
            'Completed payments (total amount)': f'{float(completed_total):.2f}',
            'Invoices issued in period':          inv_total,
            'Outstanding amount due (open invoices)': f'{float(outstanding):.2f}',
            'Overdue invoices (count)':           overdue_count,
            'Overdue amount due':                 f'{float(overdue_amount):.2f}',
        },
        'status_breakdown': status_breakdown,
        'transactions': transactions,
    }


def _collect_occupancy_data(date_from, date_to, building_filter=None):
    """Return unit occupancy data."""
    from django.db import connection
    from properties.models import Unit, Building, Lease

    if connection.schema_name == 'public':
        return {
            'summary': {
                'Total units': 0, 'Occupied (tenant)': 0, 'Owner occupied': 0,
                'Vacant': 0, 'Overall occupancy rate (%)': '0%',
                'Active leases in period': 0, 'Leases expiring by end date': 0,
            },
            'building_breakdown': [],
            'lease_log': [],
        }

    unit_qs = Unit.objects.select_related('building')
    if building_filter:
        unit_qs = unit_qs.filter(building__name=building_filter)

    total      = unit_qs.count()
    occupied   = unit_qs.filter(unit_type='tenant_occupied').count()
    owner_occ  = unit_qs.filter(unit_type='owner_occupied').count()
    vacant     = unit_qs.filter(unit_type='vacant').count()
    occ_rate   = round((occupied + owner_occ) / total * 100, 2) if total else 0

    # Active leases in period
    lease_qs = Lease.objects.filter(
        start_date__lte=date_to,
        end_date__gte=date_from,
    ).select_related('unit', 'unit__building', 'tenant')

    if building_filter:
        lease_qs = lease_qs.filter(unit__building__name=building_filter)

    expiring_soon = Lease.objects.filter(
        status='active',
        end_date__lte=date_to,
    )
    if building_filter:
        expiring_soon = expiring_soon.filter(unit__building__name=building_filter)

    # Per-building breakdown
    bldg_breakdown = list(
        unit_qs.values('building__name')
               .annotate(
                   total=Count('id'),
                   occupied=Count('id', filter=Q(unit_type='tenant_occupied')),
                   owner=Count('id', filter=Q(unit_type='owner_occupied')),
                   vacant=Count('id', filter=Q(unit_type='vacant')),
               )
               .order_by('building__name')
    )

    # Lease detail log
    lease_log = list(
        lease_qs.values(
            'unit__unit_number', 'unit__building__name',
            'tenant__first_name', 'tenant__last_name',
            'start_date', 'end_date', 'status',
            'monthly_rent', 'security_deposit',
        ).order_by('unit__building__name', 'unit__unit_number')
    )

    return {
        'summary': {
            'Total units':                total,
            'Occupied (tenant)':          occupied,
            'Owner occupied':             owner_occ,
            'Vacant':                     vacant,
            'Overall occupancy rate (%)': f'{occ_rate}%',
            'Active leases in period':    lease_qs.count(),
            'Leases expiring by end date': expiring_soon.count(),
        },
        'building_breakdown': bldg_breakdown,
        'lease_log': lease_log,
    }


def _collect_maintenance_data(date_from, date_to, building_filter=None):
    """Return maintenance request data."""
    from django.db import connection
    from maintenance.models import MaintenanceRequest

    if connection.schema_name == 'public':
        return {
            'summary': {
                'Total requests in period': 0, 'Open (unresolved)': 0,
                'Completed': 0, 'Cancelled': 0, 'High/Urgent priority': 0,
                'Avg resolution time (hrs)': 'N/A', 'Total maintenance cost': '0.00',
            },
            'category_breakdown': [],
            'status_breakdown': [],
            'request_log': [],
        }

    mq = MaintenanceRequest.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    if building_filter:
        mq = mq.filter(building=building_filter)

    # Single aggregate query for all summary counts + total cost
    agg = mq.aggregate(
        total=Count('id'),
        open_count=Count('id', filter=~Q(status__in=['completed', 'cancelled'])),
        completed=Count('id', filter=Q(status='completed')),
        cancelled=Count('id', filter=Q(status='cancelled')),
        high_prio=Count('id', filter=Q(priority__in=['high', 'urgent'])),
        total_cost=Sum('total_cost'),
    )
    total      = agg['total']
    open_count = agg['open_count']
    completed  = agg['completed']
    cancelled  = agg['cancelled']
    high_prio  = agg['high_prio']
    total_cost = agg['total_cost'] or 0

    # Avg resolution time via DB-level duration (no Python loop)
    avg_hours = None
    avg_agg = mq.filter(
        status='completed',
        completed_date__isnull=False,
        requested_date__isnull=False,
    ).aggregate(
        avg_dur=Avg(
            ExpressionWrapper(
                F('completed_date') - F('requested_date'),
                output_field=DurationField(),
            )
        )
    )
    if avg_agg['avg_dur'] is not None:
        avg_hours = round(avg_agg['avg_dur'].total_seconds() / 3600, 1)

    # Category breakdown
    category_breakdown = list(
        mq.values('category').annotate(count=Count('id')).order_by('-count')
    )

    # Status breakdown
    status_breakdown = list(
        mq.values('status').annotate(count=Count('id')).order_by('status')
    )

    # Detail log
    req_log = list(
        mq.select_related('requested_by', 'assigned_to')
           .order_by('created_at')
           .values(
               'request_number', 'created_at',
               'building', 'unit_number',
               'category', 'priority', 'status',
               'title',
               'requested_by__first_name', 'requested_by__last_name',
               'assigned_to__first_name', 'assigned_to__last_name',
               'total_cost', 'completed_date',
           )
    )

    return {
        'summary': {
            'Total requests in period': total,
            'Open (unresolved)':        open_count,
            'Completed':                completed,
            'Cancelled':                cancelled,
            'High/Urgent priority':     high_prio,
            'Avg resolution time (hrs)': str(avg_hours) if avg_hours else 'N/A',
            'Total maintenance cost':   f'{float(total_cost):.2f}',
        },
        'category_breakdown': category_breakdown,
        'status_breakdown': status_breakdown,
        'request_log': req_log,
    }


def _collect_compliance_data(date_from, date_to, building_filter=None):
    """Return compliance/audit data."""
    from properties.models import Unit, Lease, PropertyDocument

    unit_qs = Unit.objects.select_related('building')
    if building_filter:
        unit_qs = unit_qs.filter(building__name=building_filter)

    # Lease compliance
    total_units   = unit_qs.count()
    active_leases = Lease.objects.filter(status='active')
    expired_leases = Lease.objects.filter(status='expired', end_date__gte=date_from, end_date__lte=date_to)
    unsigned_leases = Lease.objects.filter(status='active', agreement_signed=False)

    if building_filter:
        active_leases   = active_leases.filter(unit__building__name=building_filter)
        expired_leases  = expired_leases.filter(unit__building__name=building_filter)
        unsigned_leases = unsigned_leases.filter(unit__building__name=building_filter)

    # Document audit
    doc_qs = PropertyDocument.objects.filter(uploaded_at__date__gte=date_from, uploaded_at__date__lte=date_to)
    if building_filter:
        doc_qs = doc_qs.filter(building__name=building_filter)

    doc_breakdown = list(
        doc_qs.values('document_type').annotate(count=Count('id')).order_by('document_type')
    )

    # Unsigned lease log
    unsigned_log = list(
        unsigned_leases.select_related('unit', 'unit__building', 'tenant')
                        .values(
                            'unit__unit_number', 'unit__building__name',
                            'tenant__first_name', 'tenant__last_name',
                            'start_date', 'end_date',
                        )
    )

    # Expired lease log
    expired_log = list(
        expired_leases.select_related('unit', 'unit__building', 'tenant')
                       .values(
                           'unit__unit_number', 'unit__building__name',
                           'tenant__first_name', 'tenant__last_name',
                           'end_date', 'status',
                       )
    )

    # Batch count to avoid repeated DB hits
    counts = {
        'active_leases':    active_leases.count(),
        'expired_leases':   expired_leases.count(),
        'unsigned_leases':  unsigned_leases.count(),
        'doc_count':        doc_qs.count(),
    }

    return {
        'summary': {
            'Total units':              total_units,
            'Active leases':            counts['active_leases'],
            'Expired leases in period': counts['expired_leases'],
            'Unsigned active leases':   counts['unsigned_leases'],
            'Documents uploaded in period': counts['doc_count'],
        },
        'document_breakdown': doc_breakdown,
        'unsigned_leases': unsigned_log,
        'expired_leases': expired_log,
    }


def _collect_report_data(report):
    """Dispatch to the right collector based on report_type."""
    date_from = report.date_from
    date_to   = report.date_to
    building  = (report.parameters or {}).get('building') or None

    if report.report_type == 'financial':
        return _collect_financial_data(date_from, date_to, building)
    if report.report_type == 'occupancy':
        return _collect_occupancy_data(date_from, date_to, building)
    if report.report_type == 'maintenance':
        return _collect_maintenance_data(date_from, date_to, building)
    if report.report_type == 'compliance':
        return _collect_compliance_data(date_from, date_to, building)
    return {}


# ─────────────────────────────────────────────────────────────────
#  FORMATTERS  (PDF / XLSX / CSV / JSON)
# ─────────────────────────────────────────────────────────────────

def _fmt_date(d):
    if not d:
        return ''
    try:
        return str(d)[:10]
    except Exception:
        return str(d)


def _fmt_dt(dt):
    if not dt:
        return ''
    try:
        return str(dt)[:16].replace('T', ' ')
    except Exception:
        return str(dt)


def _build_pdf(report, request_user, data):
    """Build a multi-section PDF exactly matching the sample layout."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=12*mm, bottomMargin=12*mm,
    )
    W = landscape(A4)[0] - 30*mm   # usable width

    styles = getSampleStyleSheet()
    title_style   = ParagraphStyle('title',   fontSize=18, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=4)
    sub_style     = ParagraphStyle('sub',     fontSize=9,  fontName='Helvetica',       alignment=TA_CENTER, textColor=colors.HexColor('#555555'), spaceAfter=8)
    section_style = ParagraphStyle('section', fontSize=12, fontName='Helvetica-Bold', spaceBefore=12, spaceAfter=4)
    body_style    = ParagraphStyle('body',    fontSize=8,  fontName='Helvetica')

    # ── header colours
    DARK    = colors.HexColor('#14213D')
    GOLD    = colors.HexColor('#EAB308')
    LIGHT   = colors.HexColor('#F3F4F6')
    WHITE   = colors.white

    def header_table_style():
        return TableStyle([
            ('BACKGROUND', (0,0), (-1,0), DARK),
            ('TEXTCOLOR',  (0,0), (-1,0), WHITE),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,0), 8),
            ('BACKGROUND', (0,1), (-1,-1), WHITE),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, LIGHT]),
            ('FONTSIZE',   (0,1), (-1,-1), 7.5),
            ('FONTNAME',   (0,1), (-1,-1), 'Helvetica'),
            ('GRID',       (0,0), (-1,-1), 0.4, colors.HexColor('#DDDDDD')),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
            ('VALIGN',    (0,0), (-1,-1), 'MIDDLE'),
        ])

    def gold_header_style():
        return TableStyle([
            ('BACKGROUND', (0,0), (-1,0), GOLD),
            ('TEXTCOLOR',  (0,0), (-1,0), DARK),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,0), 8),
            ('BACKGROUND', (0,1), (-1,-1), WHITE),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [WHITE, LIGHT]),
            ('FONTSIZE',   (0,1), (-1,-1), 7.5),
            ('FONTNAME',   (0,1), (-1,-1), 'Helvetica'),
            ('GRID',       (0,0), (-1,-1), 0.4, colors.HexColor('#DDDDDD')),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
            ('VALIGN',    (0,0), (-1,-1), 'MIDDLE'),
        ])

    story = []
    rtype = report.report_type.title()

    # ── Title
    story.append(Paragraph(f'{rtype} Report', title_style))
    building_label = (report.parameters or {}).get('building') or 'All buildings'
    story.append(Paragraph(
        f'Type: {report.report_type} &nbsp;|&nbsp; Period: {_fmt_date(report.date_from)} to {_fmt_date(report.date_to)}',
        sub_style
    ))
    story.append(HRFlowable(width='100%', thickness=1, color=DARK))
    story.append(Spacer(1, 5))

    # ── Report info table
    info_rows = [
        ['Field', 'Value'],
        ['Report name',   report.name],
        ['Report type',   report.report_type],
        ['Date from',     _fmt_date(report.date_from)],
        ['Date to',       _fmt_date(report.date_to)],
        ['Scope',         building_label],
        ['Report number', report.report_number or '-'],
        ['Generated by',  request_user.email if request_user else '-'],
    ]
    t = Table(info_rows, colWidths=[W*0.3, W*0.7])
    t.setStyle(header_table_style())
    story.append(t)
    story.append(Spacer(1, 8))

    # ── Type-specific sections
    if report.report_type == 'financial':
        summary = data.get('summary', {})
        story.append(Paragraph('Financial summary', section_style))
        sum_rows = [['Metric', 'Value']] + [[k, str(v)] for k, v in summary.items()]
        t = Table(sum_rows, colWidths=[W*0.6, W*0.4])
        t.setStyle(gold_header_style())
        story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('Invoices in period by status', section_style))
        sb = data.get('status_breakdown', [])
        if sb:
            sb_rows = [['Status', 'Count']] + [[r['status'], str(r['count'])] for r in sb]
            t = Table(sb_rows, colWidths=[W*0.5, W*0.5])
            t.setStyle(gold_header_style())
            story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('All transactions in period', section_style))
        txns = data.get('transactions', [])
        if txns:
            hdr = ['Payment #', 'Created at', 'Resident', 'Invoice #', 'Method', 'Status', 'Amount', 'Gateway', 'Gateway Ref']
            rows = [hdr]
            for tx in txns:
                bldg = (tx.get('invoice__building') or '')
                pay_num = (tx.get('payment_number') or '')
                label = f"{bldg}:\n{pay_num}" if bldg else pay_num
                rows.append([
                    label,
                    _fmt_dt(tx.get('created_at')),
                    f"{tx.get('user__first_name','')} {tx.get('user__last_name','')}".strip(),
                    tx.get('invoice__invoice_number') or '-',
                    tx.get('payment_method') or '-',
                    tx.get('status') or '-',
                    str(tx.get('amount') or '0'),
                    tx.get('gateway__gateway_type') or '-',
                    (tx.get('gateway_transaction_id') or tx.get('gateway_order_id') or '-')[:20],
                ])
            col_w = [W*0.14, W*0.1, W*0.1, W*0.12, W*0.12, W*0.1, W*0.08, W*0.1, W*0.14]
            t = Table(rows, colWidths=col_w, repeatRows=1)
            t.setStyle(gold_header_style())
            story.append(t)
        else:
            story.append(Paragraph('No transactions in this period.', body_style))

    elif report.report_type == 'occupancy':
        summary = data.get('summary', {})
        story.append(Paragraph('Occupancy Summary', section_style))
        sum_rows = [['Metric', 'Value']] + [[k, str(v)] for k, v in summary.items()]
        t = Table(sum_rows, colWidths=[W*0.6, W*0.4])
        t.setStyle(gold_header_style())
        story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('Occupancy by Building', section_style))
        bb = data.get('building_breakdown', [])
        if bb:
            hdr = ['Building', 'Total', 'Tenant Occupied', 'Owner Occupied', 'Vacant']
            rows = [hdr] + [
                [r.get('building__name',''), str(r.get('total',0)), str(r.get('occupied',0)),
                 str(r.get('owner',0)), str(r.get('vacant',0))]
                for r in bb
            ]
            t = Table(rows, colWidths=[W*0.4, W*0.15, W*0.15, W*0.15, W*0.15])
            t.setStyle(gold_header_style())
            story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('Active Lease Log', section_style))
        ll = data.get('lease_log', [])
        if ll:
            hdr = ['Building', 'Unit', 'Tenant', 'Start Date', 'End Date', 'Status', 'Monthly Rent (₹)']
            rows = [hdr]
            for r in ll:
                rows.append([
                    r.get('unit__building__name',''),
                    r.get('unit__unit_number',''),
                    f"{r.get('tenant__first_name','')} {r.get('tenant__last_name','')}".strip(),
                    _fmt_date(r.get('start_date')),
                    _fmt_date(r.get('end_date')),
                    r.get('status',''),
                    str(r.get('monthly_rent') or '-'),
                ])
            col_w = [W*0.22, W*0.1, W*0.18, W*0.12, W*0.12, W*0.12, W*0.14]
            t = Table(rows, colWidths=col_w, repeatRows=1)
            t.setStyle(gold_header_style())
            story.append(t)
        else:
            story.append(Paragraph('No leases found for this period.', body_style))

    elif report.report_type == 'maintenance':
        summary = data.get('summary', {})
        story.append(Paragraph('Maintenance Summary', section_style))
        sum_rows = [['Metric', 'Value']] + [[k, str(v)] for k, v in summary.items()]
        t = Table(sum_rows, colWidths=[W*0.6, W*0.4])
        t.setStyle(gold_header_style())
        story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('Requests by Category', section_style))
        cb = data.get('category_breakdown', [])
        if cb:
            rows = [['Category', 'Count']] + [[r['category'], str(r['count'])] for r in cb]
            t = Table(rows, colWidths=[W*0.6, W*0.4])
            t.setStyle(gold_header_style())
            story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('Requests by Status', section_style))
        sb = data.get('status_breakdown', [])
        if sb:
            rows = [['Status', 'Count']] + [[r['status'], str(r['count'])] for r in sb]
            t = Table(rows, colWidths=[W*0.6, W*0.4])
            t.setStyle(gold_header_style())
            story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('All Maintenance Requests', section_style))
        rl = data.get('request_log', [])
        if rl:
            hdr = ['Request #', 'Raised On', 'Building', 'Unit', 'Category', 'Priority', 'Status', 'Title', 'Resident', 'Assigned To', 'Cost (₹)', 'Completed']
            rows = [hdr]
            for r in rl:
                rows.append([
                    r.get('request_number',''),
                    _fmt_dt(r.get('created_at')),
                    r.get('building',''),
                    r.get('unit_number',''),
                    r.get('category',''),
                    r.get('priority',''),
                    r.get('status',''),
                    (r.get('title') or '')[:35],
                    f"{r.get('requested_by__first_name','')} {r.get('requested_by__last_name','')}".strip(),
                    f"{r.get('assigned_to__first_name') or ''} {r.get('assigned_to__last_name') or ''}".strip() or '-',
                    str(r.get('total_cost') or '0'),
                    _fmt_dt(r.get('completed_date')),
                ])
            col_w = [W*0.09, W*0.09, W*0.10, W*0.06, W*0.08, W*0.07, W*0.07, W*0.14, W*0.10, W*0.10, W*0.07, W*0.09]
            t = Table(rows, colWidths=col_w, repeatRows=1)
            t.setStyle(gold_header_style())
            story.append(t)
        else:
            story.append(Paragraph('No maintenance requests in this period.', body_style))

    elif report.report_type == 'compliance':
        summary = data.get('summary', {})
        story.append(Paragraph('Compliance Summary', section_style))
        sum_rows = [['Metric', 'Value']] + [[k, str(v)] for k, v in summary.items()]
        t = Table(sum_rows, colWidths=[W*0.6, W*0.4])
        t.setStyle(gold_header_style())
        story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('Documents Uploaded by Type', section_style))
        db = data.get('document_breakdown', [])
        if db:
            rows = [['Document Type', 'Count']] + [[r['document_type'], str(r['count'])] for r in db]
            t = Table(rows, colWidths=[W*0.6, W*0.4])
            t.setStyle(gold_header_style())
            story.append(t)
        story.append(Spacer(1, 8))

        story.append(Paragraph('Unsigned Active Leases', section_style))
        ul = data.get('unsigned_leases', [])
        if ul:
            hdr = ['Building', 'Unit', 'Tenant', 'Start Date', 'End Date']
            rows = [hdr]
            for r in ul:
                rows.append([
                    r.get('unit__building__name',''),
                    r.get('unit__unit_number',''),
                    f"{r.get('tenant__first_name','')} {r.get('tenant__last_name','')}".strip(),
                    _fmt_date(r.get('start_date')),
                    _fmt_date(r.get('end_date')),
                ])
            t = Table(rows, colWidths=[W*0.25, W*0.12, W*0.25, W*0.19, W*0.19])
            t.setStyle(gold_header_style())
            story.append(t)
        else:
            story.append(Paragraph('All active leases are signed. ✓', body_style))

        story.append(Spacer(1, 8))
        story.append(Paragraph('Expired Leases in Period', section_style))
        el = data.get('expired_leases', [])
        if el:
            hdr = ['Building', 'Unit', 'Tenant', 'Expired On', 'Status']
            rows = [hdr]
            for r in el:
                rows.append([
                    r.get('unit__building__name',''),
                    r.get('unit__unit_number',''),
                    f"{r.get('tenant__first_name','')} {r.get('tenant__last_name','')}".strip(),
                    _fmt_date(r.get('end_date')),
                    r.get('status',''),
                ])
            t = Table(rows, colWidths=[W*0.25, W*0.12, W*0.25, W*0.19, W*0.19])
            t.setStyle(gold_header_style())
            story.append(t)
        else:
            story.append(Paragraph('No expired leases in this period.', body_style))

    else:
        story.append(Paragraph('No detailed data available for this report type.', body_style))

    doc.build(story)
    buf.seek(0)
    return buf.read(), 'pdf'


def _build_xlsx(report, request_user, data):
    """Build multi-sheet Excel report."""
    import xlsxwriter
    buf = io.BytesIO()
    wb  = xlsxwriter.Workbook(buf, {'in_memory': True})

    DARK  = '#14213D'
    GOLD  = '#EAB308'
    LIGHT = '#F3F4F6'

    hdr_fmt  = wb.add_format({'bold': True, 'bg_color': DARK,  'font_color': '#FFFFFF', 'border': 1, 'font_size': 9})
    hdr2_fmt = wb.add_format({'bold': True, 'bg_color': GOLD,  'font_color': DARK,       'border': 1, 'font_size': 9})
    alt_fmt  = wb.add_format({'bg_color': LIGHT, 'border': 1, 'font_size': 8})
    norm_fmt = wb.add_format({'bg_color': '#FFFFFF', 'border': 1, 'font_size': 8})

    def write_section(ws, row, title, headers, rows_data, start_col=0):
        ws.merge_range(row, start_col, row, start_col + len(headers) - 1, title, hdr_fmt)
        row += 1
        for ci, h in enumerate(headers):
            ws.write(row, start_col + ci, h, hdr2_fmt)
        row += 1
        for ri, dr in enumerate(rows_data):
            fmt = alt_fmt if ri % 2 else norm_fmt
            for ci, val in enumerate(dr):
                ws.write(row, start_col + ci, str(val) if val is not None else '', fmt)
            row += 1
        return row + 1

    building_label = (report.parameters or {}).get('building') or 'All buildings'

    # ── Sheet 1: Report Info
    ws0 = wb.add_worksheet('Report Info')
    ws0.set_column(0, 0, 30)
    ws0.set_column(1, 1, 60)
    info_headers = ['Field', 'Value']
    info_rows = [
        ['Report Name',   report.name],
        ['Report Type',   report.report_type],
        ['Date From',     _fmt_date(report.date_from)],
        ['Date To',       _fmt_date(report.date_to)],
        ['Scope',         building_label],
        ['Report Number', report.report_number or ''],
        ['Generated By',  request_user.email if request_user else ''],
        ['Generated At',  _fmt_dt(timezone.now())],
    ]
    write_section(ws0, 0, f'{report.report_type.title()} Report', info_headers, info_rows)

    # ── Type-specific sheets
    if report.report_type == 'financial':
        # Summary
        ws1 = wb.add_worksheet('Financial Summary')
        ws1.set_column(0, 0, 45)
        ws1.set_column(1, 1, 20)
        summary = data.get('summary', {})
        write_section(ws1, 0, 'Financial Summary', ['Metric', 'Value'],
                      [[k, v] for k, v in summary.items()])
        sb = data.get('status_breakdown', [])
        if sb:
            row = len(summary) + 4
            write_section(ws1, row, 'Invoices by Status', ['Status', 'Count'],
                          [[r['status'], r['count']] for r in sb])

        # Transactions
        txns = data.get('transactions', [])
        if txns:
            ws2 = wb.add_worksheet('Transactions')
            for ci, w in enumerate([18, 16, 18, 18, 18, 12, 12, 12, 22]):
                ws2.set_column(ci, ci, w)
            headers = ['Payment #', 'Created At', 'Resident', 'Invoice #', 'Building', 'Method', 'Status', 'Amount', 'Gateway Ref']
            rows = []
            for tx in txns:
                rows.append([
                    tx.get('payment_number',''),
                    _fmt_dt(tx.get('created_at')),
                    f"{tx.get('user__first_name','')} {tx.get('user__last_name','')}".strip(),
                    tx.get('invoice__invoice_number') or '',
                    tx.get('invoice__building') or '',
                    tx.get('payment_method') or '',
                    tx.get('status') or '',
                    str(tx.get('amount') or ''),
                    tx.get('gateway_transaction_id') or tx.get('gateway_order_id') or '',
                ])
            write_section(ws2, 0, 'All Transactions in Period', headers, rows)

    elif report.report_type == 'occupancy':
        ws1 = wb.add_worksheet('Occupancy Summary')
        ws1.set_column(0, 0, 40)
        ws1.set_column(1, 1, 20)
        summary = data.get('summary', {})
        write_section(ws1, 0, 'Occupancy Summary', ['Metric', 'Value'],
                      [[k, v] for k, v in summary.items()])
        bb = data.get('building_breakdown', [])
        if bb:
            row = len(summary) + 4
            write_section(ws1, row, 'By Building', ['Building', 'Total', 'Tenant', 'Owner', 'Vacant'],
                          [[r.get('building__name',''), r.get('total',0), r.get('occupied',0), r.get('owner',0), r.get('vacant',0)] for r in bb])

        ll = data.get('lease_log', [])
        if ll:
            ws2 = wb.add_worksheet('Lease Log')
            for ci, w in enumerate([22, 12, 20, 12, 12, 12, 15]):
                ws2.set_column(ci, ci, w)
            headers = ['Building', 'Unit', 'Tenant', 'Start Date', 'End Date', 'Status', 'Monthly Rent']
            rows = [
                [r.get('unit__building__name',''), r.get('unit__unit_number',''),
                 f"{r.get('tenant__first_name','')} {r.get('tenant__last_name','')}".strip(),
                 _fmt_date(r.get('start_date')), _fmt_date(r.get('end_date')), r.get('status',''),
                 str(r.get('monthly_rent') or '')]
                for r in ll
            ]
            write_section(ws2, 0, 'Active Lease Log', headers, rows)

    elif report.report_type == 'maintenance':
        ws1 = wb.add_worksheet('Maintenance Summary')
        ws1.set_column(0, 0, 40)
        ws1.set_column(1, 1, 20)
        summary = data.get('summary', {})
        write_section(ws1, 0, 'Maintenance Summary', ['Metric', 'Value'],
                      [[k, v] for k, v in summary.items()])
        cb = data.get('category_breakdown', [])
        if cb:
            row = len(summary) + 4
            write_section(ws1, row, 'By Category', ['Category', 'Count'],
                          [[r['category'], r['count']] for r in cb])

        rl = data.get('request_log', [])
        if rl:
            ws2 = wb.add_worksheet('Request Log')
            for ci, w in enumerate([16, 16, 18, 10, 12, 10, 12, 30, 18, 18, 10, 16]):
                ws2.set_column(ci, ci, w)
            headers = ['Request #', 'Raised On', 'Building', 'Unit', 'Category', 'Priority', 'Status', 'Title', 'Resident', 'Assigned To', 'Cost', 'Completed']
            rows = [
                [r.get('request_number',''), _fmt_dt(r.get('created_at')), r.get('building',''), r.get('unit_number',''),
                 r.get('category',''), r.get('priority',''), r.get('status',''), (r.get('title') or '')[:50],
                 f"{r.get('requested_by__first_name','')} {r.get('requested_by__last_name','')}".strip(),
                 f"{r.get('assigned_to__first_name') or ''} {r.get('assigned_to__last_name') or ''}".strip() or '-',
                 str(r.get('total_cost') or '0'), _fmt_dt(r.get('completed_date'))]
                for r in rl
            ]
            write_section(ws2, 0, 'All Maintenance Requests', headers, rows)

    elif report.report_type == 'compliance':
        ws1 = wb.add_worksheet('Compliance Summary')
        ws1.set_column(0, 0, 40)
        ws1.set_column(1, 1, 20)
        summary = data.get('summary', {})
        write_section(ws1, 0, 'Compliance Summary', ['Metric', 'Value'],
                      [[k, v] for k, v in summary.items()])
        db = data.get('document_breakdown', [])
        if db:
            row = len(summary) + 4
            write_section(ws1, row, 'Documents by Type', ['Document Type', 'Count'],
                          [[r['document_type'], r['count']] for r in db])

        ul = data.get('unsigned_leases', [])
        if ul:
            ws2 = wb.add_worksheet('Unsigned Leases')
            headers = ['Building', 'Unit', 'Tenant', 'Start Date', 'End Date']
            rows = [[r.get('unit__building__name',''), r.get('unit__unit_number',''),
                     f"{r.get('tenant__first_name','')} {r.get('tenant__last_name','')}".strip(),
                     _fmt_date(r.get('start_date')), _fmt_date(r.get('end_date'))] for r in ul]
            write_section(ws2, 0, 'Unsigned Active Leases', headers, rows)

    wb.close()
    buf.seek(0)
    return buf.read(), 'xlsx'


def _build_csv(report, request_user, data):
    """Build a flat CSV with all data sections."""
    buf = io.StringIO()
    w = csv.writer(buf)

    def section(title, headers, rows):
        w.writerow([])
        w.writerow([f'=== {title} ==='])
        w.writerow(headers)
        for r in rows:
            w.writerow([str(v) if v is not None else '' for v in r])

    building_label = (report.parameters or {}).get('building') or 'All buildings'
    section('Report Info', ['Field', 'Value'], [
        ['Report Name',   report.name],
        ['Report Type',   report.report_type],
        ['Date From',     _fmt_date(report.date_from)],
        ['Date To',       _fmt_date(report.date_to)],
        ['Scope',         building_label],
        ['Report Number', report.report_number or ''],
        ['Generated By',  request_user.email if request_user else ''],
    ])

    summary = data.get('summary', {})
    if summary:
        section('Summary', ['Metric', 'Value'], [[k, v] for k, v in summary.items()])

    if report.report_type == 'financial':
        sb = data.get('status_breakdown', [])
        if sb:
            section('Invoices by Status', ['Status', 'Count'],
                    [[r['status'], r['count']] for r in sb])
        txns = data.get('transactions', [])
        if txns:
            section('All Transactions', ['Payment #', 'Created At', 'Resident', 'Invoice #', 'Building', 'Method', 'Status', 'Amount', 'Gateway Ref'],
                    [[tx.get('payment_number',''), _fmt_dt(tx.get('created_at')),
                      f"{tx.get('user__first_name','')} {tx.get('user__last_name','')}".strip(),
                      tx.get('invoice__invoice_number') or '', tx.get('invoice__building') or '',
                      tx.get('payment_method') or '', tx.get('status') or '', str(tx.get('amount') or ''),
                      tx.get('gateway_transaction_id') or tx.get('gateway_order_id') or ''] for tx in txns])

    elif report.report_type == 'occupancy':
        bb = data.get('building_breakdown', [])
        if bb:
            section('By Building', ['Building', 'Total', 'Tenant', 'Owner', 'Vacant'],
                    [[r.get('building__name',''), r.get('total',0), r.get('occupied',0), r.get('owner',0), r.get('vacant',0)] for r in bb])
        ll = data.get('lease_log', [])
        if ll:
            section('Lease Log', ['Building', 'Unit', 'Tenant', 'Start Date', 'End Date', 'Status', 'Monthly Rent'],
                    [[r.get('unit__building__name',''), r.get('unit__unit_number',''),
                      f"{r.get('tenant__first_name','')} {r.get('tenant__last_name','')}".strip(),
                      _fmt_date(r.get('start_date')), _fmt_date(r.get('end_date')), r.get('status',''),
                      str(r.get('monthly_rent') or '')] for r in ll])

    elif report.report_type == 'maintenance':
        cb = data.get('category_breakdown', [])
        if cb:
            section('By Category', ['Category', 'Count'], [[r['category'], r['count']] for r in cb])
        rl = data.get('request_log', [])
        if rl:
            section('Request Log', ['Request #', 'Created At', 'Building', 'Unit', 'Category', 'Priority', 'Status', 'Title', 'Resident', 'Assigned To', 'Cost', 'Completed'],
                    [[r.get('request_number',''), _fmt_dt(r.get('created_at')), r.get('building',''), r.get('unit_number',''),
                      r.get('category',''), r.get('priority',''), r.get('status',''), (r.get('title') or '')[:60],
                      f"{r.get('requested_by__first_name','')} {r.get('requested_by__last_name','')}".strip(),
                      f"{r.get('assigned_to__first_name') or ''} {r.get('assigned_to__last_name') or ''}".strip() or '-',
                      str(r.get('total_cost') or '0'), _fmt_dt(r.get('completed_date'))] for r in rl])

    elif report.report_type == 'compliance':
        db = data.get('document_breakdown', [])
        if db:
            section('Documents by Type', ['Document Type', 'Count'], [[r['document_type'], r['count']] for r in db])
        ul = data.get('unsigned_leases', [])
        if ul:
            section('Unsigned Leases', ['Building', 'Unit', 'Tenant', 'Start Date', 'End Date'],
                    [[r.get('unit__building__name',''), r.get('unit__unit_number',''),
                      f"{r.get('tenant__first_name','')} {r.get('tenant__last_name','')}".strip(),
                      _fmt_date(r.get('start_date')), _fmt_date(r.get('end_date'))] for r in ul])

    return buf.getvalue().encode('utf-8'), 'csv'


def _build_json(report, request_user, data):
    payload = {
        'report_number': report.report_number,
        'name': report.name,
        'report_type': report.report_type,
        'output_format': report.output_format,
        'date_from': str(report.date_from or ''),
        'date_to': str(report.date_to or ''),
        'generated_by': request_user.email if request_user else '',
        'generated_at': timezone.now().isoformat(),
        'parameters': report.parameters or {},
        'data': data,
    }
    return json.dumps(payload, indent=2, default=str).encode('utf-8'), 'json'


# ─────────────────────────────────────────────────────────────────
#  VIEW SETS
# ─────────────────────────────────────────────────────────────────

class ReportTemplateViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'reports'
    queryset = ReportTemplate.objects.all()
    serializer_class = ReportTemplateSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['report_type', 'is_active', 'is_system']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'sort_order', 'created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        if instance.is_system:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('System templates cannot be deleted.')
        instance.delete()


class GeneratedReportViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'reports'
    queryset = GeneratedReport.objects.select_related('template', 'created_by')
    serializer_class = GeneratedReportSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['report_type', 'status', 'output_format']
    search_fields = ['name', 'report_number']
    ordering_fields = ['created_at']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role not in ('master_admin', 'super_admin', 'facility_manager'):
            qs = qs.filter(created_by=user)
        return qs

    @action(detail=False, methods=['post'])
    def generate(self, request):
        """Generate a new detailed report."""
        serializer = GenerateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        template = None
        if data.get('template_id'):
            try:
                template = ReportTemplate.objects.get(id=data['template_id'])
            except ReportTemplate.DoesNotExist:
                return Response({'error': 'Template not found'}, status=status.HTTP_404_NOT_FOUND)

        from django.db import IntegrityError, transaction
        import random, string

        def _make_report_number():
            """Generate a unique RPT-YYYYMMDD-XXXXXX number."""
            from django.utils import timezone as tz
            date_str = tz.now().strftime('%Y%m%d')
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            return f'RPT-{date_str}-{suffix}'

        # Generate a unique report_number; model.save() also handles uniqueness
        # but we pre-generate here to avoid repeated DB lookups in model.save().
        report_number = _make_report_number()

        report = GeneratedReport.objects.create(
            report_number=report_number,
            template=template,
            name=data['name'],
            report_type=data['report_type'],
            output_format=data['output_format'],
            date_from=data.get('date_from'),
            date_to=data.get('date_to'),
            parameters=data.get('parameters', {}),
            created_by=request.user,
            status='generating',
        )


        from django.core.files.base import ContentFile

        try:
            # Collect real data
            report_data = _collect_report_data(report)

            # Render to requested format
            fmt = report.output_format
            if fmt == 'pdf':
                file_bytes, ext = _build_pdf(report, request.user, report_data)
            elif fmt == 'xlsx':
                file_bytes, ext = _build_xlsx(report, request.user, report_data)
            elif fmt == 'csv':
                file_bytes, ext = _build_csv(report, request.user, report_data)
            else:
                file_bytes, ext = _build_json(report, request.user, report_data)

            safe_report_num = get_valid_filename(report.report_number or 'report')
            file_name = f'{safe_report_num}.{ext}'

            report.file.save(file_name, ContentFile(file_bytes), save=False)
            report.file_size = len(file_bytes)
            report.row_count = sum(len(v) if isinstance(v, list) else 1
                                   for v in report_data.values() if v)
            report.status = 'completed'
            report.error_message = ''
            report.save(update_fields=['file', 'file_size', 'row_count', 'status', 'error_message'])

        except Exception as exc:
            logger.error(f'Report generation error: {exc}', exc_info=True)
            report.status = 'failed'
            report.error_message = str(exc)[:1000]
            report.save(update_fields=['status', 'error_message'])
            return Response(
                {'error': 'Failed to generate report', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Notification
        try:
            from notifications.services import NotificationService
            NotificationService.send(
                user=request.user,
                title='Report Generated',
                message=f'Your report "{report.name}" has been generated successfully.',
                notification_type='system',
                priority='medium',
                send_push=True,
            )
        except Exception:
            pass

        return Response(GeneratedReportSerializer(report).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download the report file."""
        from django.http import FileResponse, HttpResponse
        import mimetypes

        report = self.get_object()

        if report.status != 'completed':
            return HttpResponse(
                '{"error": "Report is not yet completed"}',
                content_type='application/json', status=400,
            )
        if not report.file or not report.file.name:
            return HttpResponse(
                '{"error": "Report file not available"}',
                content_type='application/json', status=404,
            )
        if not report.file.storage.exists(report.file.name):
            return HttpResponse(
                '{"error": "Report file is missing from storage"}',
                content_type='application/json', status=404,
            )

        file_name = report.file.name or ''
        ext = file_name.rsplit('.', 1)[-1] if '.' in file_name else report.output_format

        content_type, _ = mimetypes.guess_type(file_name)
        if not content_type:
            content_type_map = {
                'pdf':  'application/pdf',
                'csv':  'text/csv',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'json': 'application/json',
            }
            content_type = content_type_map.get(ext, 'application/octet-stream')

        safe_base_name = get_valid_filename(report.name or report.report_number or 'report')
        download_name  = f'{safe_base_name}.{ext}'

        try:
            fh = report.file.open('rb')
            response = FileResponse(fh, content_type=content_type)
            response['Content-Disposition'] = f'attachment; filename="{download_name}"'
            response['X-Accel-Buffering']   = 'no'
            return response
        except (FileNotFoundError, OSError):
            return HttpResponse(
                '{"error": "Report file is missing from storage"}',
                content_type='application/json', status=404,
            )
        except Exception as exc:
            logger.error(f'Report download error: {exc}', exc_info=True)
            return HttpResponse(
                '{"error": "Unable to open report file"}',
                content_type='application/json', status=500,
            )

    @action(detail=True, methods=['post'])
    def regenerate(self, request, pk=None):
        """Regenerate a previously generated report."""
        original = self.get_object()
        report = GeneratedReport.objects.create(
            template=original.template,
            name=original.name,
            report_type=original.report_type,
            output_format=original.output_format,
            date_from=original.date_from,
            date_to=original.date_to,
            parameters=original.parameters,
            created_by=request.user,
            status='pending',
        )
        return Response(GeneratedReportSerializer(report).data, status=status.HTTP_201_CREATED)


class ScheduledReportViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    module = 'reports'
    queryset = ScheduledReport.objects.select_related('template', 'created_by')
    serializer_class = ScheduledReportSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['frequency', 'is_active']
    search_fields = ['name']
    ordering_fields = ['name', 'next_run', 'created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        schedule = self.get_object()
        schedule.is_active = not schedule.is_active
        schedule.save(update_fields=['is_active', 'updated_at'])
        return Response(ScheduledReportSerializer(schedule).data)

    @action(detail=True, methods=['post'])
    def run_now(self, request, pk=None):
        schedule = self.get_object()
        report = GeneratedReport.objects.create(
            template=schedule.template,
            name=f'{schedule.name} (Manual Run)',
            report_type=schedule.template.report_type,
            output_format=schedule.output_format,
            parameters=schedule.parameters,
            created_by=request.user,
            status='pending',
        )
        return Response(GeneratedReportSerializer(report).data, status=status.HTTP_201_CREATED)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def reports_dashboard(request):
    stats = {
        'total_templates':  ReportTemplate.objects.filter(is_active=True).count(),
        'total_generated':  GeneratedReport.objects.count(),
        'pending':          GeneratedReport.objects.filter(status='pending').count(),
        'completed':        GeneratedReport.objects.filter(status='completed').count(),
        'failed':           GeneratedReport.objects.filter(status='failed').count(),
        'scheduled_active': ScheduledReport.objects.filter(is_active=True).count(),
        'by_type': dict(
            ReportTemplate.objects.filter(is_active=True)
            .values_list('report_type')
            .annotate(count=Count('id'))
            .values_list('report_type', 'count')
        ),
    }
    return Response(stats)
