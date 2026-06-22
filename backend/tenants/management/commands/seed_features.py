from django.core.management.base import BaseCommand
from tenants.models import TenantFeature


class Command(BaseCommand):
    help = 'Seeds Platform Features matching the Master Admin sidebar exactly'

    def handle(self, *args, **options):
        features = [
            # ─────────────────────────────────────────────────────────────
            # ONBOARDING & SETUP  (master_admin sidebar – onboarding items)
            # ─────────────────────────────────────────────────────────────
            {
                'name': 'kyc',
                'display_name': 'Terms & Agreement',
                'category': 'setup',
                'description': 'Organization KYC verification, terms acceptance, and legal agreement.',
            },
            {
                'name': 'billing_overview',
                'display_name': 'Organization Billing',
                'category': 'setup',
                'description': 'SaaS subscription billing overview and organization payment history.',
            },
            {
                'name': 'subscription',
                'display_name': 'Subscription Overview',
                'category': 'setup',
                'description': 'View and manage the current subscription plan and renewal details.',
            },

            # ─────────────────────────────────────────────────────────────
            # PRIMARY MODULES  (master_admin sidebar – main navigation)
            # ─────────────────────────────────────────────────────────────
            {
                'name': 'dashboard',
                'display_name': 'Dashboard',
                'category': 'primary',
                'description': 'Organization overview with key metrics and live activity feed.',
            },
            {
                'name': 'communities',
                'display_name': 'Communities',
                'category': 'primary',
                'description': 'Manage communities, townships, and residential communities.',
            },
            {
                'name': 'buildings',
                'display_name': 'Blocks/Sectors',
                'category': 'primary',
                'description': 'Manage building blocks, sectors, and floor structures.',
            },
            {
                'name': 'units',
                'display_name': 'Units',
                'category': 'primary',
                'description': 'Manage individual apartment units and their occupancy details.',
            },
            {
                'name': 'people_hub',
                'display_name': 'People Hub',
                'category': 'primary',
                'description': 'Manage residents, owners, tenants, and all people in the community.',
            },
            {
                'name': 'facility_managers',
                'display_name': 'Facility Managers',
                'category': 'primary',
                'description': 'Assign and manage facility-level staff and property managers.',
            },
            {
                'name': 'senior_managers',
                'display_name': 'Senior Hub Managers',
                'category': 'primary',
                'description': 'Advanced staff hierarchy and senior property manager controls.',
            },
            {
                'name': 'leases',
                'display_name': 'Rental Hub',
                'category': 'primary',
                'description': 'Track rental agreements, leases, and tenant movements.',
            },
            {
                'name': 'documents',
                'display_name': 'Documents',
                'category': 'primary',
                'description': 'Store, manage, and share community documents and agreements.',
            },
            {
                'name': 'bulk_upload',
                'display_name': 'Bulk Upload',
                'category': 'primary',
                'description': 'Import residents, units, and payments in bulk via CSV/Excel.',
            },
            {
                'name': 'bulk_export',
                'display_name': 'Bulk Export',
                'category': 'primary',
                'description': 'Export organization data and reports in bulk.',
            },

            # ─────────────────────────────────────────────────────────────
            # SECONDARY SERVICES  (master_admin sidebar – after divider)
            # ─────────────────────────────────────────────────────────────
            {
                'name': 'payments',
                'display_name': 'Payments',
                'category': 'secondary',
                'description': 'Fee collection, invoicing, and payment tracking for residents.',
            },
            {
                'name': 'maintenance',
                'display_name': 'Maintenance',
                'category': 'secondary',
                'description': 'Track and resolve facility maintenance requests and service tickets.',
            },
            {
                'name': 'amenities',
                'display_name': 'Amenities',
                'category': 'secondary',
                'description': 'Book shared amenities, clubhouse, halls, and sports courts.',
            },
            {
                'name': 'security',
                'display_name': 'Security',
                'category': 'secondary',
                'description': 'Digital logbook for visitors, gate operations, and staff entry.',
            },
            {
                'name': 'vendors',
                'display_name': 'Vendors',
                'category': 'secondary',
                'description': 'Vendor and AMC management for outsourced facility services.',
            },
            {
                'name': 'calendar',
                'display_name': 'Calendar',
                'category': 'secondary',
                'description': 'Community event calendar and scheduling tools.',
            },
            {
                'name': 'communication',
                'display_name': 'Message Center',
                'category': 'secondary',
                'description': 'Broadcast SMS, emails, and WhatsApp notifications to all residents.',
            },
            {
                'name': 'support',
                'display_name': 'Support Center',
                'category': 'secondary',
                'description': 'Helpdesk ticketing and priority support for residents and staff.',
            },
            {
                'name': 'reports',
                'display_name': 'Reports',
                'category': 'secondary',
                'description': 'Advanced collection trends, reports exports, and analytics.',
            },
            {
                'name': 'addons',
                'display_name': 'Add-on Services',
                'category': 'secondary',
                'description': 'Purchase and manage additional platform services and modules.',
            },
            {
                'name': 'settings',
                'display_name': 'Profile',
                'category': 'secondary',
                'description': 'Organization profile settings, branding, and admin preferences.',
            },

            # ─────────────────────────────────────────────────────────────
            # ADVANCED TOOLS  (master_admin sidebar – developer portal)
            # ─────────────────────────────────────────────────────────────
            {
                'name': 'developer_portal',
                'display_name': 'Developer Portal',
                'category': 'advanced',
                'description': 'Access developer APIs, Webhooks, and direct platform integrations.',
            },
        ]

        created_count = 0
        updated_count = 0

        for f in features:
            feat, created = TenantFeature.objects.update_or_create(
                name=f['name'],
                defaults={
                    'display_name': f['display_name'],
                    'category': f['category'],
                    'description': f['description'],
                    'is_active': True,
                }
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created: {f['display_name']}  [{f['category']}]"))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f"  ↺ Updated: {f['display_name']}  [{f['category']}]"))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"Done! Created: {created_count}  |  Updated: {updated_count}  |  Total: {len(features)} features"
        ))
