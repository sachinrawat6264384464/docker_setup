# visitors/tests.py
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from .models import (
    VisitorType, Visitor, VisitorPass, VisitorLog,
    BlacklistedVisitor, VisitorFeedback
)

User = get_user_model()


class VisitorTypeTestCase(TestCase):
    def setUp(self):
        self.visitor_type = VisitorType.objects.create(
            name='Guest',
            description='Regular guest visitor',
            requires_approval=True,
            max_duration_hours=4
        )
    
    def test_visitor_type_creation(self):
        """Test visitor type is created correctly"""
        self.assertEqual(self.visitor_type.name, 'Guest')
        self.assertTrue(self.visitor_type.requires_approval)
        self.assertEqual(self.visitor_type.max_duration_hours, 4)


class VisitorTestCase(TestCase):
    def setUp(self):
        self.visitor = Visitor.objects.create(
            first_name='John',
            last_name='Doe',
            email='john.doe@example.com',
            phone='+1234567890'
        )
    
    def test_visitor_creation(self):
        """Test visitor is created with auto-generated visitor number"""
        self.assertIsNotNone(self.visitor.visitor_number)
        self.assertTrue(self.visitor.visitor_number.startswith('VIS-'))
    
    def test_visitor_full_name(self):
        """Test get_full_name method"""
        self.assertEqual(self.visitor.get_full_name(), 'John Doe')
    
    def test_visitor_blacklist(self):
        """Test visitor blacklist functionality"""
        self.assertFalse(self.visitor.is_blacklisted)
        
        self.visitor.is_blacklisted = True
        self.visitor.blacklist_reason = 'Test reason'
        self.visitor.save()
        
        self.assertTrue(self.visitor.is_blacklisted)
        self.assertEqual(self.visitor.blacklist_reason, 'Test reason')


class VisitorPassTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testhost',
            email='host@example.com',
            password='testpass123'
        )
        
        self.visitor_type = VisitorType.objects.create(
            name='Guest',
            requires_approval=False
        )
        
        self.visitor = Visitor.objects.create(
            first_name='Jane',
            last_name='Smith',
            phone='+1234567890'
        )
        
        self.visitor_pass = VisitorPass.objects.create(
            visitor=self.visitor,
            visitor_type=self.visitor_type,
            host=self.user,
            purpose='Social visit',
            building='Building A',
            unit_number='101',
            expected_arrival=timezone.now() + timedelta(hours=1),
            expected_departure=timezone.now() + timedelta(hours=5)
        )
    
    def test_visitor_pass_creation(self):
        """Test visitor pass is created with auto-generated pass number"""
        self.assertIsNotNone(self.visitor_pass.pass_number)
        self.assertTrue(self.visitor_pass.pass_number.startswith('PASS-'))
        self.assertIsNotNone(self.visitor_pass.access_code)
    
    def test_visitor_pass_status(self):
        """Test visitor pass status"""
        self.assertEqual(self.visitor_pass.status, 'pending')
    
    def test_visitor_pass_check_in(self):
        """Test visitor check-in functionality"""
        self.visitor_pass.status = 'approved'
        self.visitor_pass.save()
        
        self.visitor_pass.check_in()
        
        self.assertEqual(self.visitor_pass.status, 'active')
        self.assertIsNotNone(self.visitor_pass.actual_arrival)
        self.assertEqual(self.visitor_pass.visitor.visit_count, 1)
    
    def test_visitor_pass_check_out(self):
        """Test visitor check-out functionality"""
        self.visitor_pass.status = 'active'
        self.visitor_pass.actual_arrival = timezone.now()
        self.visitor_pass.save()
        
        self.visitor_pass.check_out()
        
        self.assertEqual(self.visitor_pass.status, 'completed')
        self.assertIsNotNone(self.visitor_pass.actual_departure)
    
    def test_visitor_pass_is_expired(self):
        """Test is_expired method"""
        # Create pass with past departure time
        past_pass = VisitorPass.objects.create(
            visitor=self.visitor,
            visitor_type=self.visitor_type,
            host=self.user,
            purpose='Past visit',
            building='Building A',
            unit_number='101',
            expected_arrival=timezone.now() - timedelta(hours=5),
            expected_departure=timezone.now() - timedelta(hours=1)
        )
        
        self.assertTrue(past_pass.is_expired())
        self.assertFalse(self.visitor_pass.is_expired())


class BlacklistedVisitorTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='security',
            email='security@example.com',
            password='testpass123'
        )
        
        self.visitor = Visitor.objects.create(
            first_name='Bad',
            last_name='Actor',
            phone='+1234567890'
        )
        
        self.blacklist = BlacklistedVisitor.objects.create(
            visitor=self.visitor,
            reason='Caused disturbance',
            blacklisted_by=self.user,
            is_permanent=False,
            expires_at=timezone.now().date() + timedelta(days=30)
        )
    
    def test_blacklist_is_active(self):
        """Test blacklist is_active method"""
        self.assertTrue(self.blacklist.is_active())
    
    def test_blacklist_expired(self):
        """Test expired blacklist"""
        self.blacklist.expires_at = timezone.now().date() - timedelta(days=1)
        self.blacklist.save()
        
        self.assertFalse(self.blacklist.is_active())
    
    def test_permanent_blacklist(self):
        """Test permanent blacklist"""
        permanent = BlacklistedVisitor.objects.create(
            visitor=self.visitor,
            reason='Serious violation',
            blacklisted_by=self.user,
            is_permanent=True
        )
        
        self.assertTrue(permanent.is_active())


class VisitorFeedbackTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testhost',
            password='testpass123'
        )
        
        self.visitor_type = VisitorType.objects.create(name='Guest')
        self.visitor = Visitor.objects.create(
            first_name='Happy',
            last_name='Visitor',
            phone='+1234567890'
        )
        
        self.visitor_pass = VisitorPass.objects.create(
            visitor=self.visitor,
            visitor_type=self.visitor_type,
            host=self.user,
            purpose='Visit',
            building='A',
            unit_number='101',
            expected_arrival=timezone.now(),
            expected_departure=timezone.now() + timedelta(hours=2)
        )
        
        self.feedback = VisitorFeedback.objects.create(
            visitor_pass=self.visitor_pass,
            rating=5,
            security_staff_rating=5,
            process_ease_rating=4,
            comments='Great experience!',
            would_recommend=True
        )
    
    def test_feedback_creation(self):
        """Test feedback is created correctly"""
        self.assertEqual(self.feedback.rating, 5)
        self.assertTrue(self.feedback.would_recommend)
        self.assertEqual(self.feedback.comments, 'Great experience!')