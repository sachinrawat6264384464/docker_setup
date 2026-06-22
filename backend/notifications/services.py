# notifications/services.py
import logging
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from notifications.utils import safe_create_notification

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Centralized notification helper service.

    Multiple modules (security, visitors, people_hub, payments, maintenance)
    can call these methods to create Notification records and optionally
    trigger email, SMS, or push delivery.

    All model imports are deferred to method level to prevent circular imports.
    Every public method is wrapped in try/except so a notification failure
    never breaks the calling workflow.
    """

    # ------------------------------------------------------------------ #
    #  Core helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_notification_model():
        """Import and return the Notification model at runtime."""
        from notifications.models import Notification
        return Notification

    @staticmethod
    def _get_preference_model():
        """Import and return the NotificationPreference model at runtime."""
        from notifications.models import NotificationPreference
        return NotificationPreference

    @staticmethod
    def _get_email_service():
        """Import and return the EmailService from accounts at runtime."""
        try:
            from accounts.email_service import EmailService
            return EmailService
        except ImportError:
            try:
                from accounts.services.email_service import EmailService
                return EmailService
            except ImportError:
                logger.warning(
                    "EmailService could not be imported from accounts. "
                    "Email delivery will be skipped."
                )
                return None

    @staticmethod
    def _check_user_preference(user, notification_type, channel):
        """
        Check whether *user* has opted-in for *channel* ('email', 'sms', or
        'push') for the given *notification_type*.

        Returns True (allow) when:
        - No preference record exists (default behaviour is to allow).
        - The relevant preference flag is True.
        """
        try:
            from notifications.models import NotificationPreference
            pref = NotificationPreference.objects.filter(user=user).first()
            if pref is None:
                return True

            # Channel-level global toggle
            channel_enabled = getattr(pref, f'{channel}_enabled', True)
            if not channel_enabled:
                return False

            # Type-specific toggle (e.g. email_payment, sms_security)
            type_flag = getattr(pref, f'{channel}_{notification_type}', None)
            if type_flag is not None:
                return type_flag

            return True
        except Exception:
            # If anything goes wrong, default to allowing the notification
            return True

    @classmethod
    def _deliver_email(cls, user, title, message):
        """
        Dispatch email delivery to a Celery background task so that SMTP
        latency does NOT block the HTTP request/response cycle.

        Falls back to synchronous delivery if Celery / Redis is unavailable.
        """
        user_id = getattr(user, 'pk', None) or getattr(user, 'id', None)
        if not user_id or not getattr(user, 'email', None):
            return False
        try:
            from notifications.tasks import send_notification_email_async
            send_notification_email_async.delay(
                user_id=str(user_id),
                title=title,
                message=message,
            )
            return True  # Task queued — email will arrive shortly in background
        except Exception as e:
            # Celery unavailable → fall back to synchronous send
            logger.warning(
                "Celery unavailable, falling back to synchronous email for user %s: %s",
                user_id, str(e)
            )
            try:
                EmailService = cls._get_email_service()
                if EmailService is None:
                    return False
                if hasattr(EmailService, 'send_notification_email'):
                    return EmailService.send_notification_email(
                        user=user, subject=title, title=title, message=message
                    )
                from django.core.mail import send_mail
                from django.template.loader import render_to_string
                from django.utils.html import strip_tags
                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@hoaconnecthub.com')
                context = {'user': user, 'title': title, 'message': message, 'subject': title, 'site_name': 'HOAConnectHub.com'}
                html_message = render_to_string('emails/notification_email.html', context)
                plain_message = strip_tags(html_message)
                sent = send_mail(subject=title, message=plain_message, from_email=from_email,
                                 recipient_list=[user.email], html_message=html_message, fail_silently=True)
                return sent > 0
            except Exception as fallback_exc:
                logger.error("Fallback sync email also failed for user %s: %s", user_id, str(fallback_exc))
                return False

    @staticmethod
    def _deliver_sms(user, message):
        """
        Placeholder for SMS delivery.
        Integrate with Twilio / Africa's Talking / etc. when ready.
        """
        try:
            phone = getattr(user, 'phone', None)
            if not phone:
                logger.info("SMS skipped for user %s: no phone number.", user.id)
                return False

            # TODO: Implement SMS gateway integration here
            logger.info(
                "SMS notification queued for %s (phone: %s).",
                user.id,
                phone,
            )
            return False  # Return False until a real gateway is wired up
        except Exception as e:
            logger.error("SMS delivery failed for user %s: %s", user.id, str(e))
            return False

    @staticmethod
    def _deliver_push(user, title, message, data=None):
        """
        Placeholder for push-notification delivery.
        Integrate with FCM / APNs / OneSignal when ready.
        """
        try:
            # TODO: Implement push notification gateway here
            logger.info(
                "Push notification queued for user %s: %s",
                user.id,
                title,
            )
            return False  # Return False until a real gateway is wired up
        except Exception as e:
            logger.error("Push delivery failed for user %s: %s", user.id, str(e))
            return False

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    @classmethod
    def send(
        cls,
        user,
        title,
        message,
        notification_type='system',
        priority='medium',
        send_email=False,
        send_sms=False,
        send_push=False,
        metadata=None,
        related_object_type='',
        related_object_id=None,
        action_url='',
    ):
        """
        Create a Notification record and optionally trigger email / SMS / push.

        Args:
            user:                  The recipient User instance.
            title:                 Short notification title (max 300 chars).
            message:               Full notification body.
            notification_type:     One of Notification.NOTIFICATION_TYPES values.
            priority:              'low', 'medium', 'high', or 'urgent'.
            send_email:            Whether to attempt email delivery.
            send_sms:              Whether to attempt SMS delivery.
            send_push:             Whether to attempt push delivery.
            metadata:              Optional dict stored in the Notification.data JSONField.
            related_object_type:   E.g. 'invoice', 'visitor_pass', 'maintenance_request'.
            related_object_id:     UUID of the related object.
            action_url:            Deep-link URL for the front-end.

        Returns:
            The created Notification instance, or None on failure.
        """
        try:
            notification = safe_create_notification(
                recipient=user,
                title=title,
                message=message,
                notification_type=notification_type,
                priority=priority,
                send_email=send_email,
                send_sms=send_sms,
                send_push=send_push,
                send_in_app=True,
                related_object_type=related_object_type,
                related_object_id=related_object_id,
                action_url=action_url,
                data=metadata or {},
                is_sent=True,
                sent_at=timezone.now(),
            )

            if notification is None:
                return None

            # ---- Deliver through requested channels ---- #

            if send_email and cls._check_user_preference(user, notification_type, 'email'):
                email_ok = cls._deliver_email(user, title, message)
                if email_ok:
                    notification.email_sent = True

            if send_sms and cls._check_user_preference(user, notification_type, 'sms'):
                sms_ok = cls._deliver_sms(user, message)
                if sms_ok:
                    notification.sms_sent = True

            if send_push and cls._check_user_preference(user, notification_type, 'push'):
                push_ok = cls._deliver_push(user, title, message, data=metadata)
                if push_ok:
                    notification.push_sent = True

            # Persist delivery flags
            notification.save(update_fields=['email_sent', 'sms_sent', 'push_sent'])

            logger.info(
                "Notification created [%s] for user %s: %s",
                notification_type,
                user.id,
                title,
            )
            return notification

        except Exception as e:
            logger.error(
                "Failed to create notification for user %s: %s",
                getattr(user, 'id', 'unknown'),
                str(e),
            )
            return None

    @classmethod
    def send_to_many(
        cls,
        users,
        title,
        message,
        notification_type='system',
        priority='medium',
        send_email=False,
        send_sms=False,
        send_push=False,
        metadata=None,
    ):
        """
        Send the same notification to multiple users.

        Args:
            users:  An iterable (QuerySet or list) of User instances.

        Returns:
            A list of created Notification instances (None entries for failures).
        """
        results = []
        for user in users:
            notification = cls.send(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                priority=priority,
                send_email=send_email,
                send_sms=send_sms,
                send_push=send_push,
                metadata=metadata,
            )
            results.append(notification)
        return results

    # ------------------------------------------------------------------ #
    #  Domain-specific convenience methods
    # ------------------------------------------------------------------ #

    @classmethod
    def send_invoice_notification(cls, invoice, notification_type='invoice_sent'):
        """
        Send an invoice-related notification to the invoice's user.

        Supported *notification_type* values:
            invoice_sent, invoice_paid, invoice_overdue,
            invoice_reminder, payment_received
        """
        try:
            user = invoice.user

            type_config = {
                'invoice_sent': {
                    'title': f'New Invoice #{invoice.invoice_number}',
                    'message': (
                        f'A new invoice #{invoice.invoice_number} for '
                        f'₹{invoice.total_amount} has been generated. '
                        f'Due date: {invoice.due_date.strftime("%b %d, %Y")}.'
                    ),
                    'priority': 'medium',
                },
                'invoice_paid': {
                    'title': f'Payment Confirmed - #{invoice.invoice_number}',
                    'message': (
                        f'Your payment of ₹{invoice.amount_paid} for invoice '
                        f'#{invoice.invoice_number} has been received. Thank you!'
                    ),
                    'priority': 'low',
                },
                'invoice_overdue': {
                    'title': f'Invoice Overdue - #{invoice.invoice_number}',
                    'message': (
                        f'Invoice #{invoice.invoice_number} for '
                        f'₹{invoice.amount_due} is overdue. '
                        f'Due date was {invoice.due_date.strftime("%b %d, %Y")}. '
                        f'Please make the payment at your earliest convenience.'
                    ),
                    'priority': 'high',
                },
                'invoice_reminder': {
                    'title': f'Payment Reminder - #{invoice.invoice_number}',
                    'message': (
                        f'Friendly reminder: Invoice #{invoice.invoice_number} for '
                        f'₹{invoice.amount_due} is due on '
                        f'{invoice.due_date.strftime("%b %d, %Y")}.'
                    ),
                    'priority': 'medium',
                },
                'payment_received': {
                    'title': f'Payment Received - #{invoice.invoice_number}',
                    'message': (
                        f'A payment of ₹{invoice.amount_paid} has been applied to '
                        f'invoice #{invoice.invoice_number}. '
                        f'Remaining balance: ₹{invoice.amount_due}.'
                    ),
                    'priority': 'low',
                },
            }

            config = type_config.get(notification_type, type_config['invoice_sent'])

            # Use specialized receipt email for payments
            if notification_type in ['invoice_paid', 'payment_received']:
                EmailService = cls._get_email_service()
                if EmailService and hasattr(EmailService, 'send_payment_receipt_email'):
                    EmailService.send_payment_receipt_email(
                        user=user,
                        amount=str(invoice.amount_paid),
                        transaction_id=getattr(invoice, 'last_transaction_id', 'N/A'),
                        date=timezone.now().strftime("%b %d, %Y"),
                        message=config['message']
                    )
            
            return cls.send(
                user=user,
                title=config['title'],
                message=config['message'],
                notification_type='payment',
                priority=config['priority'],
                send_email=notification_type not in ['invoice_paid', 'payment_received'], # Don't send double email
                send_push=True,
                metadata={
                    'invoice_id': str(invoice.id),
                    'invoice_number': invoice.invoice_number,
                    'amount': str(invoice.total_amount),
                    'amount_due': str(invoice.amount_due),
                    'due_date': str(invoice.due_date),
                    'event_type': notification_type,
                },
                related_object_type='invoice',
                related_object_id=invoice.id,
                action_url=f'/payments/invoices/{invoice.id}',
            )


        except Exception as e:
            logger.error(
                "Failed to send invoice notification for invoice %s: %s",
                getattr(invoice, 'invoice_number', 'unknown'),
                str(e),
            )
            return None

    @classmethod
    def send_visitor_notification(cls, visitor_pass, notification_type='visitor_approved'):
        """
        Send a visitor-related notification to the host.

        Supported *notification_type* values:
            visitor_approved, visitor_rejected, visitor_arrived,
            visitor_checked_in, visitor_checked_out, visitor_pass_created
        """
        try:
            host = visitor_pass.host
            visitor = visitor_pass.visitor
            visitor_name = visitor.get_full_name()

            type_config = {
                'visitor_pass_created': {
                    'title': f'New Visitor Pass - {visitor_name}',
                    'message': (
                        f'A visitor pass has been created for {visitor_name}. '
                        f'Expected arrival: '
                        f'{visitor_pass.expected_arrival.strftime("%b %d, %Y %I:%M %p")}. '
                        f'Purpose: {visitor_pass.purpose}.'
                    ),
                    'priority': 'medium',
                },
                'visitor_approved': {
                    'title': f'Visitor Pass Approved - {visitor_name}',
                    'message': (
                        f'The visitor pass for {visitor_name} '
                        f'(#{visitor_pass.pass_number}) has been approved. '
                        f'Access code: {visitor_pass.access_code}.'
                    ),
                    'priority': 'medium',
                },
                'visitor_rejected': {
                    'title': f'Visitor Pass Rejected - {visitor_name}',
                    'message': (
                        f'The visitor pass for {visitor_name} '
                        f'(#{visitor_pass.pass_number}) has been rejected. '
                        f'Reason: {visitor_pass.rejection_reason or "Not specified"}.'
                    ),
                    'priority': 'medium',
                },
                'visitor_arrived': {
                    'title': f'Visitor Arrived - {visitor_name}',
                    'message': (
                        f'{visitor_name} has arrived and is at the gate. '
                        f'Pass: #{visitor_pass.pass_number}.'
                    ),
                    'priority': 'high',
                },
                'visitor_checked_in': {
                    'title': f'Visitor Checked In - {visitor_name}',
                    'message': (
                        f'{visitor_name} has been checked in at '
                        f'{visitor_pass.actual_arrival.strftime("%I:%M %p") if visitor_pass.actual_arrival else "N/A"}. '
                        f'Pass: #{visitor_pass.pass_number}.'
                    ),
                    'priority': 'medium',
                },
                'visitor_checked_out': {
                    'title': f'Visitor Checked Out - {visitor_name}',
                    'message': (
                        f'{visitor_name} has checked out at '
                        f'{visitor_pass.actual_departure.strftime("%I:%M %p") if visitor_pass.actual_departure else "N/A"}. '
                        f'Pass: #{visitor_pass.pass_number}.'
                    ),
                    'priority': 'low',
                },
            }

            config = type_config.get(notification_type, type_config['visitor_approved'])

            return cls.send(
                user=host,
                title=config['title'],
                message=config['message'],
                notification_type='security',
                priority=config['priority'],
                send_email=True,
                send_push=True,
                metadata={
                    'visitor_pass_id': str(visitor_pass.id),
                    'pass_number': visitor_pass.pass_number,
                    'visitor_name': visitor_name,
                    'access_code': visitor_pass.access_code,
                    'event_type': notification_type,
                },
                related_object_type='visitor_pass',
                related_object_id=visitor_pass.id,
                action_url=f'/visitors/passes/{visitor_pass.id}',
            )

        except Exception as e:
            logger.error(
                "Failed to send visitor notification for pass %s: %s",
                getattr(visitor_pass, 'pass_number', 'unknown'),
                str(e),
            )
            return None

    @classmethod
    def send_security_alert(cls, alert, guards=None):
        """
        Send a security / emergency alert notification to guards and,
        optionally, to the person who triggered the alert.

        Args:
            alert:   An EmergencyAlert or SecurityIncident instance.
            guards:  An iterable of SecurityGuard instances.  When None the
                     method will attempt to notify all active guards.
        """
        try:
            # Build title / message from the alert instance
            alert_title = getattr(alert, 'title', 'Security Alert')
            alert_description = getattr(alert, 'description', '')
            location = getattr(alert, 'location', '')
            building = getattr(alert, 'building', '')
            priority_value = getattr(alert, 'priority', getattr(alert, 'severity', 'high'))

            # Map severity / priority strings to Notification.PRIORITY_LEVELS
            priority_map = {
                'critical': 'urgent',
                'high': 'high',
                'medium': 'medium',
                'low': 'low',
            }
            mapped_priority = priority_map.get(priority_value, 'high')

            title = f'Security Alert: {alert_title}'
            location_str = f'{building} - {location}'.strip(' -') if building or location else 'Property'
            message = (
                f'{alert_title}\n\n'
                f'Location: {location_str}\n'
                f'Priority: {priority_value.upper()}\n\n'
                f'{alert_description}'
            )

            # Determine alert metadata
            alert_type_value = getattr(alert, 'alert_type', getattr(alert, 'incident_type', 'unknown'))
            related_type = 'emergency_alert'
            if hasattr(alert, 'incident_number'):
                related_type = 'security_incident'

            metadata = {
                'alert_id': str(alert.id),
                'alert_type': alert_type_value,
                'location': location_str,
                'priority': priority_value,
            }

            # Resolve the list of guards
            if guards is None:
                try:
                    from security.models import SecurityGuard
                    guards = SecurityGuard.objects.filter(status='active').select_related('user')
                except Exception:
                    guards = []

            notifications = []
            for guard in guards:
                guard_user = guard.user if hasattr(guard, 'user') else guard
                n = cls.send(
                    user=guard_user,
                    title=title,
                    message=message,
                    notification_type='alert',
                    priority=mapped_priority,
                    send_email=True,
                    send_sms=True,
                    send_push=True,
                    metadata=metadata,
                    related_object_type=related_type,
                    related_object_id=alert.id,
                    action_url=f'/security/alerts/{alert.id}',
                )
                notifications.append(n)

            # Also notify the person who triggered / reported the alert
            triggered_by = getattr(alert, 'triggered_by', getattr(alert, 'reported_by', None))
            if triggered_by:
                n = cls.send(
                    user=triggered_by,
                    title=f'Your alert has been broadcast: {alert_title}',
                    message=(
                        f'Your security alert "{alert_title}" has been '
                        f'sent to {len(notifications)} security personnel.'
                    ),
                    notification_type='alert',
                    priority='medium',
                    send_push=True,
                    metadata=metadata,
                    related_object_type=related_type,
                    related_object_id=alert.id,
                    action_url=f'/security/alerts/{alert.id}',
                )
                notifications.append(n)

            logger.info(
                "Security alert notifications sent to %d recipients for alert %s.",
                len([n for n in notifications if n is not None]),
                alert.id,
            )
            return notifications

        except Exception as e:
            logger.error(
                "Failed to send security alert notification: %s", str(e)
            )
            return []

    @classmethod
    def send_maintenance_notification(cls, request, notification_type='request_created'):
        """
        Send a maintenance-related notification.

        The recipient depends on the event:
        - request_created / request_updated  -> admin / facility manager
        - request_assigned                   -> the assigned technician
        - request_completed                  -> the original requester
        - status_changed                     -> the original requester

        Supported *notification_type* values:
            request_created, request_acknowledged, request_assigned,
            request_in_progress, request_completed, request_cancelled,
            status_changed
        """
        try:
            requester = request.requested_by
            assigned = getattr(request, 'assigned_to', None)

            type_config = {
                'request_created': {
                    'title': f'New Maintenance Request #{request.request_number}',
                    'message': (
                        f'A new maintenance request has been submitted.\n'
                        f'Title: {request.title}\n'
                        f'Category: {request.get_category_display()}\n'
                        f'Priority: {request.get_priority_display()}\n'
                        f'Location: {request.building}, Unit {request.unit_number}\n'
                        f'Submitted by: {requester.get_full_name()}'
                    ),
                    'priority': request.priority,
                    'recipient': 'admin',
                },
                'request_acknowledged': {
                    'title': f'Request Acknowledged - #{request.request_number}',
                    'message': (
                        f'Your maintenance request #{request.request_number} '
                        f'("{request.title}") has been acknowledged and is '
                        f'being reviewed.'
                    ),
                    'priority': 'low',
                    'recipient': 'requester',
                },
                'request_assigned': {
                    'title': f'Maintenance Task Assigned - #{request.request_number}',
                    'message': (
                        f'You have been assigned maintenance request '
                        f'#{request.request_number}.\n'
                        f'Title: {request.title}\n'
                        f'Category: {request.get_category_display()}\n'
                        f'Priority: {request.get_priority_display()}\n'
                        f'Location: {request.building}, Unit {request.unit_number}'
                    ),
                    'priority': request.priority,
                    'recipient': 'assigned',
                },
                'request_in_progress': {
                    'title': f'Work Started - #{request.request_number}',
                    'message': (
                        f'Work has started on your maintenance request '
                        f'#{request.request_number} ("{request.title}").'
                    ),
                    'priority': 'low',
                    'recipient': 'requester',
                },
                'request_completed': {
                    'title': f'Request Completed - #{request.request_number}',
                    'message': (
                        f'Your maintenance request #{request.request_number} '
                        f'("{request.title}") has been completed. '
                        f'Please review and provide your feedback.'
                    ),
                    'priority': 'medium',
                    'recipient': 'requester',
                },
                'request_cancelled': {
                    'title': f'Request Cancelled - #{request.request_number}',
                    'message': (
                        f'Maintenance request #{request.request_number} '
                        f'("{request.title}") has been cancelled.'
                    ),
                    'priority': 'low',
                    'recipient': 'requester',
                },
                'status_changed': {
                    'title': f'Request Updated - #{request.request_number}',
                    'message': (
                        f'The status of your maintenance request '
                        f'#{request.request_number} ("{request.title}") '
                        f'has been updated to: {request.get_status_display()}.'
                    ),
                    'priority': 'low',
                    'recipient': 'requester',
                },
            }

            config = type_config.get(notification_type, type_config['request_created'])

            # Determine recipient(s)
            recipient_key = config.get('recipient', 'requester')
            recipients = []

            if recipient_key == 'requester':
                recipients = [requester]
            elif recipient_key == 'assigned':
                if assigned:
                    recipients = [assigned]
                else:
                    logger.warning(
                        "Maintenance notification '%s' targets assigned user, "
                        "but no one is assigned to %s.",
                        notification_type,
                        request.request_number,
                    )
                    return None
            elif recipient_key == 'admin':
                # Notify admins / facility managers; also send to the requester
                # as a confirmation.
                try:
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    admins = list(
                        User.objects.filter(
                            role__in=['admin', 'super_admin', 'facility_manager'],
                            is_active=True,
                        )
                    )
                    recipients = admins
                except Exception:
                    recipients = []

                # Also confirm to the requester
                cls.send(
                    user=requester,
                    title=f'Request Received - #{request.request_number}',
                    message=(
                        f'Your maintenance request #{request.request_number} '
                        f'("{request.title}") has been submitted successfully. '
                        f'We will get back to you shortly.'
                    ),
                    notification_type='maintenance',
                    priority='low',
                    send_email=True,
                    send_push=True,
                    metadata={
                        'request_id': str(request.id),
                        'request_number': request.request_number,
                        'event_type': 'request_confirmation',
                    },
                    related_object_type='maintenance_request',
                    related_object_id=request.id,
                    action_url=f'/maintenance/requests/{request.id}',
                )

            notifications = []
            for user in recipients:
                n = cls.send(
                    user=user,
                    title=config['title'],
                    message=config['message'],
                    notification_type='maintenance',
                    priority=config['priority'],
                    send_email=True,
                    send_push=True,
                    metadata={
                        'request_id': str(request.id),
                        'request_number': request.request_number,
                        'category': request.category,
                        'priority': request.priority,
                        'status': request.status,
                        'event_type': notification_type,
                    },
                    related_object_type='maintenance_request',
                    related_object_id=request.id,
                    action_url=f'/maintenance/requests/{request.id}',
                )
                notifications.append(n)

            if len(notifications) == 1:
                return notifications[0]
            return notifications
        except Exception as e:
            logger.error("Failed to send maintenance notification: %s", str(e))
            return None

    @classmethod
    def send_amenity_notification(cls, booking, notification_type='booking_confirmed'):
        """
        Send an amenity booking-related notification.
        Types: booking_requested, booking_approved, booking_rejected, 
               booking_confirmed, booking_cancelled, reminder
        """
        try:
            user = booking.booked_by
            amenity = booking.amenity

            type_config = {
                'booking_requested': {
                    'title': f'Booking Request Received - {amenity.name}',
                    'message': f'Your booking request for {amenity.name} on {booking.booking_date} is pending approval.',
                    'priority': 'low',
                },
                'booking_approved': {
                    'title': f'Booking Approved! - {amenity.name}',
                    'message': f'Great news! Your booking for {amenity.name} on {booking.booking_date} at {booking.start_time} has been approved.',
                    'priority': 'medium',
                },
                'booking_rejected': {
                    'title': f'Booking Rejected - {amenity.name}',
                    'message': f'Sorry, your booking request for {amenity.name} was rejected. Reason: {booking.rejection_reason or "N/A"}',
                    'priority': 'medium',
                },
                'booking_confirmed': {
                    'title': f'Booking Confirmed - {amenity.name}',
                    'message': f'Your booking for {amenity.name} is confirmed for {booking.booking_date} from {booking.start_time} to {booking.end_time}.',
                    'priority': 'high',
                },
                'booking_cancelled': {
                    'title': f'Booking Cancelled - {amenity.name}',
                    'message': f'Your booking for {amenity.name} on {booking.booking_date} has been cancelled.',
                    'priority': 'low',
                },
                'reminder': {
                    'title': f'Amenity Reminder - {amenity.name}',
                    'message': f'Friendly reminder: You have a booking for {amenity.name} today at {booking.start_time}. Enjoy!',
                    'priority': 'medium',
                },
            }

            config = type_config.get(notification_type, type_config['booking_confirmed'])

            return cls.send(
                user=user,
                title=config['title'],
                message=config['message'],
                notification_type='amenity',
                priority=config['priority'],
                send_email=True,
                send_push=True,
                metadata={'booking_id': str(booking.id), 'event_type': notification_type},
                related_object_type='amenity_booking',
                related_object_id=booking.id,
                action_url=f'/amenities/bookings/{booking.id}',
            )
        except Exception as e:
            logger.error(f"Failed to send amenity notification: {str(e)}")
            return None

    @classmethod
    def send_parking_notification(cls, slot_or_pass, notification_type='slot_assigned'):
        """
        Send a parking-related notification.
        Types: slot_assigned, pass_issued, violation_alert, pass_expiry_warning
        """
        try:
            # Handle both Slot and Pass objects
            user = getattr(slot_or_pass, 'assigned_to', getattr(slot_or_pass, 'user', None))
            if not user: return None

            type_config = {
                'slot_assigned': {
                    'title': 'New Parking Slot Assigned',
                    'message': f'Parking Slot {getattr(slot_or_pass, "slot_number", "N/A")} has been assigned to you.',
                    'priority': 'medium',
                },
                'pass_issued': {
                    'title': 'Parking Pass Issued',
                    'message': f'Your parking pass {getattr(slot_or_pass, "pass_number", "N/A")} is now active. Please use the QR code in the app for entry.',
                    'priority': 'high',
                },
                'violation_alert': {
                    'title': '🚨 Parking Violation Alert',
                    'message': 'A parking violation has been reported for your vehicle. Please ensure you are parked in your assigned slot.',
                    'priority': 'urgent',
                },
                'pass_expiry_warning': {
                    'title': 'Parking Pass Expiring Soon',
                    'message': f'Your parking pass is set to expire on {getattr(slot_or_pass, "valid_until", "N/A")}. Please renew it to avoid entry issues.',
                    'priority': 'high',
                },
            }

            config = type_config.get(notification_type, type_config['slot_assigned'])

            return cls.send(
                user=user,
                title=config['title'],
                message=config['message'],
                notification_type='parking',
                priority=config['priority'],
                send_email=True,
                send_push=True,
                metadata={'event_type': notification_type},
                action_url='/parking/my-slots',
            )
        except Exception as e:
            logger.error(f"Failed to send parking notification: {str(e)}")
            return None

    @classmethod
    def send_lease_notification(cls, lease, notification_type='agreement_created'):
        """
        Send a rental/lease-related notification.
        Types: agreement_created, expiry_reminder, document_verified, status_update
        """
        try:
            user = lease.tenant
            unit = lease.unit

            type_config = {
                'agreement_created': {
                    'title': 'New Rental Agreement Created',
                    'message': f'A new rental agreement for Unit {unit.unit_number} has been created. Please review and sign.',
                    'priority': 'high',
                },
                'expiry_reminder': {
                    'title': 'Lease Expiry Notice',
                    'message': f'Your lease for Unit {unit.unit_number} will expire on {lease.end_date}. Please contact management for renewal.',
                    'priority': 'urgent',
                },
                'document_verified': {
                    'title': 'Lease Document Verified',
                    'message': f'Your signed lease agreement for Unit {unit.unit_number} has been verified successfully.',
                    'priority': 'low',
                },
                'status_update': {
                    'title': 'Lease Status Updated',
                    'message': f'The status of your lease for Unit {unit.unit_number} has been updated to {lease.get_status_display()}.',
                    'priority': 'medium',
                },
            }

            config = type_config.get(notification_type, type_config['agreement_created'])

            return cls.send(
                user=user,
                title=config['title'],
                message=config['message'],
                notification_type='rental',
                priority=config['priority'],
                send_email=True,
                send_push=True,
                metadata={'lease_id': str(lease.id), 'event_type': notification_type},
                related_object_type='lease',
                related_object_id=lease.id,
                action_url=f'/rentals/lease/{lease.id}',
            )
        except Exception as e:
            logger.error(f"Failed to send lease notification: {str(e)}")
            return None

    # ------------------------------------------------------------------ #
    #  Additional utility methods
    # ------------------------------------------------------------------ #

    @classmethod
    def send_announcement(cls, announcement):
        """
        Broadcast a notifications.Announcement to its target audience.

        Returns a list of Notification instances.
        """
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()

            users = User.objects.filter(is_active=True)

            if announcement.audience_type == 'building' and announcement.target_buildings:
                users = users.filter(building_name__in=announcement.target_buildings)
            elif announcement.audience_type == 'unit_type' and announcement.target_units:
                users = users.filter(unit_number__in=announcement.target_units)
            # 'all' and 'custom' keep the full queryset

            results = cls.send_to_many(
                users=users,
                title=announcement.title,
                message=announcement.content,
                notification_type='announcement',
                priority='medium',
                send_email=announcement.send_email,
                send_sms=announcement.send_sms,
                send_push=announcement.send_push,
                metadata={
                    'announcement_id': str(announcement.id),
                },
            )

            # Update announcement stats
            announcement.sent_count = len([r for r in results if r is not None])
            announcement.save(update_fields=['sent_count'])

            return results

        except Exception as e:
            logger.error("Failed to broadcast announcement %s: %s", announcement.id, str(e))
            return []

    @classmethod
    def send_payment_reminder(cls, invoice, reminder_type='before_due'):
        """
        Convenience wrapper around send_invoice_notification for payment
        reminders.
        """
        type_map = {
            'before_due': 'invoice_reminder',
            'on_due': 'invoice_reminder',
            'after_due': 'invoice_overdue',
        }
        return cls.send_invoice_notification(
            invoice=invoice,
            notification_type=type_map.get(reminder_type, 'invoice_reminder'),
        )

    @classmethod
    def send_welcome_notification(cls, user, notification_type='resident_onboarding'):
        """
        Send a welcome notification to a new user.
        Types: resident_onboarding, master_admin_activated, fm_appointed, login_credentials
        """
        try:
            type_config = {
                'resident_onboarding': {
                    'title': 'Welcome to HOA Connect!',
                    'message': f'Welcome {user.get_full_name() or user.username}! We are excited to have you as part of our community.',
                    'priority': 'medium',
                },
                'master_admin_activated': {
                    'title': 'Organization Account Activated',
                    'message': 'Your Master Admin account has been activated. You can now start setting up your community.',
                    'priority': 'high',
                },
                'fm_appointed': {
                    'title': 'Facility Manager Appointment',
                    'message': 'You have been appointed as a Facility Manager. Please log in to view your dashboard.',
                    'priority': 'high',
                },
                'login_credentials': {
                    'title': 'Your Login Credentials',
                    'message': f'Your account has been created. Your username is {user.username}. Please use the app to set your password.',
                    'priority': 'high',
                },
            }

            config = type_config.get(notification_type, type_config['resident_onboarding'])

            # Use the specialized welcome email service if available
            # EmailService = cls._get_email_service()
            # if EmailService and hasattr(EmailService, 'send_welcome_email'):
            #     EmailService.send_welcome_email(user)
            
            return cls.send(
                user=user,
                title=config['title'],
                message=config['message'],
                notification_type='system',
                priority=config['priority'],
                send_email=False, # Already sent via send_welcome_email
                send_push=True,
                metadata={'event_type': notification_type},
                action_url='/login',
            )
        except Exception as e:
            logger.error(f"Failed to send welcome notification: {str(e)}")
            return None
