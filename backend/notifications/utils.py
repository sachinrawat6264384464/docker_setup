import logging
from django.apps import apps
from django.db import connection, transaction
from django.db.utils import DatabaseError, OperationalError, ProgrammingError

logger = logging.getLogger(__name__)


def _notifications_table_available():
    """Return True when notifications app and table exist in current schema."""
    if not apps.is_installed('notifications'):
        return False

    try:
        table_names = connection.introspection.table_names()
        return 'notifications_notification' in table_names
    except Exception:
        return False


def safe_create_notification(**kwargs):
    """Create a notification safely; never raise to caller."""
    if not _notifications_table_available():
        return None

    if 'user' in kwargs and 'recipient' not in kwargs:
        kwargs['recipient'] = kwargs.pop('user')

    try:
        from notifications.models import Notification

        # Isolate DB errors so an outer transaction does not remain broken.
        with transaction.atomic():
            return Notification.objects.create(**kwargs)
    except (ProgrammingError, OperationalError, DatabaseError) as exc:
        logger.warning('Notification create skipped due to DB state: %s', exc)
    except Exception as exc:
        logger.warning('Notification create failed: %s', exc)

    return None


def safe_bulk_create_notifications(notifications, **kwargs):
    """Bulk create notifications safely; returns created list or empty list."""
    notifications = list(notifications or [])
    if not notifications or not _notifications_table_available():
        return []

    try:
        from notifications.models import Notification

        with transaction.atomic():
            return Notification.objects.bulk_create(notifications, **kwargs)
    except (ProgrammingError, OperationalError, DatabaseError) as exc:
        logger.warning('Notification bulk create skipped due to DB state: %s', exc)
    except Exception as exc:
        logger.warning('Notification bulk create failed: %s', exc)

    return []
