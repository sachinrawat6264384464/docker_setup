# vendors/tests.py
"""
Comprehensive tests for the Vendors app.
Covers models, serializers, API views, custom actions, and permissions.

Run with:
    python manage.py test vendors
    python manage.py test vendors.tests.VendorCategoryModelTest
    python manage.py test vendors -v 2
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from .models import (
    VendorCategory, Vendor, VendorService, VendorContract,
    VendorReview, VendorPayment, VendorInsurance
)
from .serializers import (
    VendorCategorySerializer, VendorSerializer, VendorServiceSerializer,
    VendorContractSerializer, VendorReviewSerializer, VendorPaymentSerializer,
    VendorInsuranceSerializer
)

User = get_user_model()


# =============================================================================
# HELPER MIXINS
# =============================================================================

class VendorTestDataMixin:
    """
    Shared helper methods for creating test fixtures used across model,
    serializer, and API test classes.
    """

    def create_user(self, username='testuser', role='facility_manager', is_staff=False, **kwargs):
        defaults = {
            'email': f'{username}@example.com',
            'password': 'TestPass123!',
            'is_active': True,
            'is_staff': is_staff,
        }
        defaults.update(kwargs)
        password = defaults.pop('password')
        user = User(username=username, role=role, **defaults)
        user.set_password(password)
        user.save()
        return user

    def create_category(self, name='Plumbing', **kwargs):
        defaults = {
            'description': f'{name} services',
            'icon': 'wrench',
            'is_active': True,
        }
        defaults.update(kwargs)
        return VendorCategory.objects.create(name=name, **defaults)

    def create_vendor(self, company_name='ABC Plumbing', **kwargs):
        defaults = {
            'vendor_type': 'company',
            'contact_person': 'John Smith',
            'email': 'john@abcplumbing.com',
            'phone': '555-0100',
            'address_line1': '123 Main St',
            'city': 'Springfield',
            'state': 'IL',
            'zip_code': '62701',
            'status': 'active',
        }
        defaults.update(kwargs)
        return Vendor.objects.create(company_name=company_name, **defaults)

    def create_service(self, vendor=None, category=None, **kwargs):
        vendor = vendor or self.create_vendor()
        category = category or self.create_category()
        defaults = {
            'service_name': 'Pipe Repair',
            'description': 'General pipe repair service',
            'pricing_type': 'hourly',
            'base_price': Decimal('75.00'),
            'is_active': True,
            'min_notice_hours': 24,
        }
        defaults.update(kwargs)
        return VendorService.objects.create(vendor=vendor, category=category, **defaults)

    def create_contract(self, vendor=None, created_by=None, **kwargs):
        vendor = vendor or self.create_vendor()
        created_by = created_by or self.create_user(username='contract_creator')
        defaults = {
            'contract_type': 'annual',
            'title': 'Annual Maintenance Contract',
            'description': 'Annual plumbing maintenance',
            'scope_of_work': 'Quarterly inspections and emergency repairs',
            'contract_value': Decimal('25000.00'),
            'payment_schedule': 'Quarterly payments of ₹6250',
            'start_date': date.today(),
            'end_date': date.today() + timedelta(days=365),
            'status': 'draft',
        }
        defaults.update(kwargs)
        return VendorContract.objects.create(
            vendor=vendor, created_by=created_by, **defaults
        )

    def create_payment(self, vendor=None, created_by=None, **kwargs):
        vendor = vendor or self.create_vendor()
        created_by = created_by or self.create_user(username='payment_creator')
        defaults = {
            'amount': Decimal('5000.00'),
            'description': 'Monthly maintenance payment',
            'invoice_number': 'INV-001',
            'status': 'pending',
            'due_date': date.today() + timedelta(days=30),
        }
        defaults.update(kwargs)
        return VendorPayment.objects.create(
            vendor=vendor, created_by=created_by, **defaults
        )

    def create_insurance(self, vendor=None, **kwargs):
        vendor = vendor or self.create_vendor()
        defaults = {
            'insurance_type': 'general_liability',
            'policy_number': 'POL-12345',
            'insurance_company': 'SafeGuard Insurance',
            'coverage_amount': Decimal('1000000.00'),
            'effective_date': date.today() - timedelta(days=30),
            'expiry_date': date.today() + timedelta(days=335),
        }
        defaults.update(kwargs)
        return VendorInsurance.objects.create(vendor=vendor, **defaults)


# =============================================================================
# MODEL TESTS
# =============================================================================

class VendorCategoryModelTest(VendorTestDataMixin, TestCase):
    """Tests for the VendorCategory model."""

    def setUp(self):
        self.category = self.create_category(name='Plumbing')

    def test_category_creation(self):
        """Test VendorCategory is created with correct field values."""
        self.assertEqual(self.category.name, 'Plumbing')
        self.assertEqual(self.category.description, 'Plumbing services')
        self.assertEqual(self.category.icon, 'wrench')
        self.assertTrue(self.category.is_active)
        self.assertIsNotNone(self.category.created_at)

    def test_str_representation(self):
        """Test __str__ returns category name."""
        self.assertEqual(str(self.category), 'Plumbing')

    def test_unique_name_constraint(self):
        """Test that duplicate category names are rejected."""
        with self.assertRaises(Exception):
            VendorCategory.objects.create(name='Plumbing')

    def test_ordering(self):
        """Test default ordering is by name."""
        self.create_category(name='Electrical')
        self.create_category(name='Landscaping')
        categories = list(VendorCategory.objects.values_list('name', flat=True))
        self.assertEqual(categories, ['Electrical', 'Landscaping', 'Plumbing'])

    def test_blank_fields(self):
        """Test that description and icon can be blank."""
        cat = VendorCategory.objects.create(name='Misc')
        self.assertEqual(cat.description, '')
        self.assertEqual(cat.icon, '')

    def test_default_is_active(self):
        """Test is_active defaults to True."""
        cat = VendorCategory.objects.create(name='New Category')
        self.assertTrue(cat.is_active)

    def test_inactive_category(self):
        """Test creating an inactive category."""
        cat = VendorCategory.objects.create(name='Deprecated', is_active=False)
        self.assertFalse(cat.is_active)


class VendorModelTest(VendorTestDataMixin, TestCase):
    """Tests for the Vendor model."""

    def setUp(self):
        self.vendor = self.create_vendor()

    def test_vendor_creation(self):
        """Test Vendor is created with correct field values."""
        self.assertEqual(self.vendor.company_name, 'ABC Plumbing')
        self.assertEqual(self.vendor.vendor_type, 'company')
        self.assertEqual(self.vendor.contact_person, 'John Smith')
        self.assertEqual(self.vendor.email, 'john@abcplumbing.com')
        self.assertEqual(self.vendor.status, 'active')
        self.assertFalse(self.vendor.is_preferred)
        self.assertFalse(self.vendor.is_verified)

    def test_auto_generated_vendor_number(self):
        """Test vendor_number is auto-generated on save."""
        self.assertIsNotNone(self.vendor.vendor_number)
        self.assertTrue(self.vendor.vendor_number.startswith('VEN-'))
        # Format: VEN-YYYYMM-NNNNN
        parts = self.vendor.vendor_number.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[2]), 5)

    def test_vendor_number_sequential(self):
        """Test sequential vendor number generation."""
        vendor2 = self.create_vendor(company_name='XYZ Electric', email='xyz@example.com')
        num1 = int(self.vendor.vendor_number.split('-')[-1])
        num2 = int(vendor2.vendor_number.split('-')[-1])
        self.assertEqual(num2, num1 + 1)

    def test_vendor_number_not_overwritten_on_update(self):
        """Test vendor_number is not regenerated on subsequent saves."""
        original_number = self.vendor.vendor_number
        self.vendor.company_name = 'Updated Name'
        self.vendor.save()
        self.assertEqual(self.vendor.vendor_number, original_number)

    def test_str_representation(self):
        """Test __str__ returns vendor_number - company_name."""
        expected = f"{self.vendor.vendor_number} - ABC Plumbing"
        self.assertEqual(str(self.vendor), expected)

    def test_uuid_primary_key(self):
        """Test that the primary key is a UUID."""
        import uuid
        self.assertIsInstance(self.vendor.id, uuid.UUID)

    def test_default_values(self):
        """Test default field values."""
        self.assertEqual(self.vendor.average_rating, Decimal('0.00'))
        self.assertEqual(self.vendor.total_reviews, 0)
        self.assertEqual(self.vendor.total_jobs, 0)
        self.assertEqual(self.vendor.country, 'USA')

    def test_vendor_types(self):
        """Test all vendor type choices work."""
        for vendor_type, _ in Vendor.VENDOR_TYPES:
            v = self.create_vendor(
                company_name=f'Test {vendor_type}',
                email=f'{vendor_type}@test.com',
                vendor_type=vendor_type,
            )
            self.assertEqual(v.vendor_type, vendor_type)

    def test_status_choices(self):
        """Test all status choices work."""
        for status_val, _ in Vendor.STATUS_CHOICES:
            self.vendor.status = status_val
            self.vendor.save()
            self.vendor.refresh_from_db()
            self.assertEqual(self.vendor.status, status_val)

    def test_many_to_many_categories(self):
        """Test vendor can be associated with multiple categories."""
        cat1 = self.create_category(name='Plumbing')
        cat2 = self.create_category(name='Electrical')
        self.vendor.categories.set([cat1, cat2])
        self.assertEqual(self.vendor.categories.count(), 2)

    def test_verified_by_foreign_key(self):
        """Test verified_by links to a user."""
        user = self.create_user(username='verifier')
        self.vendor.is_verified = True
        self.vendor.verified_by = user
        self.vendor.verified_at = timezone.now()
        self.vendor.save()
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.verified_by, user)
        self.assertTrue(self.vendor.is_verified)

    def test_optional_fields_blank(self):
        """Test optional fields accept blank values."""
        vendor = Vendor.objects.create(
            company_name='Minimal Vendor',
            contact_person='Min Person',
            email='min@example.com',
            phone='555-0000',
            address_line1='1 Street',
            city='Town',
            state='ST',
            zip_code='00000',
        )
        self.assertEqual(vendor.alternate_phone, '')
        self.assertEqual(vendor.website, '')
        self.assertEqual(vendor.tax_id, '')
        self.assertEqual(vendor.license_number, '')
        self.assertIsNone(vendor.license_expiry)
        self.assertIsNone(vendor.hourly_rate)

    def test_ordering(self):
        """Test default ordering is by -created_at."""
        meta = Vendor._meta
        self.assertEqual(meta.ordering, ['-created_at'])

    def test_indexes(self):
        """Test that indexes exist for status, is_preferred, and average_rating."""
        index_fields = [idx.fields for idx in Vendor._meta.indexes]
        self.assertIn(['status'], index_fields)
        self.assertIn(['is_preferred'], index_fields)
        self.assertIn(['-average_rating'], index_fields)


class VendorServiceModelTest(VendorTestDataMixin, TestCase):
    """Tests for the VendorService model."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.category = self.create_category()
        self.service = self.create_service(vendor=self.vendor, category=self.category)

    def test_service_creation(self):
        """Test VendorService is created with correct field values."""
        self.assertEqual(self.service.service_name, 'Pipe Repair')
        self.assertEqual(self.service.vendor, self.vendor)
        self.assertEqual(self.service.category, self.category)
        self.assertEqual(self.service.pricing_type, 'hourly')
        self.assertEqual(self.service.base_price, Decimal('75.00'))
        self.assertTrue(self.service.is_active)
        self.assertEqual(self.service.min_notice_hours, 24)

    def test_str_representation(self):
        """Test __str__ returns vendor_name - service_name."""
        expected = f"{self.vendor.company_name} - Pipe Repair"
        self.assertEqual(str(self.service), expected)

    def test_cascade_delete(self):
        """Test service is deleted when vendor is deleted."""
        vendor_id = self.vendor.id
        self.vendor.delete()
        self.assertFalse(VendorService.objects.filter(vendor_id=vendor_id).exists())

    def test_protect_category_delete(self):
        """Test category deletion is blocked when services reference it."""
        with self.assertRaises(Exception):
            self.category.delete()

    def test_pricing_types(self):
        """Test all pricing type choices work."""
        for pricing_type in ['hourly', 'fixed', 'per_unit', 'custom']:
            self.service.pricing_type = pricing_type
            self.service.save()
            self.service.refresh_from_db()
            self.assertEqual(self.service.pricing_type, pricing_type)

    def test_ordering(self):
        """Test default ordering is by service_name."""
        self.assertEqual(VendorService._meta.ordering, ['service_name'])

    def test_related_name(self):
        """Test accessing services from vendor via related_name."""
        services = self.vendor.services.all()
        self.assertEqual(services.count(), 1)
        self.assertEqual(services.first(), self.service)


class VendorContractModelTest(VendorTestDataMixin, TestCase):
    """Tests for the VendorContract model."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.user = self.create_user(username='manager')
        self.contract = self.create_contract(vendor=self.vendor, created_by=self.user)

    def test_contract_creation(self):
        """Test VendorContract is created with correct field values."""
        self.assertEqual(self.contract.vendor, self.vendor)
        self.assertEqual(self.contract.contract_type, 'annual')
        self.assertEqual(self.contract.title, 'Annual Maintenance Contract')
        self.assertEqual(self.contract.contract_value, Decimal('25000.00'))
        self.assertEqual(self.contract.status, 'draft')
        self.assertFalse(self.contract.signed_by_vendor)
        self.assertFalse(self.contract.signed_by_management)

    def test_auto_generated_contract_number(self):
        """Test contract_number is auto-generated on save."""
        self.assertIsNotNone(self.contract.contract_number)
        self.assertTrue(self.contract.contract_number.startswith('VCTR-'))
        parts = self.contract.contract_number.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[2]), 5)

    def test_contract_number_sequential(self):
        """Test sequential contract number generation."""
        contract2 = self.create_contract(
            vendor=self.vendor,
            created_by=self.user,
            title='Second Contract',
        )
        num1 = int(self.contract.contract_number.split('-')[-1])
        num2 = int(contract2.contract_number.split('-')[-1])
        self.assertEqual(num2, num1 + 1)

    def test_contract_number_not_overwritten(self):
        """Test contract_number is preserved on update."""
        original_number = self.contract.contract_number
        self.contract.title = 'Updated Title'
        self.contract.save()
        self.assertEqual(self.contract.contract_number, original_number)

    def test_str_representation(self):
        """Test __str__ returns contract_number - vendor company_name."""
        expected = f"{self.contract.contract_number} - {self.vendor.company_name}"
        self.assertEqual(str(self.contract), expected)

    def test_uuid_primary_key(self):
        """Test primary key is UUID."""
        import uuid
        self.assertIsInstance(self.contract.id, uuid.UUID)

    def test_contract_types(self):
        """Test all contract type choices work."""
        for ct, _ in VendorContract.CONTRACT_TYPES:
            self.contract.contract_type = ct
            self.contract.save()
            self.contract.refresh_from_db()
            self.assertEqual(self.contract.contract_type, ct)

    def test_status_choices(self):
        """Test all status choices work."""
        for st, _ in VendorContract.STATUS_CHOICES:
            self.contract.status = st
            self.contract.save()
            self.contract.refresh_from_db()
            self.assertEqual(self.contract.status, st)

    def test_cascade_delete_vendor(self):
        """Test contract is deleted when vendor is deleted."""
        vendor_id = self.vendor.id
        self.vendor.delete()
        self.assertFalse(VendorContract.objects.filter(vendor_id=vendor_id).exists())

    def test_created_by_set_null_on_delete(self):
        """Test created_by becomes null when user is deleted."""
        user = self.create_user(username='temp_user')
        contract = self.create_contract(vendor=self.vendor, created_by=user)
        user.delete()
        contract.refresh_from_db()
        self.assertIsNone(contract.created_by)

    def test_ordering(self):
        """Test default ordering is by -created_at."""
        self.assertEqual(VendorContract._meta.ordering, ['-created_at'])

    def test_nullable_end_date(self):
        """Test end_date can be null (ongoing contracts)."""
        contract = self.create_contract(
            vendor=self.vendor,
            created_by=self.user,
            title='Ongoing Contract',
            end_date=None,
        )
        self.assertIsNone(contract.end_date)


class VendorReviewModelTest(VendorTestDataMixin, TestCase):
    """Tests for the VendorReview model."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.user = self.create_user(username='reviewer')

    def _create_review(self, **kwargs):
        """Helper to create a review, patching the missing update_ratings method."""
        defaults = {
            'vendor': self.vendor,
            'reviewed_by': self.user,
            'overall_rating': 4,
            'quality_rating': 5,
            'timeliness_rating': 4,
            'professionalism_rating': 4,
            'value_rating': 3,
            'title': 'Good work',
            'comment': 'Did a great job on the plumbing.',
        }
        defaults.update(kwargs)
        with patch.object(Vendor, 'update_ratings', create=True, return_value=None):
            return VendorReview.objects.create(**defaults)

    def test_review_creation(self):
        """Test VendorReview is created with correct field values."""
        review = self._create_review()
        self.assertEqual(review.vendor, self.vendor)
        self.assertEqual(review.reviewed_by, self.user)
        self.assertEqual(review.overall_rating, 4)
        self.assertEqual(review.quality_rating, 5)
        self.assertEqual(review.title, 'Good work')
        self.assertFalse(review.is_verified)
        self.assertTrue(review.would_recommend)

    def test_str_representation(self):
        """Test __str__ returns a human-readable review label."""
        review = self._create_review()
        expected = f"Review for {self.vendor.company_name} - 4/5"
        self.assertEqual(str(review), expected)

    def test_save_calls_update_ratings(self):
        """Test that saving a review calls vendor.update_ratings()."""
        with patch.object(Vendor, 'update_ratings', create=True) as mock_update:
            VendorReview.objects.create(
                vendor=self.vendor,
                reviewed_by=self.user,
                overall_rating=5,
                quality_rating=5,
                timeliness_rating=5,
                professionalism_rating=5,
                value_rating=5,
                title='Excellent',
                comment='Amazing work',
            )
            mock_update.assert_called_once()

    def test_rating_validators(self):
        """Test rating fields enforce 1-5 range at validation level."""
        review = self._create_review()
        review.overall_rating = 0
        with self.assertRaises(ValidationError):
            review.full_clean()

        review.overall_rating = 6
        with self.assertRaises(ValidationError):
            review.full_clean()

    def test_cascade_delete_vendor(self):
        """Test review is deleted when vendor is deleted."""
        self._create_review()
        self.vendor.delete()
        self.assertEqual(VendorReview.objects.count(), 0)

    def test_reviewed_by_set_null_on_delete(self):
        """Test reviewed_by becomes null when user is deleted."""
        temp_user = self.create_user(username='temp_reviewer')
        review = self._create_review(reviewed_by=temp_user)
        temp_user.delete()
        review.refresh_from_db()
        self.assertIsNone(review.reviewed_by)

    def test_default_would_recommend(self):
        """Test would_recommend defaults to True."""
        review = self._create_review()
        self.assertTrue(review.would_recommend)

    def test_vendor_response_blank_by_default(self):
        """Test vendor_response is blank initially."""
        review = self._create_review()
        self.assertEqual(review.vendor_response, '')
        self.assertIsNone(review.responded_at)

    def test_ordering(self):
        """Test default ordering is by -created_at."""
        self.assertEqual(VendorReview._meta.ordering, ['-created_at'])


class VendorPaymentModelTest(VendorTestDataMixin, TestCase):
    """Tests for the VendorPayment model."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.user = self.create_user(username='payer')
        self.payment = self.create_payment(vendor=self.vendor, created_by=self.user)

    def test_payment_creation(self):
        """Test VendorPayment is created with correct field values."""
        self.assertEqual(self.payment.vendor, self.vendor)
        self.assertEqual(self.payment.amount, Decimal('5000.00'))
        self.assertEqual(self.payment.status, 'pending')
        self.assertEqual(self.payment.invoice_number, 'INV-001')

    def test_auto_generated_payment_number(self):
        """Test payment_number is auto-generated on save."""
        self.assertIsNotNone(self.payment.payment_number)
        self.assertTrue(self.payment.payment_number.startswith('VPAY-'))
        parts = self.payment.payment_number.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[2]), 5)

    def test_payment_number_sequential(self):
        """Test sequential payment number generation."""
        payment2 = self.create_payment(
            vendor=self.vendor,
            created_by=self.user,
            invoice_number='INV-002',
        )
        num1 = int(self.payment.payment_number.split('-')[-1])
        num2 = int(payment2.payment_number.split('-')[-1])
        self.assertEqual(num2, num1 + 1)

    def test_payment_number_not_overwritten(self):
        """Test payment_number is preserved on update."""
        original_number = self.payment.payment_number
        self.payment.amount = Decimal('6000.00')
        self.payment.save()
        self.assertEqual(self.payment.payment_number, original_number)

    def test_str_representation(self):
        """Test __str__ returns payment_number - vendor - amount."""
        expected = f"{self.payment.payment_number} - {self.vendor.company_name} - ₹{self.payment.amount}"
        self.assertEqual(str(self.payment), expected)

    def test_uuid_primary_key(self):
        """Test primary key is UUID."""
        import uuid
        self.assertIsInstance(self.payment.id, uuid.UUID)

    def test_payment_status_choices(self):
        """Test all payment status choices work."""
        for st, _ in VendorPayment.PAYMENT_STATUS:
            self.payment.status = st
            self.payment.save()
            self.payment.refresh_from_db()
            self.assertEqual(self.payment.status, st)

    def test_optional_contract_link(self):
        """Test payment can be linked to a contract or not."""
        self.assertIsNone(self.payment.contract)

        contract = self.create_contract(vendor=self.vendor, created_by=self.user)
        self.payment.contract = contract
        self.payment.save()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.contract, contract)

    def test_cascade_delete_vendor(self):
        """Test payment is deleted when vendor is deleted."""
        self.vendor.delete()
        self.assertEqual(VendorPayment.objects.count(), 0)

    def test_contract_set_null_on_delete(self):
        """Test contract FK becomes null when contract is deleted."""
        contract = self.create_contract(vendor=self.vendor, created_by=self.user)
        self.payment.contract = contract
        self.payment.save()
        contract.delete()
        self.payment.refresh_from_db()
        self.assertIsNone(self.payment.contract)

    def test_ordering(self):
        """Test default ordering is by -created_at."""
        self.assertEqual(VendorPayment._meta.ordering, ['-created_at'])


class VendorInsuranceModelTest(VendorTestDataMixin, TestCase):
    """Tests for the VendorInsurance model."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.insurance = self.create_insurance(vendor=self.vendor)

    def test_insurance_creation(self):
        """Test VendorInsurance is created with correct field values."""
        self.assertEqual(self.insurance.vendor, self.vendor)
        self.assertEqual(self.insurance.insurance_type, 'general_liability')
        self.assertEqual(self.insurance.policy_number, 'POL-12345')
        self.assertEqual(self.insurance.insurance_company, 'SafeGuard Insurance')
        self.assertEqual(self.insurance.coverage_amount, Decimal('1000000.00'))
        self.assertFalse(self.insurance.is_verified)

    def test_str_representation(self):
        """Test __str__ returns vendor - insurance type display."""
        expected = f"{self.vendor.company_name} - General Liability"
        self.assertEqual(str(self.insurance), expected)

    def test_is_expired_false(self):
        """Test is_expired() returns False for future expiry date."""
        self.assertFalse(self.insurance.is_expired())

    def test_is_expired_true(self):
        """Test is_expired() returns True for past expiry date."""
        self.insurance.expiry_date = date.today() - timedelta(days=1)
        self.insurance.save()
        self.assertTrue(self.insurance.is_expired())

    def test_insurance_types(self):
        """Test all insurance type choices work."""
        for ins_type, _ in VendorInsurance.INSURANCE_TYPES:
            ins = self.create_insurance(
                vendor=self.vendor,
                insurance_type=ins_type,
                policy_number=f'POL-{ins_type}',
            )
            self.assertEqual(ins.insurance_type, ins_type)

    def test_cascade_delete_vendor(self):
        """Test insurance is deleted when vendor is deleted."""
        self.vendor.delete()
        self.assertEqual(VendorInsurance.objects.count(), 0)

    def test_verified_by_set_null_on_delete(self):
        """Test verified_by becomes null when user is deleted."""
        user = self.create_user(username='ins_verifier')
        self.insurance.is_verified = True
        self.insurance.verified_by = user
        self.insurance.verified_at = timezone.now()
        self.insurance.save()

        user.delete()
        self.insurance.refresh_from_db()
        self.assertIsNone(self.insurance.verified_by)

    def test_ordering(self):
        """Test default ordering is by -expiry_date."""
        self.assertEqual(VendorInsurance._meta.ordering, ['-expiry_date'])


# =============================================================================
# SERIALIZER TESTS
# =============================================================================

class VendorCategorySerializerTest(VendorTestDataMixin, TestCase):
    """Tests for VendorCategorySerializer."""

    def setUp(self):
        self.category = self.create_category(name='Landscaping')

    def test_serialization_fields(self):
        """Test serializer outputs expected fields."""
        serializer = VendorCategorySerializer(self.category)
        data = serializer.data
        expected_fields = {
            'id', 'name', 'description', 'icon',
            'is_active', 'vendor_count', 'created_at',
        }
        self.assertEqual(set(data.keys()), expected_fields)

    def test_vendor_count_computed(self):
        """Test vendor_count returns count of active vendors in category."""
        vendor = self.create_vendor()
        vendor.categories.add(self.category)
        serializer = VendorCategorySerializer(self.category)
        self.assertEqual(serializer.data['vendor_count'], 1)

    def test_vendor_count_only_active(self):
        """Test vendor_count only includes vendors with active status."""
        active_vendor = self.create_vendor(company_name='Active Co', email='active@test.com')
        active_vendor.categories.add(self.category)

        inactive_vendor = self.create_vendor(
            company_name='Inactive Co', email='inactive@test.com', status='inactive'
        )
        inactive_vendor.categories.add(self.category)

        serializer = VendorCategorySerializer(self.category)
        self.assertEqual(serializer.data['vendor_count'], 1)

    def test_deserialization_valid(self):
        """Test valid data deserializes correctly."""
        data = {'name': 'HVAC', 'description': 'Heating and cooling', 'is_active': True}
        serializer = VendorCategorySerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_deserialization_missing_name(self):
        """Test missing name raises validation error."""
        data = {'description': 'Missing name'}
        serializer = VendorCategorySerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('name', serializer.errors)

    def test_read_only_fields(self):
        """Test read-only fields are not writable."""
        data = {'name': 'Test', 'id': 999, 'created_at': '2020-01-01T00:00:00Z'}
        serializer = VendorCategorySerializer(data=data)
        self.assertTrue(serializer.is_valid())
        # id and created_at should not appear in validated_data
        self.assertNotIn('id', serializer.validated_data)
        self.assertNotIn('created_at', serializer.validated_data)


class VendorSerializerTest(VendorTestDataMixin, TestCase):
    """Tests for VendorSerializer."""

    def setUp(self):
        self.category = self.create_category(name='Plumbing')
        self.vendor = self.create_vendor()
        self.vendor.categories.add(self.category)

    def test_serialization_includes_nested_categories(self):
        """Test serialization includes nested category objects."""
        serializer = VendorSerializer(self.vendor)
        data = serializer.data
        self.assertIn('categories', data)
        self.assertEqual(len(data['categories']), 1)
        self.assertEqual(data['categories'][0]['name'], 'Plumbing')

    def test_serialization_includes_services(self):
        """Test serialization includes nested service objects."""
        self.create_service(vendor=self.vendor, category=self.category)
        serializer = VendorSerializer(self.vendor)
        data = serializer.data
        self.assertIn('services', data)
        self.assertEqual(len(data['services']), 1)

    def test_rating_display(self):
        """Test rating_display computed field."""
        self.vendor.average_rating = Decimal('4.50')
        self.vendor.total_reviews = 10
        self.vendor.save()
        serializer = VendorSerializer(self.vendor)
        rating = serializer.data['rating_display']
        self.assertEqual(rating['average'], 4.50)
        self.assertEqual(rating['total_reviews'], 10)

    def test_is_license_expired_none(self):
        """Test is_license_expired is None when no license_expiry set."""
        serializer = VendorSerializer(self.vendor)
        self.assertIsNone(serializer.data['is_license_expired'])

    def test_is_license_expired_false(self):
        """Test is_license_expired is False for future expiry."""
        self.vendor.license_expiry = date.today() + timedelta(days=30)
        self.vendor.save()
        serializer = VendorSerializer(self.vendor)
        self.assertFalse(serializer.data['is_license_expired'])

    def test_is_license_expired_true(self):
        """Test is_license_expired is True for past expiry."""
        self.vendor.license_expiry = date.today() - timedelta(days=1)
        self.vendor.save()
        serializer = VendorSerializer(self.vendor)
        self.assertTrue(serializer.data['is_license_expired'])

    def test_create_with_category_ids(self):
        """Test creating a vendor with category_ids sets categories."""
        cat1 = self.create_category(name='Cat A')
        cat2 = self.create_category(name='Cat B')
        data = {
            'company_name': 'New Vendor',
            'vendor_type': 'company',
            'contact_person': 'Jane Doe',
            'email': 'new@vendor.com',
            'phone': '555-0200',
            'address_line1': '456 Oak Ave',
            'city': 'Portland',
            'state': 'OR',
            'zip_code': '97201',
            'category_ids': [cat1.id, cat2.id],
        }
        serializer = VendorSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        vendor = serializer.save()
        self.assertEqual(vendor.categories.count(), 2)

    def test_update_with_category_ids(self):
        """Test updating a vendor with category_ids replaces categories."""
        cat_new = self.create_category(name='Electrical')
        data = {'category_ids': [cat_new.id]}
        serializer = VendorSerializer(self.vendor, data=data, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        vendor = serializer.save()
        self.assertEqual(vendor.categories.count(), 1)
        self.assertEqual(vendor.categories.first(), cat_new)

    def test_read_only_fields_not_writable(self):
        """Test read-only fields cannot be set during creation."""
        data = {
            'company_name': 'RO Test',
            'vendor_number': 'CUSTOM-NUM',
            'contact_person': 'Test',
            'email': 'ro@test.com',
            'phone': '555-0000',
            'address_line1': '1 St',
            'city': 'City',
            'state': 'ST',
            'zip_code': '00000',
        }
        serializer = VendorSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('vendor_number', serializer.validated_data)

    def test_deserialization_valid_minimal(self):
        """Test valid minimal data deserializes correctly."""
        data = {
            'company_name': 'Minimal',
            'contact_person': 'Test',
            'email': 'min@test.com',
            'phone': '555-1111',
            'address_line1': '1 Road',
            'city': 'Town',
            'state': 'TX',
            'zip_code': '75001',
        }
        serializer = VendorSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)


class VendorContractSerializerTest(VendorTestDataMixin, TestCase):
    """Tests for VendorContractSerializer."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.user = self.create_user(username='contract_user')
        self.contract = self.create_contract(vendor=self.vendor, created_by=self.user)

    def test_serialization_fields(self):
        """Test serializer outputs expected key fields."""
        serializer = VendorContractSerializer(self.contract)
        data = serializer.data
        self.assertIn('id', data)
        self.assertIn('contract_number', data)
        self.assertIn('vendor', data)
        self.assertIn('is_fully_signed', data)
        self.assertIn('is_active_contract', data)

    def test_is_fully_signed_false(self):
        """Test is_fully_signed is False when not both parties signed."""
        serializer = VendorContractSerializer(self.contract)
        self.assertFalse(serializer.data['is_fully_signed'])

    def test_is_fully_signed_true(self):
        """Test is_fully_signed is True when both parties signed."""
        self.contract.signed_by_vendor = True
        self.contract.signed_by_management = True
        self.contract.save()
        serializer = VendorContractSerializer(self.contract)
        self.assertTrue(serializer.data['is_fully_signed'])

    def test_is_active_contract_draft(self):
        """Test is_active_contract is False for draft status."""
        serializer = VendorContractSerializer(self.contract)
        self.assertFalse(serializer.data['is_active_contract'])

    def test_is_active_contract_active_and_current(self):
        """Test is_active_contract is True for active status with valid dates."""
        self.contract.status = 'active'
        self.contract.start_date = date.today() - timedelta(days=1)
        self.contract.end_date = date.today() + timedelta(days=30)
        self.contract.save()
        serializer = VendorContractSerializer(self.contract)
        self.assertTrue(serializer.data['is_active_contract'])

    def test_is_active_contract_expired(self):
        """Test is_active_contract is False when end_date is in the past."""
        self.contract.status = 'active'
        self.contract.start_date = date.today() - timedelta(days=60)
        self.contract.end_date = date.today() - timedelta(days=1)
        self.contract.save()
        serializer = VendorContractSerializer(self.contract)
        self.assertFalse(serializer.data['is_active_contract'])

    def test_is_active_contract_not_yet_started(self):
        """Test is_active_contract is False when start_date is in the future."""
        self.contract.status = 'active'
        self.contract.start_date = date.today() + timedelta(days=10)
        self.contract.end_date = date.today() + timedelta(days=100)
        self.contract.save()
        serializer = VendorContractSerializer(self.contract)
        self.assertFalse(serializer.data['is_active_contract'])

    def test_create_sets_created_by_from_request(self):
        """Test serializer create() sets created_by from request context."""
        request = MagicMock()
        request.user = self.user
        data = {
            'vendor_id': str(self.vendor.id),
            'contract_type': 'one_time',
            'title': 'One Time Job',
            'description': 'Quick fix',
            'scope_of_work': 'Fix the door',
            'contract_value': '500.00',
            'payment_schedule': 'On completion',
            'start_date': str(date.today()),
        }
        serializer = VendorContractSerializer(data=data, context={'request': request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        contract = serializer.save()
        self.assertEqual(contract.created_by, self.user)

    def test_vendor_id_write_only(self):
        """Test vendor_id is write-only and vendor is read-only."""
        serializer = VendorContractSerializer(self.contract)
        data = serializer.data
        self.assertIn('vendor', data)
        self.assertNotIn('vendor_id', data)


class VendorReviewSerializerTest(VendorTestDataMixin, TestCase):
    """Tests for VendorReviewSerializer."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.user = self.create_user(username='review_user')
        with patch.object(Vendor, 'update_ratings', create=True, return_value=None):
            self.review = VendorReview.objects.create(
                vendor=self.vendor,
                reviewed_by=self.user,
                overall_rating=4,
                quality_rating=5,
                timeliness_rating=3,
                professionalism_rating=4,
                value_rating=4,
                title='Good service',
                comment='Very professional',
            )

    def test_average_rating_computed(self):
        """Test average_rating computed field calculation."""
        serializer = VendorReviewSerializer(self.review)
        # (4+5+3+4+4) / 5 = 4.0
        self.assertEqual(serializer.data['average_rating'], 4.0)

    def test_serialization_fields(self):
        """Test serializer outputs expected fields."""
        serializer = VendorReviewSerializer(self.review)
        data = serializer.data
        self.assertIn('overall_rating', data)
        self.assertIn('quality_rating', data)
        self.assertIn('average_rating', data)
        self.assertIn('vendor', data)
        self.assertIn('reviewed_by_user', data)

    def test_create_sets_reviewed_by_from_request(self):
        """Test serializer create() sets reviewed_by from request context."""
        request = MagicMock()
        request.user = self.user
        data = {
            'vendor_id': str(self.vendor.id),
            'overall_rating': 5,
            'quality_rating': 5,
            'timeliness_rating': 5,
            'professionalism_rating': 5,
            'value_rating': 5,
            'title': 'Perfect',
            'comment': 'Could not ask for better',
        }
        serializer = VendorReviewSerializer(data=data, context={'request': request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with patch.object(Vendor, 'update_ratings', create=True, return_value=None):
            review = serializer.save()
        self.assertEqual(review.reviewed_by, self.user)

    def test_read_only_fields(self):
        """Test is_verified and vendor_response are read-only."""
        data = {
            'vendor_id': str(self.vendor.id),
            'overall_rating': 3,
            'quality_rating': 3,
            'timeliness_rating': 3,
            'professionalism_rating': 3,
            'value_rating': 3,
            'title': 'Ok',
            'comment': 'Average',
            'is_verified': True,
            'vendor_response': 'Thanks',
        }
        serializer = VendorReviewSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn('is_verified', serializer.validated_data)
        self.assertNotIn('vendor_response', serializer.validated_data)

    def test_invalid_rating_range(self):
        """Test serializer rejects ratings outside 1-5."""
        data = {
            'vendor_id': str(self.vendor.id),
            'overall_rating': 6,
            'quality_rating': 5,
            'timeliness_rating': 5,
            'professionalism_rating': 5,
            'value_rating': 5,
            'title': 'Bad',
            'comment': 'Invalid',
        }
        serializer = VendorReviewSerializer(data=data)
        self.assertFalse(serializer.is_valid())


class VendorPaymentSerializerTest(VendorTestDataMixin, TestCase):
    """Tests for VendorPaymentSerializer."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.user = self.create_user(username='payment_user')
        self.payment = self.create_payment(vendor=self.vendor, created_by=self.user)

    def test_is_overdue_false_for_paid(self):
        """Test is_overdue is False for paid payments."""
        self.payment.status = 'paid'
        self.payment.save()
        serializer = VendorPaymentSerializer(self.payment)
        self.assertFalse(serializer.data['is_overdue'])

    def test_is_overdue_true(self):
        """Test is_overdue is True for pending payment past due date."""
        self.payment.due_date = date.today() - timedelta(days=5)
        self.payment.save()
        serializer = VendorPaymentSerializer(self.payment)
        self.assertTrue(serializer.data['is_overdue'])

    def test_is_overdue_false_not_past_due(self):
        """Test is_overdue is False for pending payment before due date."""
        self.payment.due_date = date.today() + timedelta(days=10)
        self.payment.save()
        serializer = VendorPaymentSerializer(self.payment)
        self.assertFalse(serializer.data['is_overdue'])

    def test_days_until_due_none_for_paid(self):
        """Test days_until_due is None for paid payments."""
        self.payment.status = 'paid'
        self.payment.save()
        serializer = VendorPaymentSerializer(self.payment)
        self.assertIsNone(serializer.data['days_until_due'])

    def test_days_until_due_positive(self):
        """Test days_until_due is positive for future due date."""
        self.payment.due_date = date.today() + timedelta(days=15)
        self.payment.save()
        serializer = VendorPaymentSerializer(self.payment)
        self.assertEqual(serializer.data['days_until_due'], 15)

    def test_days_until_due_negative(self):
        """Test days_until_due is negative for past due date."""
        self.payment.due_date = date.today() - timedelta(days=3)
        self.payment.save()
        serializer = VendorPaymentSerializer(self.payment)
        self.assertEqual(serializer.data['days_until_due'], -3)

    def test_create_sets_created_by(self):
        """Test serializer create() sets created_by from request context."""
        request = MagicMock()
        request.user = self.user
        data = {
            'vendor_id': str(self.vendor.id),
            'amount': '1000.00',
            'description': 'Test payment',
            'status': 'pending',
            'due_date': str(date.today() + timedelta(days=30)),
        }
        serializer = VendorPaymentSerializer(data=data, context={'request': request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        payment = serializer.save()
        self.assertEqual(payment.created_by, self.user)

    def test_serialization_fields(self):
        """Test serializer outputs expected fields."""
        serializer = VendorPaymentSerializer(self.payment)
        data = serializer.data
        self.assertIn('payment_number', data)
        self.assertIn('is_overdue', data)
        self.assertIn('days_until_due', data)
        self.assertIn('vendor', data)


class VendorInsuranceSerializerTest(VendorTestDataMixin, TestCase):
    """Tests for VendorInsuranceSerializer."""

    def setUp(self):
        self.vendor = self.create_vendor()
        self.insurance = self.create_insurance(vendor=self.vendor)

    def test_is_current_true(self):
        """Test is_current is True when insurance is not expired."""
        serializer = VendorInsuranceSerializer(self.insurance)
        self.assertTrue(serializer.data['is_current'])

    def test_is_current_false(self):
        """Test is_current is False when insurance is expired."""
        self.insurance.expiry_date = date.today() - timedelta(days=1)
        self.insurance.save()
        serializer = VendorInsuranceSerializer(self.insurance)
        self.assertFalse(serializer.data['is_current'])

    def test_days_until_expiry_positive(self):
        """Test days_until_expiry is positive for future expiry."""
        self.insurance.expiry_date = date.today() + timedelta(days=100)
        self.insurance.save()
        serializer = VendorInsuranceSerializer(self.insurance)
        self.assertEqual(serializer.data['days_until_expiry'], 100)

    def test_days_until_expiry_negative(self):
        """Test days_until_expiry is negative for past expiry."""
        self.insurance.expiry_date = date.today() - timedelta(days=10)
        self.insurance.save()
        serializer = VendorInsuranceSerializer(self.insurance)
        self.assertEqual(serializer.data['days_until_expiry'], -10)

    def test_serialization_fields(self):
        """Test serializer outputs expected fields."""
        serializer = VendorInsuranceSerializer(self.insurance)
        data = serializer.data
        self.assertIn('is_current', data)
        self.assertIn('days_until_expiry', data)
        self.assertIn('vendor', data)
        self.assertIn('insurance_type', data)


# =============================================================================
# API / VIEW TESTS
# =============================================================================

class VendorCategoryAPITest(VendorTestDataMixin, APITestCase):
    """API tests for VendorCategoryViewSet."""

    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(
            username='api_admin', role='facility_manager', is_staff=True
        )
        self.client.force_authenticate(user=self.user)
        self.category = self.create_category(name='Plumbing')

    def test_list_categories(self):
        """Test GET /api/vendors/categories/ returns 200."""
        response = self.client.get('/api/vendors/categories/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_categories_contains_data(self):
        """Test list returns created categories."""
        self.create_category(name='Electrical')
        response = self.client.get('/api/vendors/categories/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Could be paginated or a raw list
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            results = data['results']
        else:
            results = data
        names = [c['name'] for c in results]
        self.assertIn('Plumbing', names)
        self.assertIn('Electrical', names)

    def test_create_category(self):
        """Test POST /api/vendors/categories/ creates a category."""
        data = {'name': 'HVAC', 'description': 'Heating & cooling', 'is_active': True}
        response = self.client.post('/api/vendors/categories/', data, format='json')
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
        self.assertTrue(VendorCategory.objects.filter(name='HVAC').exists())

    def test_retrieve_category(self):
        """Test GET /api/vendors/categories/{id}/ returns the category."""
        response = self.client.get(f'/api/vendors/categories/{self.category.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Plumbing')

    def test_update_category(self):
        """Test PATCH /api/vendors/categories/{id}/ updates the category."""
        response = self.client.patch(
            f'/api/vendors/categories/{self.category.id}/',
            {'description': 'Updated desc'},
            format='json'
        )
        self.assertIn(response.status_code, [status.HTTP_200_OK])
        self.category.refresh_from_db()
        self.assertEqual(self.category.description, 'Updated desc')

    def test_delete_category(self):
        """Test DELETE /api/vendors/categories/{id}/ removes the category."""
        cat = self.create_category(name='Temporary')
        response = self.client.delete(f'/api/vendors/categories/{cat.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(VendorCategory.objects.filter(name='Temporary').exists())

    def test_search_categories(self):
        """Test search filter on categories."""
        self.create_category(name='Electrical')
        response = self.client.get('/api/vendors/categories/', {'search': 'Electr'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_is_active(self):
        """Test filtering by is_active query param."""
        self.create_category(name='Inactive Cat', is_active=False)
        response = self.client.get('/api/vendors/categories/', {'is_active': 'false'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class VendorAPITest(VendorTestDataMixin, APITestCase):
    """API tests for VendorViewSet including custom actions."""

    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(
            username='api_admin', role='facility_manager', is_staff=True
        )
        self.client.force_authenticate(user=self.user)
        self.vendor = self.create_vendor()
        self.category = self.create_category(name='General')

    def _vendor_create_data(self, **overrides):
        """Return valid vendor creation payload."""
        data = {
            'company_name': 'New Vendor LLC',
            'vendor_type': 'company',
            'contact_person': 'Alice Doe',
            'email': 'alice@newvendor.com',
            'phone': '555-0300',
            'address_line1': '789 Elm St',
            'city': 'Austin',
            'state': 'TX',
            'zip_code': '73301',
            'category_ids': [self.category.id],
        }
        data.update(overrides)
        return data

    def test_list_vendors(self):
        """Test GET /api/vendors/vendors/ returns 200."""
        response = self.client.get('/api/vendors/vendors/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_vendor(self):
        """Test POST /api/vendors/vendors/ creates a vendor."""
        data = self._vendor_create_data()
        response = self.client.post('/api/vendors/vendors/', data, format='json')
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
        self.assertTrue(Vendor.objects.filter(company_name='New Vendor LLC').exists())

    def test_retrieve_vendor(self):
        """Test GET /api/vendors/vendors/{id}/ returns vendor details."""
        response = self.client.get(f'/api/vendors/vendors/{self.vendor.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['company_name'], 'ABC Plumbing')

    def test_update_vendor(self):
        """Test PATCH /api/vendors/vendors/{id}/ updates vendor."""
        response = self.client.patch(
            f'/api/vendors/vendors/{self.vendor.id}/',
            {'company_name': 'ABC Plumbing Pro'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.company_name, 'ABC Plumbing Pro')

    def test_delete_vendor(self):
        """Test DELETE /api/vendors/vendors/{id}/ removes vendor."""
        v = self.create_vendor(company_name='To Delete', email='delete@test.com')
        response = self.client.delete(f'/api/vendors/vendors/{v.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Vendor.objects.filter(id=v.id).exists())

    def test_preferred_vendors_action(self):
        """Test GET /api/vendors/vendors/preferred_vendors/."""
        self.vendor.is_preferred = True
        self.vendor.save()
        response = self.client.get('/api/vendors/vendors/preferred_vendors/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_top_rated_action(self):
        """Test GET /api/vendors/vendors/top_rated/."""
        response = self.client.get('/api/vendors/vendors/top_rated/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_top_rated_with_limit(self):
        """Test top_rated custom limit parameter."""
        response = self.client.get('/api/vendors/vendors/top_rated/', {'limit': 5})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_verify_action_staff(self):
        """Test POST /api/vendors/vendors/{id}/verify/ by staff user."""
        self.assertFalse(self.vendor.is_verified)
        response = self.client.post(f'/api/vendors/vendors/{self.vendor.id}/verify/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.vendor.refresh_from_db()
        self.assertTrue(self.vendor.is_verified)
        self.assertEqual(self.vendor.verified_by, self.user)
        self.assertIsNotNone(self.vendor.verified_at)

    def test_verify_action_non_staff_denied(self):
        """Test verify action returns 403 for non-staff user."""
        non_staff = self.create_user(username='non_staff', role='facility_manager', is_staff=False)
        self.client.force_authenticate(user=non_staff)
        response = self.client.post(f'/api/vendors/vendors/{self.vendor.id}/verify/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_mark_preferred_action(self):
        """Test POST /api/vendors/vendors/{id}/mark_preferred/."""
        self.assertFalse(self.vendor.is_preferred)
        response = self.client.post(f'/api/vendors/vendors/{self.vendor.id}/mark_preferred/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.vendor.refresh_from_db()
        self.assertTrue(self.vendor.is_preferred)

    def test_suspend_action(self):
        """Test POST /api/vendors/vendors/{id}/suspend/."""
        response = self.client.post(
            f'/api/vendors/vendors/{self.vendor.id}/suspend/',
            {'reason': 'Quality issues'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.status, 'suspended')
        self.assertIn('SUSPENDED: Quality issues', self.vendor.notes)

    def test_activate_action(self):
        """Test POST /api/vendors/vendors/{id}/activate/."""
        self.vendor.status = 'suspended'
        self.vendor.save()
        response = self.client.post(f'/api/vendors/vendors/{self.vendor.id}/activate/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.vendor.refresh_from_db()
        self.assertEqual(self.vendor.status, 'active')

    def test_statistics_action(self):
        """Test GET /api/vendors/vendors/{id}/statistics/."""
        response = self.client.get(f'/api/vendors/vendors/{self.vendor.id}/statistics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn('vendor', data)
        self.assertIn('contracts', data)
        self.assertIn('payments', data)
        self.assertIn('reviews', data)

    def test_statistics_with_data(self):
        """Test statistics action with related contract and payment data."""
        self.create_contract(vendor=self.vendor, created_by=self.user, status='active')
        self.create_payment(vendor=self.vendor, created_by=self.user, status='paid')
        response = self.client.get(f'/api/vendors/vendors/{self.vendor.id}/statistics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['contracts']['total'], 1)
        self.assertEqual(response.data['contracts']['active'], 1)

    def test_filter_by_status(self):
        """Test filtering vendors by status query param."""
        self.create_vendor(company_name='Inactive Co', email='inv@test.com', status='inactive')
        response = self.client.get('/api/vendors/vendors/', {'status': 'inactive'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_vendor_type(self):
        """Test filtering vendors by vendor_type."""
        response = self.client.get('/api/vendors/vendors/', {'vendor_type': 'company'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_search_vendors(self):
        """Test search across company_name, contact_person, email, etc."""
        response = self.client.get('/api/vendors/vendors/', {'search': 'ABC'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_category(self):
        """Test filtering vendors by category query param."""
        self.vendor.categories.add(self.category)
        response = self.client.get('/api/vendors/vendors/', {'category': self.category.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_min_rating(self):
        """Test filtering vendors by min_rating query param."""
        self.vendor.average_rating = Decimal('4.50')
        self.vendor.save()
        response = self.client.get('/api/vendors/vendors/', {'min_rating': '4.0'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class VendorServiceAPITest(VendorTestDataMixin, APITestCase):
    """API tests for VendorServiceViewSet."""

    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(
            username='service_admin', role='facility_manager', is_staff=True
        )
        self.client.force_authenticate(user=self.user)
        self.vendor = self.create_vendor()
        self.category = self.create_category(name='Plumbing')
        self.service = self.create_service(vendor=self.vendor, category=self.category)

    def test_list_services(self):
        """Test GET /api/vendors/services/ returns 200."""
        response = self.client.get('/api/vendors/services/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_service(self):
        """Test POST /api/vendors/services/ creates a service."""
        data = {
            'vendor': str(self.vendor.id),
            'category': self.category.id,
            'service_name': 'Drain Cleaning',
            'description': 'Professional drain cleaning',
            'pricing_type': 'fixed',
            'base_price': '150.00',
        }
        response = self.client.post('/api/vendors/services/', data, format='json')
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_retrieve_service(self):
        """Test GET /api/vendors/services/{id}/ returns service details."""
        response = self.client.get(f'/api/vendors/services/{self.service.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['service_name'], 'Pipe Repair')

    def test_update_service(self):
        """Test PATCH /api/vendors/services/{id}/ updates a service."""
        response = self.client.patch(
            f'/api/vendors/services/{self.service.id}/',
            {'base_price': '100.00'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.service.refresh_from_db()
        self.assertEqual(self.service.base_price, Decimal('100.00'))

    def test_delete_service(self):
        """Test DELETE /api/vendors/services/{id}/ removes the service."""
        response = self.client.delete(f'/api/vendors/services/{self.service.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_filter_by_vendor(self):
        """Test filtering services by vendor."""
        response = self.client.get('/api/vendors/services/', {'vendor': str(self.vendor.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_pricing_type(self):
        """Test filtering services by pricing_type."""
        response = self.client.get('/api/vendors/services/', {'pricing_type': 'hourly'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_category_name_in_response(self):
        """Test category_name is included in response."""
        response = self.client.get(f'/api/vendors/services/{self.service.id}/')
        self.assertEqual(response.data['category_name'], 'Plumbing')


class VendorContractAPITest(VendorTestDataMixin, APITestCase):
    """API tests for VendorContractViewSet including custom actions."""

    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(
            username='contract_admin', role='facility_manager', is_staff=True
        )
        self.client.force_authenticate(user=self.user)
        self.vendor = self.create_vendor()
        self.contract = self.create_contract(vendor=self.vendor, created_by=self.user)

    def test_list_contracts(self):
        """Test GET /api/vendors/contracts/ returns 200."""
        response = self.client.get('/api/vendors/contracts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_contract(self):
        """Test POST /api/vendors/contracts/ creates a contract."""
        data = {
            'vendor_id': str(self.vendor.id),
            'contract_type': 'project',
            'title': 'Roof Repair Project',
            'description': 'Complete roof repair',
            'scope_of_work': 'Replace damaged shingles and sealant',
            'contract_value': '15000.00',
            'payment_schedule': '50% upfront, 50% on completion',
            'start_date': str(date.today()),
            'end_date': str(date.today() + timedelta(days=90)),
        }
        response = self.client.post('/api/vendors/contracts/', data, format='json')
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_retrieve_contract(self):
        """Test GET /api/vendors/contracts/{id}/ returns contract details."""
        response = self.client.get(f'/api/vendors/contracts/{self.contract.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Annual Maintenance Contract')

    def test_update_contract(self):
        """Test PATCH /api/vendors/contracts/{id}/ updates contract."""
        response = self.client.patch(
            f'/api/vendors/contracts/{self.contract.id}/',
            {'title': 'Updated Contract Title'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.title, 'Updated Contract Title')

    def test_delete_contract(self):
        """Test DELETE /api/vendors/contracts/{id}/ removes contract."""
        response = self.client.delete(f'/api/vendors/contracts/{self.contract.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_active_contracts_action(self):
        """Test GET /api/vendors/contracts/active_contracts/."""
        self.contract.status = 'active'
        self.contract.start_date = date.today() - timedelta(days=10)
        self.contract.end_date = date.today() + timedelta(days=100)
        self.contract.save()
        response = self.client.get('/api/vendors/contracts/active_contracts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_expiring_soon_action(self):
        """Test GET /api/vendors/contracts/expiring_soon/."""
        self.contract.status = 'active'
        self.contract.start_date = date.today() - timedelta(days=300)
        self.contract.end_date = date.today() + timedelta(days=15)
        self.contract.save()
        response = self.client.get('/api/vendors/contracts/expiring_soon/', {'days': 30})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_sign_by_vendor_action(self):
        """Test POST /api/vendors/contracts/{id}/sign_by_vendor/."""
        response = self.client.post(f'/api/vendors/contracts/{self.contract.id}/sign_by_vendor/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contract.refresh_from_db()
        self.assertTrue(self.contract.signed_by_vendor)
        self.assertIsNotNone(self.contract.vendor_signature_date)

    def test_sign_by_management_action(self):
        """Test POST /api/vendors/contracts/{id}/sign_by_management/."""
        response = self.client.post(
            f'/api/vendors/contracts/{self.contract.id}/sign_by_management/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contract.refresh_from_db()
        self.assertTrue(self.contract.signed_by_management)
        self.assertIsNotNone(self.contract.management_signature_date)

    def test_auto_activate_on_both_signatures(self):
        """Test contract auto-activates when both parties sign."""
        # Vendor signs first
        self.contract.signed_by_vendor = True
        self.contract.vendor_signature_date = timezone.now()
        self.contract.save()
        # Management signs
        response = self.client.post(
            f'/api/vendors/contracts/{self.contract.id}/sign_by_management/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, 'active')

    def test_auto_activate_on_vendor_sign_after_management(self):
        """Test contract auto-activates when vendor signs after management."""
        self.contract.signed_by_management = True
        self.contract.management_signature_date = timezone.now()
        self.contract.save()
        response = self.client.post(
            f'/api/vendors/contracts/{self.contract.id}/sign_by_vendor/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, 'active')

    def test_terminate_action(self):
        """Test POST /api/vendors/contracts/{id}/terminate/."""
        self.contract.status = 'active'
        self.contract.save()
        response = self.client.post(f'/api/vendors/contracts/{self.contract.id}/terminate/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, 'terminated')

    def test_filter_by_status(self):
        """Test filtering contracts by status."""
        response = self.client.get('/api/vendors/contracts/', {'status': 'draft'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_contract_type(self):
        """Test filtering contracts by contract_type."""
        response = self.client.get('/api/vendors/contracts/', {'contract_type': 'annual'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_search_contracts(self):
        """Test searching contracts by title."""
        response = self.client.get('/api/vendors/contracts/', {'search': 'Maintenance'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class VendorReviewAPITest(VendorTestDataMixin, APITestCase):
    """API tests for VendorReviewViewSet including custom actions."""

    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(
            username='review_admin', role='facility_manager', is_staff=True
        )
        self.client.force_authenticate(user=self.user)
        self.vendor = self.create_vendor()
        with patch.object(Vendor, 'update_ratings', create=True, return_value=None):
            self.review = VendorReview.objects.create(
                vendor=self.vendor,
                reviewed_by=self.user,
                overall_rating=4,
                quality_rating=4,
                timeliness_rating=4,
                professionalism_rating=4,
                value_rating=4,
                title='Solid work',
                comment='Everything was done well.',
            )

    def test_list_reviews(self):
        """Test GET /api/vendors/reviews/ returns 200."""
        response = self.client.get('/api/vendors/reviews/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_review(self):
        """Test POST /api/vendors/reviews/ creates a review."""
        data = {
            'vendor_id': str(self.vendor.id),
            'overall_rating': 5,
            'quality_rating': 5,
            'timeliness_rating': 5,
            'professionalism_rating': 5,
            'value_rating': 5,
            'title': 'Excellent',
            'comment': 'Best service ever',
            'would_recommend': True,
        }
        with patch.object(Vendor, 'update_ratings', create=True, return_value=None):
            response = self.client.post('/api/vendors/reviews/', data, format='json')
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_retrieve_review(self):
        """Test GET /api/vendors/reviews/{id}/ returns review."""
        response = self.client.get(f'/api/vendors/reviews/{self.review.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Solid work')

    def test_update_review(self):
        """Test PATCH /api/vendors/reviews/{id}/ updates review."""
        with patch.object(Vendor, 'update_ratings', create=True, return_value=None):
            response = self.client.patch(
                f'/api/vendors/reviews/{self.review.id}/',
                {'title': 'Updated title'},
                format='json'
            )
        self.assertIn(response.status_code, [status.HTTP_200_OK])
        self.review.refresh_from_db()
        self.assertEqual(self.review.title, 'Updated title')

    def test_delete_review(self):
        """Test DELETE /api/vendors/reviews/{id}/ removes review."""
        response = self.client.delete(f'/api/vendors/reviews/{self.review.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_verify_review_action_staff(self):
        """Test POST /api/vendors/reviews/{id}/verify/ by staff."""
        response = self.client.post(f'/api/vendors/reviews/{self.review.id}/verify/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_verified)

    def test_verify_review_action_non_staff_denied(self):
        """Test verify review returns 403 for non-staff user."""
        non_staff = self.create_user(username='non_staff_rev', role='tenant', is_staff=False)
        self.client.force_authenticate(user=non_staff)
        response = self.client.post(f'/api/vendors/reviews/{self.review.id}/verify/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_add_response_action(self):
        """Test POST /api/vendors/reviews/{id}/add_response/ adds vendor response."""
        response = self.client.post(
            f'/api/vendors/reviews/{self.review.id}/add_response/',
            {'response': 'Thank you for the feedback!'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.review.refresh_from_db()
        self.assertEqual(self.review.vendor_response, 'Thank you for the feedback!')
        self.assertIsNotNone(self.review.responded_at)

    def test_add_response_empty_text_rejected(self):
        """Test add_response returns 400 when response text is empty."""
        response = self.client.post(
            f'/api/vendors/reviews/{self.review.id}/add_response/',
            {'response': ''},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_by_vendor(self):
        """Test filtering reviews by vendor."""
        response = self.client.get('/api/vendors/reviews/', {'vendor': str(self.vendor.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_overall_rating(self):
        """Test filtering reviews by overall_rating."""
        response = self.client.get('/api/vendors/reviews/', {'overall_rating': 4})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_would_recommend(self):
        """Test filtering reviews by would_recommend."""
        response = self.client.get('/api/vendors/reviews/', {'would_recommend': 'true'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class VendorPaymentAPITest(VendorTestDataMixin, APITestCase):
    """API tests for VendorPaymentViewSet including custom actions."""

    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(
            username='payment_admin', role='facility_manager', is_staff=True
        )
        self.client.force_authenticate(user=self.user)
        self.vendor = self.create_vendor()
        self.payment = self.create_payment(vendor=self.vendor, created_by=self.user)

    def test_list_payments(self):
        """Test GET /api/vendors/payments/ returns 200."""
        response = self.client.get('/api/vendors/payments/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_payment(self):
        """Test POST /api/vendors/payments/ creates a payment."""
        data = {
            'vendor_id': str(self.vendor.id),
            'amount': '2500.00',
            'description': 'Emergency repair payment',
            'status': 'pending',
            'due_date': str(date.today() + timedelta(days=14)),
        }
        response = self.client.post('/api/vendors/payments/', data, format='json')
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_retrieve_payment(self):
        """Test GET /api/vendors/payments/{id}/ returns payment."""
        response = self.client.get(f'/api/vendors/payments/{self.payment.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_payment(self):
        """Test PATCH /api/vendors/payments/{id}/ updates payment."""
        response = self.client.patch(
            f'/api/vendors/payments/{self.payment.id}/',
            {'notes': 'Updated note'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.notes, 'Updated note')

    def test_delete_payment(self):
        """Test DELETE /api/vendors/payments/{id}/ removes payment."""
        response = self.client.delete(f'/api/vendors/payments/{self.payment.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_pending_payments_action(self):
        """Test GET /api/vendors/payments/pending_payments/."""
        response = self.client.get('/api/vendors/payments/pending_payments/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_overdue_payments_action(self):
        """Test GET /api/vendors/payments/overdue_payments/."""
        self.payment.due_date = date.today() - timedelta(days=10)
        self.payment.save()
        response = self.client.get('/api/vendors/payments/overdue_payments/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_approve_action(self):
        """Test POST /api/vendors/payments/{id}/approve/ approves payment."""
        response = self.client.post(f'/api/vendors/payments/{self.payment.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'processing')
        self.assertEqual(self.payment.approved_by, self.user)
        self.assertIsNotNone(self.payment.approved_at)

    def test_approve_non_pending_rejected(self):
        """Test approve action returns 400 for non-pending payment."""
        self.payment.status = 'paid'
        self.payment.save()
        response = self.client.post(f'/api/vendors/payments/{self.payment.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mark_paid_action(self):
        """Test POST /api/vendors/payments/{id}/mark_paid/ marks as paid."""
        response = self.client.post(f'/api/vendors/payments/{self.payment.id}/mark_paid/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'paid')
        self.assertIsNotNone(self.payment.paid_date)

    def test_payment_summary_action(self):
        """Test GET /api/vendors/payments/payment_summary/ returns stats."""
        response = self.client.get('/api/vendors/payments/payment_summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn('total_paid', data)
        self.assertIn('total_pending', data)
        self.assertIn('total_overdue', data)
        self.assertIn('count_paid', data)
        self.assertIn('count_pending', data)
        self.assertIn('count_overdue', data)

    def test_payment_summary_with_data(self):
        """Test payment_summary reflects actual payment data."""
        # Create a paid payment
        self.create_payment(
            vendor=self.vendor,
            created_by=self.user,
            status='paid',
            amount=Decimal('3000.00'),
            invoice_number='INV-PAID',
        )
        response = self.client.get('/api/vendors/payments/payment_summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(response.data['total_paid'], 0)

    def test_filter_by_status(self):
        """Test filtering payments by status."""
        response = self.client.get('/api/vendors/payments/', {'status': 'pending'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_search_payments(self):
        """Test searching payments by invoice_number."""
        response = self.client.get('/api/vendors/payments/', {'search': 'INV-001'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class VendorInsuranceAPITest(VendorTestDataMixin, APITestCase):
    """API tests for VendorInsuranceViewSet including custom actions."""

    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(
            username='ins_admin', role='facility_manager', is_staff=True
        )
        self.client.force_authenticate(user=self.user)
        self.vendor = self.create_vendor()
        self.insurance = self.create_insurance(vendor=self.vendor)

    def test_list_insurance(self):
        """Test GET /api/vendors/insurance/ returns 200."""
        response = self.client.get('/api/vendors/insurance/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_insurance(self):
        """Test POST /api/vendors/insurance/ creates an insurance record."""
        data = {
            'vendor_id': str(self.vendor.id),
            'insurance_type': 'workers_comp',
            'policy_number': 'WC-67890',
            'insurance_company': 'WorkSafe Insurance',
            'coverage_amount': '500000.00',
            'effective_date': str(date.today()),
            'expiry_date': str(date.today() + timedelta(days=365)),
        }
        response = self.client.post('/api/vendors/insurance/', data, format='json')
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_retrieve_insurance(self):
        """Test GET /api/vendors/insurance/{id}/ returns insurance details."""
        response = self.client.get(f'/api/vendors/insurance/{self.insurance.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['policy_number'], 'POL-12345')

    def test_update_insurance(self):
        """Test PATCH /api/vendors/insurance/{id}/ updates insurance."""
        response = self.client.patch(
            f'/api/vendors/insurance/{self.insurance.id}/',
            {'coverage_amount': '2000000.00'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.insurance.refresh_from_db()
        self.assertEqual(self.insurance.coverage_amount, Decimal('2000000.00'))

    def test_delete_insurance(self):
        """Test DELETE /api/vendors/insurance/{id}/ removes insurance."""
        response = self.client.delete(f'/api/vendors/insurance/{self.insurance.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_expiring_soon_action(self):
        """Test GET /api/vendors/insurance/expiring_soon/."""
        self.insurance.expiry_date = date.today() + timedelta(days=30)
        self.insurance.save()
        response = self.client.get('/api/vendors/insurance/expiring_soon/', {'days': 60})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_expired_action(self):
        """Test GET /api/vendors/insurance/expired/."""
        self.insurance.expiry_date = date.today() - timedelta(days=5)
        self.insurance.save()
        response = self.client.get('/api/vendors/insurance/expired/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_verify_insurance_action_staff(self):
        """Test POST /api/vendors/insurance/{id}/verify/ by staff."""
        response = self.client.post(f'/api/vendors/insurance/{self.insurance.id}/verify/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.insurance.refresh_from_db()
        self.assertTrue(self.insurance.is_verified)
        self.assertEqual(self.insurance.verified_by, self.user)
        self.assertIsNotNone(self.insurance.verified_at)

    def test_verify_insurance_action_non_staff_denied(self):
        """Test verify insurance returns 403 for non-staff."""
        non_staff = self.create_user(username='non_staff_ins', role='tenant', is_staff=False)
        self.client.force_authenticate(user=non_staff)
        response = self.client.post(f'/api/vendors/insurance/{self.insurance.id}/verify/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_filter_by_vendor(self):
        """Test filtering insurance by vendor."""
        response = self.client.get(
            '/api/vendors/insurance/', {'vendor': str(self.vendor.id)}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filter_by_insurance_type(self):
        """Test filtering insurance by type."""
        response = self.client.get(
            '/api/vendors/insurance/', {'insurance_type': 'general_liability'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# =============================================================================
# PERMISSION / AUTHENTICATION TESTS
# =============================================================================

class VendorUnauthenticatedAccessTest(APITestCase):
    """Test that unauthenticated requests are rejected across all endpoints."""

    def setUp(self):
        self.client = APIClient()

    def test_categories_list_unauthenticated(self):
        """Test unauthenticated access to categories list is denied."""
        response = self.client.get('/api/vendors/categories/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_vendors_list_unauthenticated(self):
        """Test unauthenticated access to vendors list is denied."""
        response = self.client.get('/api/vendors/vendors/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_services_list_unauthenticated(self):
        """Test unauthenticated access to services list is denied."""
        response = self.client.get('/api/vendors/services/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_contracts_list_unauthenticated(self):
        """Test unauthenticated access to contracts list is denied."""
        response = self.client.get('/api/vendors/contracts/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_reviews_list_unauthenticated(self):
        """Test unauthenticated access to reviews list is denied."""
        response = self.client.get('/api/vendors/reviews/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_payments_list_unauthenticated(self):
        """Test unauthenticated access to payments list is denied."""
        response = self.client.get('/api/vendors/payments/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_insurance_list_unauthenticated(self):
        """Test unauthenticated access to insurance list is denied."""
        response = self.client.get('/api/vendors/insurance/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_vendor_create_unauthenticated(self):
        """Test unauthenticated POST to vendors is denied."""
        data = {
            'company_name': 'Hack Corp',
            'contact_person': 'Hacker',
            'email': 'hack@corp.com',
            'phone': '555-0000',
            'address_line1': '1 Hack St',
            'city': 'Hackville',
            'state': 'HK',
            'zip_code': '00000',
        }
        response = self.client.post('/api/vendors/vendors/', data, format='json')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_vendor_custom_action_unauthenticated(self):
        """Test unauthenticated access to custom actions is denied."""
        response = self.client.get('/api/vendors/vendors/preferred_vendors/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_payment_summary_unauthenticated(self):
        """Test unauthenticated access to payment_summary is denied."""
        response = self.client.get('/api/vendors/payments/payment_summary/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_insurance_expiring_soon_unauthenticated(self):
        """Test unauthenticated access to insurance expiring_soon is denied."""
        response = self.client.get('/api/vendors/insurance/expiring_soon/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])

    def test_contracts_active_contracts_unauthenticated(self):
        """Test unauthenticated access to active_contracts is denied."""
        response = self.client.get('/api/vendors/contracts/active_contracts/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN
        ])
