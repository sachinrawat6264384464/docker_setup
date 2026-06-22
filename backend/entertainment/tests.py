# ========================================
# FILE 6: entertainment/tests.py
# ========================================
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from .models import Event, EventRegistration, Club

User = get_user_model()


class EventTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        self.event = Event.objects.create(
            title='Summer BBQ',
            description='Annual summer BBQ event',
            event_type='party',
            start_date=timezone.now().date() + timedelta(days=7),
            end_date=timezone.now().date() + timedelta(days=7),
            start_time=timezone.now().time(),
            end_time=(timezone.now() + timedelta(hours=4)).time(),
            venue='Community Garden',
            max_attendees=50,
            organized_by='Community Committee',
            contact_person='John Doe',
            contact_phone='123-456-7890',
            contact_email='john@example.com',
            created_by=self.user
        )
    
    def test_event_creation(self):
        """Test event is created correctly"""
        self.assertEqual(self.event.title, 'Summer BBQ')
        self.assertEqual(self.event.event_type, 'party')
        self.assertEqual(self.event.current_attendees, 0)
        self.assertEqual(self.event.status, 'draft')
    
    def test_event_str(self):
        """Test string representation"""
        expected = f"Summer BBQ - {self.event.start_date}"
        self.assertEqual(str(self.event), expected)


class EventRegistrationTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        self.event = Event.objects.create(
            title='Test Event',
            description='Test',
            event_type='workshop',
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
            start_time=timezone.now().time(),
            end_time=timezone.now().time(),
            venue='Test Venue',
            max_attendees=10,
            organized_by='Test Org',
            contact_person='Test Person',
            contact_phone='123-456-7890',
            contact_email='test@example.com'
        )
        
        self.registration = EventRegistration.objects.create(
            event=self.event,
            user=self.user,
            number_of_guests=2
        )
    
    def test_registration_creation(self):
        """Test registration is created"""
        self.assertEqual(self.registration.event, self.event)
        self.assertEqual(self.registration.user, self.user)
        self.assertEqual(self.registration.number_of_guests, 2)
        self.assertEqual(self.registration.status, 'registered')


class ClubTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin',
            password='testpass123'
        )
        
        self.club = Club.objects.create(
            name='Book Club',
            description='Monthly book discussions',
            category='reading',
            admin=self.admin,
            max_members=20
        )
    
    def test_club_creation(self):
        """Test club is created"""
        self.assertEqual(self.club.name, 'Book Club')
        self.assertEqual(self.club.category, 'reading')
        self.assertTrue(self.club.is_active)
    
    def test_member_count(self):
        """Test member count method"""
        self.assertEqual(self.club.member_count(), 0)
        
        user = User.objects.create_user(
            username='member',
            password='testpass123'
        )
        self.club.members.add(user)
        
        self.assertEqual(self.club.member_count(), 1)
    
    def test_is_full(self):
        """Test is_full method"""
        self.assertFalse(self.club.is_full())
        
        # Add max members
        for i in range(20):
            user = User.objects.create_user(
                username=f'user{i}',
                password='testpass123'
            )
            self.club.members.add(user)
        
        self.assertTrue(self.club.is_full())