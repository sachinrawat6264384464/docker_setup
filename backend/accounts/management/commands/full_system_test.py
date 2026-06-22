# accounts/management/commands/full_system_test.py
"""
Full Integration System Test for HOAConnect Hub
================================================
Performs end-to-end integration testing across all modules:
  - Tenants, Accounts, Properties, Leases, Payments,
    Maintenance, Visitors, Security, Amenities, Communication

Usage:
  python manage.py full_system_test
  python manage.py full_system_test --cleanup
  python manage.py full_system_test --verbose
  python manage.py full_system_test --cleanup --verbose
"""

import os
import sys
import time
import logging
import traceback
from datetime import datetime, date, timedelta
from decimal import Decimal
from io import StringIO

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from django.utils import timezone


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_SCHEMA_NAME = "test_integration"
TEST_DOMAIN_NAME = "test-integration.localhost"
TEST_TENANT_NAME = "Integration Test Property Co."
TEST_PREFIX = "systest_"  # prefix for all test objects


class TestResult:
    """Container for a single test step result."""

    def __init__(self, name, passed, message="", duration=0.0, details=""):
        self.name = name
        self.passed = passed
        self.message = message
        self.duration = duration
        self.details = details

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name} ({self.duration:.3f}s) - {self.message}"


class Command(BaseCommand):
    help = (
        "Run a comprehensive integration test across all HOAConnect Hub modules. "
        "Creates a test tenant, populates data for every module, validates results, "
        "and optionally cleans up. Logs everything to backend/logs/."
    )

    # ------------------------------------------------------------------
    # Argument definitions
    # ------------------------------------------------------------------
    def add_arguments(self, parser):
        parser.add_argument(
            "--cleanup",
            action="store_true",
            default=False,
            help="Delete the test tenant and all test data after the run.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            default=False,
            help="Print detailed output for each test step.",
        )

    # ------------------------------------------------------------------
    # Handle
    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        self.verbose = options["verbose"]
        self.do_cleanup = options["cleanup"]
        self.results: list[TestResult] = []

        # References to created objects (used across steps & cleanup)
        self.test_tenant = None
        self.test_domain = None
        self.admin_user = None
        self.manager_user = None
        self.resident_user = None
        self.guard_user = None
        self.building = None
        self.unit = None
        self.lease = None
        self.invoice = None
        self.payment = None
        self.payment_gateway = None
        self.maintenance_request = None
        self.visitor_type = None
        self.visitor = None
        self.visitor_pass = None
        self.security_guard = None
        self.security_incident = None
        self.amenity = None
        self.amenity_booking = None
        self.conversation = None
        self.message = None

        # ---- Set up file logger ----
        self._setup_logger()

        overall_start = time.time()

        self._banner("HOAConnect Hub - Full Integration System Test")
        self.logger.info("=" * 80)
        self.logger.info("HOAConnect Hub - Full Integration System Test")
        self.logger.info(f"Started at: {datetime.now().isoformat()}")
        self.logger.info(f"Cleanup mode: {self.do_cleanup}")
        self.logger.info(f"Verbose mode: {self.verbose}")
        self.logger.info("=" * 80)

        # ---- Execute test steps ----
        steps = [
            ("1. Tenant Setup", self._test_tenant_setup),
            ("2. Account / User Creation", self._test_accounts),
            ("3. Property - Buildings & Units", self._test_properties),
            ("4. Lease Creation", self._test_leases),
            ("5. Payments - Invoice & Payment", self._test_payments),
            ("6. Maintenance Requests", self._test_maintenance),
            ("7. Visitors - Types, Visitors, Passes", self._test_visitors),
            ("8. Security - Guards & Incidents", self._test_security),
            ("9. Amenities - Create & Book", self._test_amenities),
            ("10. Communication - Conversations & Messages", self._test_communication),
        ]

        for step_name, step_fn in steps:
            self._run_step(step_name, step_fn)

        # ---- Optional cleanup ----
        if self.do_cleanup:
            self._run_step("11. Cleanup - Remove Test Data", self._test_cleanup)

        # ---- Summary ----
        overall_duration = time.time() - overall_start
        self._print_summary(overall_duration)

    # ==================================================================
    # SETUP HELPERS
    # ==================================================================
    def _setup_logger(self):
        """Configure a file logger that writes to backend/logs/."""
        log_dir = os.path.join(settings.BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"system_test_{timestamp}.log")

        self.logger = logging.getLogger("full_system_test")
        self.logger.setLevel(logging.DEBUG)
        # Prevent duplicate handlers on repeated runs
        self.logger.handlers = []

        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

        self.log_file_path = log_file
        self.stdout.write(f"  Log file: {log_file}\n")

    # ------------------------------------------------------------------
    # Step runner
    # ------------------------------------------------------------------
    def _run_step(self, name, fn):
        """Execute *fn* inside try/except, record timing and result."""
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"  {name}")
        self.stdout.write(f"{'='*60}")
        self.logger.info("-" * 60)
        self.logger.info(f"STEP: {name}")

        start = time.time()
        try:
            fn()
            duration = time.time() - start
            result = TestResult(name, True, "OK", duration)
        except Exception as exc:
            duration = time.time() - start
            tb = traceback.format_exc()
            result = TestResult(name, False, str(exc), duration, tb)
            self.logger.error(f"EXCEPTION in {name}: {exc}")
            self.logger.debug(tb)
            self.stdout.write(self.style.ERROR(f"  FAILED: {exc}"))
            if self.verbose:
                self.stdout.write(tb)

        self.results.append(result)

        status_style = self.style.SUCCESS if result.passed else self.style.ERROR
        self.stdout.write(
            status_style(f"  {'PASS' if result.passed else 'FAIL'} - {result.message} ({duration:.3f}s)")
        )
        self.logger.info(f"RESULT: {'PASS' if result.passed else 'FAIL'} ({duration:.3f}s) - {result.message}")

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------
    def _banner(self, text):
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.HTTP_INFO(f"  {text}"))
        self.stdout.write("=" * 80)

    def _detail(self, msg):
        """Print only when --verbose is active."""
        if self.verbose:
            self.stdout.write(f"    {msg}")
        self.logger.debug(msg)

    def _info(self, msg):
        """Always printed and logged."""
        self.stdout.write(f"    {msg}")
        self.logger.info(msg)

    # ==================================================================
    # 1. TENANT SETUP
    # ==================================================================
    def _test_tenant_setup(self):
        from tenants.models import Client, Domain

        # Clean up any leftover test tenant from a previous interrupted run
        old = Client.objects.filter(schema_name=TEST_SCHEMA_NAME).first()
        if old:
            self._detail(f"Removing leftover test tenant (schema={TEST_SCHEMA_NAME})")
            old.delete(force_drop=True)

        # Create test tenant (Client) -- this also creates the schema
        self.test_tenant = Client(
            schema_name=TEST_SCHEMA_NAME,
            name=TEST_TENANT_NAME,
            description="Automated integration test tenant",
            contact_email=f"{TEST_PREFIX}admin@example.com",
            contact_phone="+1-555-000-0000",
            address="123 Test Street, Testville, TS 00000",
            subscription_plan="enterprise",
            is_active=True,
        )
        self.test_tenant.save()
        self._info(f"Created Client: {self.test_tenant.name} (schema={self.test_tenant.schema_name})")

        # Create Domain
        self.test_domain = Domain(
            domain=TEST_DOMAIN_NAME,
            tenant=self.test_tenant,
            is_primary=True,
        )
        self.test_domain.save()
        self._info(f"Created Domain: {self.test_domain.domain}")

        # Verify the schema was created
        from django_tenants.utils import schema_context
        with schema_context(TEST_SCHEMA_NAME):
            self._detail("Successfully switched into test tenant schema")

    # ==================================================================
    # 2. ACCOUNT / USER CREATION
    # ==================================================================
    def _test_accounts(self):
        from django_tenants.utils import schema_context
        from accounts.models import User, UserProfile

        with schema_context(TEST_SCHEMA_NAME):
            # Master admin
            self.admin_user = User.objects.create_user(
                username=f"{TEST_PREFIX}master_admin",
                email=f"{TEST_PREFIX}master_admin@example.com",
                password="TestPass123!",
                first_name="Test",
                last_name="MasterAdmin",
                role="master_admin",
                phone="+1-555-000-0001",
                is_staff=True,
                is_superuser=True,
                is_approved=True,
                tenant_id=TEST_SCHEMA_NAME,
            )
            UserProfile.objects.create(
                user=self.admin_user,
                occupation="System Administrator",
                city="Testville",
                state="TS",
                country="India",
            )
            self._info(f"Created user: {self.admin_user.username} (role={self.admin_user.role})")

            # Facility manager
            self.manager_user = User.objects.create_user(
                username=f"{TEST_PREFIX}facility_manager",
                email=f"{TEST_PREFIX}facility_manager@example.com",
                password="TestPass123!",
                first_name="Test",
                last_name="Manager",
                role="facility_manager",
                phone="+1-555-000-0002",
                is_approved=True,
                tenant_id=TEST_SCHEMA_NAME,
            )
            UserProfile.objects.create(
                user=self.manager_user,
                occupation="Facility Manager",
                city="Testville",
                state="TS",
                country="India",
                employee_id=f"{TEST_PREFIX}EMP001",
                department="Facilities",
            )
            self._info(f"Created user: {self.manager_user.username} (role={self.manager_user.role})")

            # Tenant / Resident
            self.resident_user = User.objects.create_user(
                username=f"{TEST_PREFIX}resident",
                email=f"{TEST_PREFIX}resident@example.com",
                password="TestPass123!",
                first_name="Test",
                last_name="Resident",
                role="tenant",
                phone="+1-555-000-0003",
                unit_number="A-101",
                building_name="Tower Alpha",
                is_approved=True,
                tenant_id=TEST_SCHEMA_NAME,
            )
            UserProfile.objects.create(
                user=self.resident_user,
                occupation="Software Engineer",
                city="Testville",
                state="TS",
                country="India",
                household_size=3,
                has_pets=True,
                pet_details="1 Golden Retriever",
            )
            self._info(f"Created user: {self.resident_user.username} (role={self.resident_user.role})")

            # Security guard user
            self.guard_user = User.objects.create_user(
                username=f"{TEST_PREFIX}guard",
                email=f"{TEST_PREFIX}guard@example.com",
                password="TestPass123!",
                first_name="Test",
                last_name="Guard",
                role="security_guard",
                phone="+1-555-000-0004",
                is_approved=True,
                tenant_id=TEST_SCHEMA_NAME,
            )
            self._info(f"Created user: {self.guard_user.username} (role={self.guard_user.role})")

            # Validate counts
            user_count = User.objects.filter(username__startswith=TEST_PREFIX).count()
            assert user_count == 4, f"Expected 4 test users, got {user_count}"
            self._info(f"Validated: {user_count} test users created")

    # ==================================================================
    # 3. PROPERTIES - Buildings & Units
    # ==================================================================
    def _test_properties(self):
        from django_tenants.utils import schema_context
        from properties.models import Building, Unit

        with schema_context(TEST_SCHEMA_NAME):
            self.building = Building.objects.create(
                name=f"{TEST_PREFIX}Tower Alpha",
                address="123 Test Street",
                city="Testville",
                state="TS",
                postal_code="00000",
                country="India",
                total_floors=10,
                total_units=40,
                building_type="residential",
                year_built=2020,
                blocks=["A", "B"],
                amenities=["gym", "pool", "parking"],
                description="Test building for integration testing",
            )
            self._info(f"Created Building: {self.building.name} (id={self.building.id})")

            self.unit = Unit.objects.create(
                building=self.building,
                unit_number="A-101",
                block="A",
                floor=1,
                unit_type="tenant_occupied",
                bedrooms=2,
                bathrooms=Decimal("2.0"),
                square_feet=1200,
                monthly_rent=Decimal("25000.00"),
                monthly_maintenance=Decimal("3000.00"),
                currency="INR",
                owner_first_name="Owner",
                owner_last_name="Test",
                owner_email=f"{TEST_PREFIX}owner@example.com",
                owner_phone="+1-555-000-0099",
                status="occupied",
                is_occupied=True,
            )
            self._info(f"Created Unit: {self.unit.unit_number} in {self.building.name}")

            # Verify
            assert Building.objects.filter(name__startswith=TEST_PREFIX).count() == 1
            assert Unit.objects.filter(building=self.building).count() == 1
            self._info("Validated: Building and Unit created successfully")

    # ==================================================================
    # 4. LEASES
    # ==================================================================
    def _test_leases(self):
        from django_tenants.utils import schema_context
        from properties.models import Lease

        with schema_context(TEST_SCHEMA_NAME):
            today = date.today()
            self.lease = Lease.objects.create(
                unit=self.unit,
                tenant=self.resident_user,
                start_date=today,
                end_date=today + timedelta(days=365),
                status="active",
                monthly_rent=Decimal("25000.00"),
                security_deposit=Decimal("50000.00"),
                maintenance_charge=Decimal("3000.00"),
                late_fee_amount=Decimal("500.00"),
                agreement_signed=True,
                agreement_signed_date=today,
                terms_and_conditions="Standard lease terms for integration test.",
                notes="Auto-generated by full_system_test management command.",
                created_by=self.manager_user,
            )
            self._info(
                f"Created Lease: {self.lease.id} | "
                f"Unit={self.unit.unit_number} | Tenant={self.resident_user.get_full_name()} | "
                f"Rent={self.lease.monthly_rent}"
            )

            assert Lease.objects.filter(unit=self.unit, tenant=self.resident_user).count() == 1
            self._info("Validated: Lease created and linked correctly")

    # ==================================================================
    # 5. PAYMENTS - Invoice & Payment
    # ==================================================================
    def _test_payments(self):
        from django_tenants.utils import schema_context
        from payments.models import Invoice, Payment, PaymentGateway

        with schema_context(TEST_SCHEMA_NAME):
            today = date.today()

            # Payment gateway
            self.payment_gateway = PaymentGateway.objects.create(
                gateway_type="manual",
                is_active=True,
                is_test_mode=True,
                currency="INR",
                settings={"label": "Integration test gateway"},
            )
            self._info(f"Created PaymentGateway: {self.payment_gateway.gateway_type}")

            # Invoice
            self.invoice = Invoice(
                invoice_number=f"{TEST_PREFIX}INV-0001",
                user=self.resident_user,
                invoice_type="rent",
                building=self.building.name,
                unit_number=self.unit.unit_number,
                subtotal=Decimal("25000.00"),
                tax_amount=Decimal("0.00"),
                tax_percentage=Decimal("0.00"),
                discount_amount=Decimal("0.00"),
                late_fee=Decimal("0.00"),
                issue_date=today,
                due_date=today + timedelta(days=5),
                period_start=today.replace(day=1),
                period_end=(today.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1),
                status="sent",
                description="Monthly rent for integration test",
                line_items=[
                    {"description": "Monthly Rent", "amount": "25000.00"},
                ],
                is_recurring=False,
                created_by=self.manager_user,
            )
            self.invoice.save()
            self._info(
                f"Created Invoice: {self.invoice.invoice_number} | "
                f"Total={self.invoice.total_amount} | Due={self.invoice.due_date}"
            )

            # Payment
            self.payment = Payment(
                payment_number=f"{TEST_PREFIX}PAY-0001",
                user=self.resident_user,
                invoice=self.invoice,
                amount=Decimal("25000.00"),
                currency="INR",
                payment_method="cash",
                gateway=self.payment_gateway,
                gateway_transaction_id=f"{TEST_PREFIX}TXN001",
                status="completed",
                description="Rent payment via cash for integration test",
            )
            self.payment.save()
            self._info(
                f"Created Payment: {self.payment.payment_number} | "
                f"Amount={self.payment.amount} | Status={self.payment.status}"
            )

            # Validate invoice updated
            self.invoice.refresh_from_db()
            self._detail(
                f"Invoice after payment: amount_paid={self.invoice.amount_paid}, "
                f"status={self.invoice.status}"
            )
            assert self.invoice.amount_paid >= Decimal("25000.00"), (
                f"Expected invoice amount_paid >= 25000, got {self.invoice.amount_paid}"
            )
            self._info("Validated: Invoice marked as paid after payment")

    # ==================================================================
    # 6. MAINTENANCE REQUESTS
    # ==================================================================
    def _test_maintenance(self):
        from django_tenants.utils import schema_context
        from maintenance.models import MaintenanceRequest

        with schema_context(TEST_SCHEMA_NAME):
            self.maintenance_request = MaintenanceRequest(
                category="plumbing",
                priority="high",
                title=f"{TEST_PREFIX}Leaking kitchen faucet",
                description="The kitchen faucet has been dripping constantly since yesterday. Needs urgent repair.",
                building=self.building.name,
                unit_number=self.unit.unit_number,
                specific_location="Kitchen sink",
                requested_by=self.resident_user,
                contact_phone=self.resident_user.phone,
                status="submitted",
                access_instructions="Spare key with security desk.",
                is_occupied=True,
            )
            self.maintenance_request.save()
            self._info(
                f"Created MaintenanceRequest: {self.maintenance_request.request_number} | "
                f"Category={self.maintenance_request.category} | "
                f"Priority={self.maintenance_request.priority}"
            )

            # Simulate assignment
            self.maintenance_request.assigned_to = self.manager_user
            self.maintenance_request.status = "assigned"
            self.maintenance_request.assigned_date = timezone.now()
            self.maintenance_request.admin_notes = "Assigned to maintenance team lead."
            self.maintenance_request.save()

            self.maintenance_request.refresh_from_db()
            assert self.maintenance_request.status == "assigned"
            self._info(
                f"Validated: Request {self.maintenance_request.request_number} "
                f"assigned to {self.maintenance_request.assigned_to}"
            )

    # ==================================================================
    # 7. VISITORS - Types, Visitors, Passes
    # ==================================================================
    def _test_visitors(self):
        from django_tenants.utils import schema_context
        from visitors.models import VisitorType, Visitor, VisitorPass

        with schema_context(TEST_SCHEMA_NAME):
            # Visitor type
            self.visitor_type = VisitorType.objects.create(
                name=f"{TEST_PREFIX}Guest",
                description="Personal guest of a resident (test)",
                requires_approval=True,
                max_duration_hours=12,
                color_code="#28a745",
                is_active=True,
            )
            self._info(f"Created VisitorType: {self.visitor_type.name}")

            # Visitor
            self.visitor = Visitor(
                first_name="John",
                last_name=f"{TEST_PREFIX}Doe",
                email=f"{TEST_PREFIX}visitor@example.com",
                phone="+15550001234",
                gender="male",
                id_type="Driver License",
                id_number="DL-TEST-9999",
                company_name="",
            )
            self.visitor.save()
            self._info(f"Created Visitor: {self.visitor.get_full_name()} ({self.visitor.visitor_number})")

            # Visitor pass
            now = timezone.now()
            self.visitor_pass = VisitorPass(
                visitor=self.visitor,
                visitor_type=self.visitor_type,
                host=self.resident_user,
                purpose="Social visit for integration testing",
                building=self.building.name,
                unit_number=self.unit.unit_number,
                expected_arrival=now + timedelta(hours=1),
                expected_departure=now + timedelta(hours=5),
                status="approved",
                approved_by=self.manager_user,
                approved_at=now,
                can_drive_in=False,
                requires_escort=False,
                security_notes="Test visitor pass - automated.",
            )
            self.visitor_pass.save()
            self._info(
                f"Created VisitorPass: {self.visitor_pass.pass_number} | "
                f"Status={self.visitor_pass.status}"
            )

            # Validate chain
            assert VisitorPass.objects.filter(visitor=self.visitor).count() == 1
            self._info("Validated: Visitor -> VisitorPass chain intact")

    # ==================================================================
    # 8. SECURITY - Guards & Incidents
    # ==================================================================
    def _test_security(self):
        from django_tenants.utils import schema_context
        from security.models import SecurityGuard, SecurityIncident

        with schema_context(TEST_SCHEMA_NAME):
            today = date.today()

            # Security guard profile (linked to guard_user)
            self.security_guard = SecurityGuard.objects.create(
                user=self.guard_user,
                employee_id=f"{TEST_PREFIX}SEC001",
                shift="morning",
                status="active",
                date_of_birth=date(1990, 5, 15),
                blood_group="O+",
                emergency_contact_name="Emergency Contact Test",
                emergency_contact_phone="+1-555-000-9999",
                joining_date=today - timedelta(days=180),
                license_number=f"{TEST_PREFIX}LIC-001",
                license_expiry=today + timedelta(days=365),
                training_completed=["Basic Security", "Fire Safety", "First Aid"],
                certifications=["CPR Certified"],
                assigned_building=self.building.name,
                assigned_gate="Main Gate",
                assigned_area="Ground Floor Lobby",
                created_by=self.admin_user,
            )
            self._info(
                f"Created SecurityGuard: {self.security_guard.employee_id} | "
                f"User={self.guard_user.get_full_name()}"
            )

            # Security incident
            self.security_incident = SecurityIncident(
                incident_type="suspicious",
                severity="low",
                title=f"{TEST_PREFIX}Unidentified person near parking area",
                description=(
                    "An unidentified person was observed loitering near the B-block "
                    "parking area at approximately 22:30. Security was alerted and the "
                    "individual left the premises."
                ),
                location="B-Block Parking Area",
                building=self.building.name,
                occurred_at=timezone.now() - timedelta(hours=2),
                reported_by=self.guard_user,
                assigned_to=self.security_guard,
                status="investigating",
                investigation_notes="Reviewing CCTV footage from cameras P1 and P2.",
                police_notified=False,
                management_notified=True,
                property_damage=False,
            )
            self.security_incident.save()
            self._info(
                f"Created SecurityIncident: {self.security_incident.incident_number} | "
                f"Type={self.security_incident.incident_type} | "
                f"Severity={self.security_incident.severity}"
            )

            # Validate
            assert SecurityGuard.objects.filter(employee_id=f"{TEST_PREFIX}SEC001").exists()
            assert SecurityIncident.objects.filter(
                title__startswith=TEST_PREFIX
            ).count() == 1
            self._info("Validated: SecurityGuard and SecurityIncident created")

    # ==================================================================
    # 9. AMENITIES - Create & Book
    # ==================================================================
    def _test_amenities(self):
        from django_tenants.utils import schema_context
        from amenities.models import Amenity, AmenityBooking

        with schema_context(TEST_SCHEMA_NAME):
            today = date.today()
            tomorrow = today + timedelta(days=1)

            self.amenity = Amenity.objects.create(
                name=f"{TEST_PREFIX}Community Pool",
                amenity_type="pool",
                description="Olympic-sized swimming pool for residents (test amenity).",
                building=self.building.name,
                floor="Ground",
                location_details="Adjacent to the clubhouse on the west side.",
                capacity=30,
                area_sqft=Decimal("5000.00"),
                status="available",
                is_bookable=True,
                requires_approval=False,
                is_24_hours=False,
                operating_hours={
                    "monday": {"open": "06:00", "close": "21:00"},
                    "tuesday": {"open": "06:00", "close": "21:00"},
                    "wednesday": {"open": "06:00", "close": "21:00"},
                    "thursday": {"open": "06:00", "close": "21:00"},
                    "friday": {"open": "06:00", "close": "21:00"},
                    "saturday": {"open": "07:00", "close": "22:00"},
                    "sunday": {"open": "07:00", "close": "22:00"},
                },
                max_booking_duration_hours=2,
                min_advance_booking_hours=1,
                max_advance_booking_days=14,
                is_paid=True,
                price_per_hour=Decimal("200.00"),
                security_deposit=Decimal("500.00"),
                features=["heated", "changing_rooms", "showers", "towels"],
                rules="No diving. Children under 12 must be supervised.",
                created_by=self.admin_user,
            )
            self._info(f"Created Amenity: {self.amenity.name} (type={self.amenity.amenity_type})")

            # Book the amenity
            from datetime import time as dt_time

            self.amenity_booking = AmenityBooking(
                amenity=self.amenity,
                booked_by=self.resident_user,
                booking_date=tomorrow,
                start_time=dt_time(10, 0),
                end_time=dt_time(12, 0),
                duration_hours=Decimal("2.00"),
                number_of_people=3,
                guest_names=["Guest A", "Guest B"],
                purpose="Morning swim session (integration test)",
                status="confirmed",
                payment_status="paid",
                notes="Automated test booking",
            )
            self.amenity_booking.save()
            self._info(
                f"Created AmenityBooking: {self.amenity_booking.booking_number} | "
                f"Date={self.amenity_booking.booking_date} | "
                f"Fee={self.amenity_booking.booking_fee}"
            )

            # Validate
            assert Amenity.objects.filter(name__startswith=TEST_PREFIX).count() == 1
            assert AmenityBooking.objects.filter(amenity=self.amenity).count() == 1
            self._info("Validated: Amenity and Booking created successfully")

    # ==================================================================
    # 10. COMMUNICATION - Conversations & Messages
    # ==================================================================
    def _test_communication(self):
        from django_tenants.utils import schema_context
        from communication.models import Conversation, ConversationParticipant, Message

        with schema_context(TEST_SCHEMA_NAME):
            # Create a group conversation
            self.conversation = Conversation.objects.create(
                conversation_type="group",
                title=f"{TEST_PREFIX}Maintenance Discussion",
                description="Group chat about recent maintenance issues (test)",
                created_by=self.manager_user,
            )
            self._info(f"Created Conversation: '{self.conversation.title}' (type={self.conversation.conversation_type})")

            # Add participants
            ConversationParticipant.objects.create(
                conversation=self.conversation,
                user=self.manager_user,
                role="admin",
            )
            ConversationParticipant.objects.create(
                conversation=self.conversation,
                user=self.resident_user,
                role="member",
            )
            self._info("Added participants (Manager and Resident) to conversation")

            # Send a message
            self.message = Message.objects.create(
                conversation=self.conversation,
                sender=self.resident_user,
                content="Hello, is the kitchen faucet leaking a known issue?",
                message_type="text",
            )
            self._info(f"Sent message from {self.resident_user.username}: '{self.message.content[:30]}...'")

            # Validate
            assert Message.objects.filter(conversation=self.conversation).count() == 1
            self._info("Validated: Communication flow works")

    # ==================================================================
    # 11. CLEANUP
    # ==================================================================
    def _test_cleanup(self):
        from tenants.models import Client
        if self.test_tenant:
            self._info(f"Cleaning up test tenant: {self.test_tenant.schema_name}")
            self.test_tenant.delete(force_drop=True)
            self._info("✅ Cleanup successful")

    # ==================================================================
    # SUMMARY
    # ==================================================================
    def _print_summary(self, total_duration):
        passed_count = sum(1 for r in self.results if r.passed)
        failed_count = len(self.results) - passed_count

        self._banner("TEST SUMMARY")
        for res in self.results:
            status_style = self.style.SUCCESS if res.passed else self.style.ERROR
            self.stdout.write(status_style(str(res)))

        self.stdout.write("-" * 30)
        self.stdout.write(f"  TOTAL STEPS: {len(self.results)}")
        self.stdout.write(self.style.SUCCESS(f"  PASSED:      {passed_count}"))
        if failed_count > 0:
            self.stdout.write(self.style.ERROR(f"  FAILED:      {failed_count}"))
        self.stdout.write(f"  DURATION:    {total_duration:.2f}s")
        self.stdout.write("=" * 80 + "\n")

        if failed_count == 0:
            self.stdout.write(self.style.SUCCESS("🌟 ALL SYSTEMS FUNCTIONAL 🌟\n"))
        else:
            self.stdout.write(self.style.ERROR("❌ SOME SYSTEMS FAILED ❌\n"))
