# communication/views.py
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from django.db.models import Q, Count, Max, F
from django.utils import timezone
from datetime import timedelta
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.auth import get_user_model

from accounts.permissions import ModulePermissionMixin, HasModulePermission

from .models import (
    Conversation, ConversationParticipant, Message, MessageAttachment,
    MessageReaction, MessageReadReceipt, Announcement, AnnouncementView
)
from .serializers import (
    ConversationSerializer, ConversationCreateSerializer,
    MessageSerializer, MessageAttachmentSerializer,
    MessageReactionSerializer, AnnouncementSerializer,
    ConversationParticipantSerializer
)
from properties.models import Building, Unit

User = get_user_model()

RESIDENT_ROLES = ('tenant', 'owner', 'tenant_vendor')
MANAGER_ROLES = ('facility_manager', 'manager')


def _safe_str(value):
    return (str(value).strip() if value is not None else '')


def _get_user_unit_context(user):
    if not user or not user.is_authenticated:
        return None

    building_name = _safe_str(getattr(user, 'building_name', ''))
    unit_number = _safe_str(getattr(user, 'unit_number', ''))
    
    unit = None
    
    # 1. Try resolving from profile fields
    if building_name and unit_number:
        unit = (
            Unit.objects.filter(
                building__name__iexact=building_name.strip(),
                unit_number__iexact=unit_number.strip(),
            )
            .select_related('building__township', 'floor_ref__block')
            .first()
        )

    # 2. Fallback to active Lease (for tenants)
    if not unit:
        from properties.models import Lease
        active_lease = Lease.objects.filter(
            tenant=user, 
            status='active'
        ).select_related('unit__building__township', 'unit__floor_ref__block').first()
        if active_lease:
            unit = active_lease.unit

    # 3. Fallback to Ownership
    if not unit:
        unit = Unit.objects.filter(
            owner_user=user
        ).select_related('building__township', 'floor_ref__block').first()

    if not unit:
        # Debug info: what was tried?
        return {
            'error': True,
            'details': f"No unit found matching building '{building_name}' and unit '{unit_number}'.",
            'tried_fields': {'building': building_name, 'unit': unit_number}
        }

    # Found a unit! Ensure building_name/unit_number are correctly set for this logic
    building = unit.building
    unit_number = unit.unit_number
    
    block_name = _safe_str(getattr(unit.floor_ref.block, 'name', '')) if getattr(unit, 'floor_ref', None) and getattr(unit.floor_ref, 'block', None) else _safe_str(unit.block)
    floor_value = getattr(unit.floor_ref, 'floor_number', None) if getattr(unit, 'floor_ref', None) else None
    if floor_value is None:
        floor_value = unit.floor

    township = getattr(unit.building, 'township', None)
    return {
        'error': False,
        'unit': unit,
        'building': building,
        'township': township,
        'block_name': block_name,
        'wing_name': block_name,
        'floor': floor_value,
    }


def _ensure_group_conversation(marker, title, creator, participants):
    conversation = Conversation.objects.filter(conversation_type='group', description=marker).first()
    if not conversation:
        conversation = Conversation.objects.create(
            conversation_type='group',
            title=title,
            description=marker,
            created_by=creator,
        )

    existing_ids = set(conversation.participant_set.values_list('user_id', flat=True))
    new_participants = []
    
    if creator.id not in existing_ids:
        new_participants.append(ConversationParticipant(conversation=conversation, user=creator, role='admin'))
        existing_ids.add(creator.id)

    for participant in participants:
        if participant.id not in existing_ids:
            new_participants.append(ConversationParticipant(conversation=conversation, user=participant, role='member'))
            existing_ids.add(participant.id)

    if new_participants:
        ConversationParticipant.objects.bulk_create(new_participants)

    return conversation


def _get_building_assigned_managers(building_ids):
    if not building_ids:
        return User.objects.none()

    managed_manager_ids = list(
        Building.objects.filter(id__in=building_ids)
        .exclude(managed_by__isnull=True)
        .values_list('managed_by_id', flat=True)
    )
    building_names = list(
        Building.objects.filter(id__in=building_ids).values_list('name', flat=True)
    )

    return User.objects.filter(
        Q(id__in=managed_manager_ids) | Q(building_name__in=building_names),
        role__in=MANAGER_ROLES,
        is_active=True,
    ).distinct()


class ConversationViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing conversations (direct messages and group chats)
    """
    module = 'communication'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'last_message_at']
    filterset_fields = ['conversation_type', 'is_archived']
    
    def get_queryset(self):
        """Get conversations where user is a participant"""
        return Conversation.objects.filter(
            participants=self.request.user
        ).prefetch_related(
            'participant_set__user',
            'messages'
        ).distinct()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return ConversationCreateSerializer
        return ConversationSerializer

    @action(detail=False, methods=['get'], url_path='resident-channels')
    def resident_channels(self, request):
        user = request.user
        if getattr(user, 'role', None) not in RESIDENT_ROLES:
            return Response({'error': 'Only residents can access resident channels.'}, status=status.HTTP_403_FORBIDDEN)

        context = _get_user_unit_context(user)
        if not context or context.get('error'):
            # Return graceful response instead of 400 if mapping is missing
            return Response({
                'conversations': [],
                'group_ids': [],
                'direct_contacts': [],
                'warning': context.get('details', 'Unit mapping incomplete') if context else 'User unit context missing'
            }, status=status.HTTP_200_OK)

        township = context['township']
        building = context['building']
        block_name = context['block_name']
        wing_name = context['wing_name']
        floor_value = context['floor']

        building_ids_in_colony = list(
            Building.objects.filter(township=township).values_list('id', flat=True)
        ) if township else [building.id]
        building_names_in_colony = list(
            Building.objects.filter(id__in=building_ids_in_colony).values_list('name', flat=True)
        ) if building_ids_in_colony else [building.name]
        building_manager_participants = _get_building_assigned_managers(building_ids_in_colony)

        colony_participants = User.objects.filter(
            role__in=RESIDENT_ROLES,
            is_active=True,
            building_name__in=building_names_in_colony,
        ).distinct()
        colony_group_participants = (colony_participants | building_manager_participants).distinct()

        block_units = Unit.objects.filter(building=building)
        if block_name:
            block_units = block_units.filter(Q(block__iexact=block_name) | Q(floor_ref__block__name__iexact=block_name))

        if block_units.exists():
            unit_numbers = list(block_units.values_list('unit_number', flat=True))
            block_participants = User.objects.filter(role__in=RESIDENT_ROLES, is_active=True, building_name__iexact=building.name, unit_number__in=unit_numbers).distinct()
        else:
            block_participants = User.objects.filter(id=user.id)
            
        building_manager_scope = _get_building_assigned_managers([building.id])
        block_group_participants = (block_participants | building_manager_scope).distinct()

        floor_participants = block_participants
        if floor_value is not None:
            floor_units = block_units.filter(Q(floor=floor_value) | Q(floor_ref__floor_number=floor_value))
            if floor_units.exists():
                unit_numbers = list(floor_units.values_list('unit_number', flat=True))
                floor_participants = User.objects.filter(role__in=RESIDENT_ROLES, is_active=True, building_name__iexact=building.name, unit_number__in=unit_numbers).distinct()
            else:
                floor_participants = User.objects.filter(id=user.id)
        floor_group_participants = (floor_participants | building_manager_scope).distinct()

        group_conversations = []

        colony_marker = f'[AUTO_SCOPE] colony:{getattr(township, "id", "na")}'
        colony_title = f'{getattr(township, "name", building.name)} Colony Group'
        group_conversations.append(_ensure_group_conversation(colony_marker, colony_title, user, colony_group_participants))

        if block_name:
            block_marker = f'[AUTO_SCOPE] block:{building.id}:{block_name.lower()}'
            block_title = f'Block {block_name} Group - {building.name}'
            group_conversations.append(_ensure_group_conversation(block_marker, block_title, user, block_group_participants))

            wing_marker = f'[AUTO_SCOPE] wing:{building.id}:{wing_name.lower()}'
            wing_title = f'Wing {wing_name} Group - {building.name}'
            group_conversations.append(_ensure_group_conversation(wing_marker, wing_title, user, block_group_participants))

        if floor_value is not None:
            floor_marker = f'[AUTO_SCOPE] floor:{building.id}:{_safe_str(block_name).lower()}:{floor_value}'
            floor_title = f'Floor {floor_value} Group - {building.name}'
            group_conversations.append(_ensure_group_conversation(floor_marker, floor_title, user, floor_group_participants))

        direct_contacts = []
        for resident in colony_participants.exclude(id=user.id).order_by('first_name', 'last_name', 'username'):
            direct_contacts.append({
                'id': str(resident.id),
                'name': resident.get_full_name() or resident.username,
                'username': resident.username,
                'building_name': resident.building_name,
                'unit_number': resident.unit_number,
            })

        direct_conversations = self.get_queryset().filter(conversation_type='direct').order_by('-last_message_at')
        serializer = self.get_serializer(group_conversations + list(direct_conversations), many=True)

        return Response({
            'conversations': serializer.data,
            'group_ids': [str(conversation.id) for conversation in group_conversations],
            'direct_contacts': direct_contacts,
        })

    @action(detail=False, methods=['post'], url_path='start-direct')
    def start_direct(self, request):
        user = request.user
        if getattr(user, 'role', None) not in RESIDENT_ROLES:
            return Response({'error': 'Only residents can start direct chats here.'}, status=status.HTTP_403_FORBIDDEN)

        participant_id = request.data.get('participant_id')
        if not participant_id:
            return Response({'error': 'participant_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        other_user = User.objects.filter(id=participant_id, role__in=RESIDENT_ROLES, is_active=True).first()
        if not other_user:
            return Response({'error': 'Resident not found.'}, status=status.HTTP_404_NOT_FOUND)
        if other_user.id == user.id:
            return Response({'error': 'Cannot start a direct chat with yourself.'}, status=status.HTTP_400_BAD_REQUEST)

        my_context = _get_user_unit_context(user)
        other_context = _get_user_unit_context(other_user)
        if not my_context or not other_context:
            return Response({'error': 'Unit mapping missing for one of the residents.'}, status=status.HTTP_400_BAD_REQUEST)

        my_township_id = getattr(my_context.get('township'), 'id', None)
        other_township_id = getattr(other_context.get('township'), 'id', None)
        if not my_township_id or not other_township_id or my_township_id != other_township_id:
            return Response({'error': 'Direct chats are allowed only within the same colony.'}, status=status.HTTP_403_FORBIDDEN)

        conversation = (
            Conversation.objects.filter(conversation_type='direct', participants=user)
            .filter(participants=other_user)
            .annotate(participant_count=Count('participants', distinct=True))
            .filter(participant_count=2)
            .first()
        )

        if not conversation:
            conversation = Conversation.objects.create(
                conversation_type='direct',
                title=f'{user.get_full_name() or user.username} & {other_user.get_full_name() or other_user.username}',
                created_by=user,
            )
            ConversationParticipant.objects.create(conversation=conversation, user=user, role='admin')
            ConversationParticipant.objects.create(conversation=conversation, user=other_user, role='member')

        serializer = self.get_serializer(conversation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def my_conversations(self, request):
        """Get all conversations for current user"""
        conversations = self.get_queryset().order_by('-last_message_at')
        
        # Apply filters
        conversation_type = request.query_params.get('type')
        if conversation_type:
            conversations = conversations.filter(conversation_type=conversation_type)
        
        is_archived = request.query_params.get('archived')
        if is_archived is not None:
            conversations = conversations.filter(is_archived=is_archived.lower() == 'true')
        
        page = self.paginate_queryset(conversations)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(conversations, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive a conversation"""
        conversation = self.get_object()
        participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user
        ).first()
        
        if not participant:
            return Response(
                {'error': 'Not a participant of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        conversation.is_archived = True
        conversation.save()
        
        return Response({'status': 'conversation archived'})
    
    @action(detail=True, methods=['post'])
    def unarchive(self, request, pk=None):
        """Unarchive a conversation"""
        conversation = self.get_object()
        conversation.is_archived = False
        conversation.save()
        return Response({'status': 'conversation unarchived'})
    
    @action(detail=True, methods=['post'])
    def mute(self, request, pk=None):
        """Mute a conversation"""
        conversation = self.get_object()
        participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user
        ).first()
        
        if participant:
            participant.is_muted = True
            participant.save()
            return Response({'status': 'conversation muted'})
        
        return Response(
            {'error': 'Not a participant'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    @action(detail=True, methods=['post'])
    def unmute(self, request, pk=None):
        """Unmute a conversation"""
        conversation = self.get_object()
        participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user
        ).first()
        
        if participant:
            participant.is_muted = False
            participant.save()
            return Response({'status': 'conversation unmuted'})
        
        return Response(
            {'error': 'Not a participant'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    @action(detail=True, methods=['post'])
    def pin(self, request, pk=None):
        """Pin a conversation"""
        conversation = self.get_object()
        participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user
        ).first()
        
        if participant:
            participant.is_pinned = True
            participant.save()
            return Response({'status': 'conversation pinned'})
        
        return Response(
            {'error': 'Not a participant'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    @action(detail=True, methods=['post'])
    def unpin(self, request, pk=None):
        """Unpin a conversation"""
        conversation = self.get_object()
        participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user
        ).first()
        
        if participant:
            participant.is_pinned = False
            participant.save()
            return Response({'status': 'conversation unpinned'})
        
        return Response(
            {'error': 'Not a participant'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    @action(detail=True, methods=['post'])
    def add_participant(self, request, pk=None):
        """Add a participant to group conversation"""
        conversation = self.get_object()
        
        if conversation.conversation_type != 'group':
            return Response(
                {'error': 'Can only add participants to group conversations'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user_id = request.data.get('user_id')
        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if requester is admin
        requester_participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user,
            role='admin'
        ).first()
        
        if not requester_participant:
            return Response(
                {'error': 'Only admins can add participants'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Add participant
        participant, created = ConversationParticipant.objects.get_or_create(
            conversation=conversation,
            user_id=user_id
        )
        
        if created:
            return Response({'status': 'participant added'})
        else:
            return Response({'status': 'user already a participant'})
    
    @action(detail=True, methods=['post'])
    def remove_participant(self, request, pk=None):
        """Remove a participant from group conversation"""
        conversation = self.get_object()
        user_id = request.data.get('user_id')
        
        # Check if requester is admin
        requester_participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user,
            role='admin'
        ).first()
        
        if not requester_participant:
            return Response(
                {'error': 'Only admins can remove participants'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Remove participant
        ConversationParticipant.objects.filter(
            conversation=conversation,
            user_id=user_id
        ).delete()
        
        return Response({'status': 'participant removed'})


class MessageViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing messages within conversations
    """
    module = 'communication'
    serializer_class = MessageSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['content']
    ordering_fields = ['created_at']
    
    def get_queryset(self):
        """Get messages from conversations user is part of"""
        return Message.objects.filter(
            conversation__participants=self.request.user,
            is_deleted=False
        ).select_related('sender', 'reply_to').prefetch_related(
            'attachments', 'reactions', 'read_receipts'
        )
    
    def perform_create(self, serializer):
        """Create a new message and update unread counts"""
        if getattr(self.request.user, 'role', None) in RESIDENT_ROLES:
            user_messages = Message.objects.filter(
                sender=self.request.user,
                is_deleted=False,
            ).order_by('-created_at')

            sent_count = user_messages.count()
            if sent_count >= 3 and sent_count % 3 == 0:
                last_message = user_messages.first()
                cooldown_until = last_message.created_at + timedelta(minutes=2)
                now = timezone.now()
                if now < cooldown_until:
                    wait_seconds = int((cooldown_until - now).total_seconds())
                    wait_display = max(1, (wait_seconds + 59) // 60)
                    raise ValidationError(
                        {
                            'error': (
                                f'Cooldown active. Aapko agla message bhejne se pehle {wait_display} minute wait karna hoga.'
                            )
                        }
                    )

        message = serializer.save(sender=self.request.user)
        
        # Update unread counts for all participants except sender
        conversation = message.conversation
        ConversationParticipant.objects.filter(
            conversation=conversation
        ).exclude(
            user=self.request.user
        ).update(
            unread_count=F('unread_count') + 1
        )
        
        # Send notification to participants
        try:
            from notifications.tasks import send_message_notification
            send_message_notification.delay(message.id)
        except Exception:
            # Do not break message delivery if async notification queue is unavailable.
            pass
    
    @action(detail=False, methods=['get'])
    def conversation_messages(self, request):
        """Get all messages for a specific conversation"""
        conversation_id = request.query_params.get('conversation_id')
        if not conversation_id:
            return Response(
                {'error': 'conversation_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        messages = self.get_queryset().filter(
            conversation_id=conversation_id
        ).order_by('created_at')
        
        # Mark messages as read
        participant = ConversationParticipant.objects.filter(
            conversation_id=conversation_id,
            user=request.user
        ).first()
        
        if participant:
            participant.last_read_at = timezone.now()
            participant.unread_count = 0
            participant.save()
            
            # Create read receipts
            existing_receipts_msg_ids = set(MessageReadReceipt.objects.filter(
                message__in=messages, user=request.user
            ).values_list('message_id', flat=True))
            
            new_receipts = [
                MessageReadReceipt(message=message, user=request.user)
                for message in messages
                if message.id not in existing_receipts_msg_ids
            ]
            
            if new_receipts:
                MessageReadReceipt.objects.bulk_create(new_receipts)
        
        page = self.paginate_queryset(messages)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(messages, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['put'])
    def edit(self, request, pk=None):
        """Edit a message"""
        message = self.get_object()
        
        if message.sender != request.user:
            return Response(
                {'error': 'You can only edit your own messages'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        message.content = request.data.get('content', message.content)
        message.is_edited = True
        message.save()
        
        serializer = self.get_serializer(message)
        return Response(serializer.data)
    
    @action(detail=True, methods=['delete'])
    def soft_delete(self, request, pk=None):
        """Soft delete a message"""
        message = self.get_object()
        
        if message.sender != request.user:
            return Response(
                {'error': 'You can only delete your own messages'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        message.is_deleted = True
        message.deleted_at = timezone.now()
        message.save()
        
        return Response({'status': 'message deleted'})
    
    @action(detail=True, methods=['post'])
    def react(self, request, pk=None):
        """Add a reaction to a message"""
        message = self.get_object()
        emoji = request.data.get('emoji')
        
        if not emoji:
            return Response(
                {'error': 'emoji is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        reaction, created = MessageReaction.objects.get_or_create(
            message=message,
            user=request.user,
            emoji=emoji
        )
        
        serializer = MessageReactionSerializer(reaction)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def unreact(self, request, pk=None):
        """Remove a reaction from a message"""
        message = self.get_object()
        emoji = request.data.get('emoji')
        
        MessageReaction.objects.filter(
            message=message,
            user=request.user,
            emoji=emoji
        ).delete()
        
        return Response({'status': 'reaction removed'})


class AnnouncementViewSet(ModulePermissionMixin, viewsets.ModelViewSet):
    """
    ViewSet for managing announcements
    """
    module = 'communication'
    serializer_class = AnnouncementSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter, DjangoFilterBackend]
    search_fields = ['title', 'content', 'announcement_number']
    ordering_fields = ['created_at', 'priority']
    filterset_fields = ['announcement_type', 'priority', 'is_published']
    
    def get_queryset(self):
        """Get published announcements or all if user is staff/manager"""
        user = self.request.user
        if user.is_staff or user.role in ['master_admin', 'masteradmin', 'facility_manager']:
            return Announcement.objects.all()
        else:
            return Announcement.objects.filter(
                is_published=True,
                published_at__lte=timezone.now()
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
            )
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish an announcement"""
        announcement = self.get_object()
        
        if not request.user.is_staff:
            return Response(
                {'error': 'Only staff can publish announcements'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        announcement.is_published = True
        announcement.published_at = timezone.now()
        announcement.save()
        
        # Send notifications to targeted users
        from notifications.tasks import send_announcement_notification
        send_announcement_notification.delay(announcement.id)
        
        return Response({'status': 'announcement published'})
    
    @action(detail=True, methods=['post'])
    def mark_as_viewed(self, request, pk=None):
        """Mark announcement as viewed by current user"""
        announcement = self.get_object()
        
        view, created = AnnouncementView.objects.get_or_create(
            announcement=announcement,
            user=request.user
        )
        
        if created:
            announcement.view_count += 1
            announcement.save()
        
        return Response({'status': 'marked as viewed'})
    
    @action(detail=False, methods=['get'])
    def unread(self, request):
        """Get unread announcements for current user"""
        viewed_ids = AnnouncementView.objects.filter(
            user=request.user
        ).values_list('announcement_id', flat=True)
        
        announcements = self.get_queryset().exclude(
            id__in=viewed_ids
        ).order_by('-created_at')
        
        serializer = self.get_serializer(announcements, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def urgent(self, request):
        """Get urgent announcements"""
        announcements = self.get_queryset().filter(
            priority='urgent'
        ).order_by('-created_at')
        
        serializer = self.get_serializer(announcements, many=True)
        return Response(serializer.data)
