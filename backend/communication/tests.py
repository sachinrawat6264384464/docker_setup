# communication/tests.py
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import timedelta
import uuid

from .models import (
    Conversation, ConversationParticipant, Message,
    MessageAttachment, MessageReaction, MessageReadReceipt,
    Announcement, AnnouncementAttachment, AnnouncementView
)

User = get_user_model()


class CommunicationTestMixin:
    def _create_user(self, role='tenant', **kwargs):
        defaults = {
            'username': f'user_{uuid.uuid4().hex[:8]}',
            'email': f'{uuid.uuid4().hex[:8]}@test.com',
            'password': 'TestPass123!', 'role': role, 'is_active': True,
        }
        defaults.update(kwargs)
        pw = defaults.pop('password')
        return User.objects.create_user(password=pw, **defaults)

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def _create_conversation(self, created_by=None, participants=None, **kwargs):
        if created_by is None:
            created_by = self._create_user()
        defaults = {
            'conversation_type': 'direct', 'title': 'Test conversation',
            'created_by': created_by,
        }
        defaults.update(kwargs)
        conv = Conversation.objects.create(**defaults)
        ConversationParticipant.objects.create(conversation=conv, user=created_by, role='admin')
        if participants:
            for p in participants:
                ConversationParticipant.objects.create(conversation=conv, user=p)
        return conv

    def _create_message(self, conversation=None, sender=None, **kwargs):
        if sender is None:
            sender = self._create_user()
        if conversation is None:
            conversation = self._create_conversation(created_by=sender)
        defaults = {
            'conversation': conversation, 'sender': sender,
            'message_type': 'text', 'content': 'Hello world',
        }
        defaults.update(kwargs)
        return Message.objects.create(**defaults)

    def _create_announcement(self, created_by=None, **kwargs):
        if created_by is None:
            created_by = self._create_user(role='master_admin', is_staff=True)
        defaults = {
            'title': 'Building update', 'content': 'New parking rules',
            'announcement_type': 'general', 'priority': 'medium',
            'created_by': created_by, 'target_all': True,
            'is_published': False,
        }
        defaults.update(kwargs)
        return Announcement.objects.create(**defaults)


class ConversationModelTests(CommunicationTestMixin, TestCase):
    def test_create_conversation(self):
        c = self._create_conversation()
        self.assertEqual(c.conversation_type, 'direct')
        self.assertFalse(c.is_locked)

    def test_str(self):
        c = self._create_conversation(title='Chat room')
        self.assertIn('Chat room', str(c))


class MessageModelTests(CommunicationTestMixin, TestCase):
    def test_create_message(self):
        m = self._create_message()
        self.assertEqual(m.content, 'Hello world')
        self.assertFalse(m.is_edited)
        self.assertFalse(m.is_deleted)

    def test_message_updates_conversation(self):
        user = self._create_user()
        conv = self._create_conversation(created_by=user)
        m = self._create_message(conversation=conv, sender=user)
        conv.refresh_from_db()
        self.assertIsNotNone(conv.last_message_at)


class AnnouncementModelTests(CommunicationTestMixin, TestCase):
    def test_create_announcement(self):
        a = self._create_announcement()
        self.assertFalse(a.is_published)
        self.assertTrue(a.target_all)

    def test_auto_generated_number(self):
        a = self._create_announcement()
        self.assertIsNotNone(a.announcement_number)
        self.assertTrue(len(a.announcement_number) > 0)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ConversationAPITests(CommunicationTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant1 = self._create_user(role='tenant')
        self.tenant2 = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_conversations(self):
        self._create_conversation(created_by=self.tenant1, participants=[self.tenant2])
        self._auth(self.tenant1)
        resp = self.client.get('/api/communication/conversations/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_my_conversations_action(self):
        self._create_conversation(created_by=self.tenant1, participants=[self.tenant2])
        self._auth(self.tenant1)
        resp = self.client.get('/api/communication/conversations/my_conversations/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_archive_action(self):
        conv = self._create_conversation(created_by=self.tenant1, participants=[self.tenant2])
        self._auth(self.tenant1)
        resp = self.client.post(f'/api/communication/conversations/{conv.id}/archive/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_mute_action(self):
        conv = self._create_conversation(created_by=self.tenant1, participants=[self.tenant2])
        self._auth(self.tenant1)
        resp = self.client.post(f'/api/communication/conversations/{conv.id}/mute/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_pin_action(self):
        conv = self._create_conversation(created_by=self.tenant1, participants=[self.tenant2])
        self._auth(self.tenant1)
        resp = self.client.post(f'/api/communication/conversations/{conv.id}/pin/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class MessageAPITests(CommunicationTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant1 = self._create_user(role='tenant')
        self.tenant2 = self._create_user(role='tenant')
        self.conv = self._create_conversation(created_by=self.tenant1, participants=[self.tenant2])
        self.client = APIClient()

    def test_list_messages(self):
        self._create_message(conversation=self.conv, sender=self.tenant1)
        self._auth(self.tenant1)
        resp = self.client.get('/api/communication/messages/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_conversation_messages_action(self):
        self._create_message(conversation=self.conv, sender=self.tenant1)
        self._auth(self.tenant1)
        resp = self.client.get(f'/api/communication/messages/conversation_messages/?conversation_id={self.conv.id}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_react_action(self):
        msg = self._create_message(conversation=self.conv, sender=self.tenant1)
        self._auth(self.tenant2)
        data = {'emoji': '👍'}
        resp = self.client.post(f'/api/communication/messages/{msg.id}/react/', data, format='json')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CommAnnouncementAPITests(CommunicationTestMixin, APITestCase):
    def setUp(self):
        self.admin = self._create_user(role='master_admin', is_staff=True)
        self.tenant = self._create_user(role='tenant')
        self.client = APIClient()

    def test_list_announcements(self):
        self._auth(self.admin)
        resp = self.client.get('/api/communication/announcements/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_publish_action(self):
        ann = self._create_announcement(created_by=self.admin)
        self._auth(self.admin)
        resp = self.client.post(f'/api/communication/announcements/{ann.id}/publish/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_mark_as_viewed_action(self):
        ann = self._create_announcement(created_by=self.admin, is_published=True)
        self._auth(self.tenant)
        resp = self.client.post(f'/api/communication/announcements/{ann.id}/mark_as_viewed/')
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])

    def test_unread_action(self):
        self._auth(self.tenant)
        resp = self.client.get('/api/communication/announcements/unread/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_urgent_action(self):
        self._auth(self.tenant)
        resp = self.client.get('/api/communication/announcements/urgent/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
