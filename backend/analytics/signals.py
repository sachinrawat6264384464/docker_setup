import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from analytics.models import AnalyticsEvent

logger = logging.getLogger(__name__)


def _detect_device_type(user_agent: str) -> str:
    """Detect device type from User-Agent string."""
    if not user_agent:
        return 'web'
    ua_lower = user_agent.lower()
    if 'android' in ua_lower:
        return 'android'
    if 'iphone' in ua_lower or 'ipad' in ua_lower or 'ios' in ua_lower:
        return 'ios'
    if 'okhttp' in ua_lower or 'python-requests' in ua_lower or 'curl' in ua_lower:
        return 'api'
    return 'web'


def _get_client_ip(request) -> str:
    """Extract the real client IP address from request headers."""
    if request is None:
        return None
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _get_tenant_schema(request) -> str:
    """Extract tenant schema name from request."""
    if request is None:
        return ''
    tenant = getattr(request, 'tenant', None)
    if tenant is not None:
        return getattr(tenant, 'schema_name', '')
    return ''


def track_event(
    event_type: str,
    user=None,
    tenant_schema: str = '',
    object_type: str = '',
    object_id: str = '',
    metadata: dict = None,
    request=None,
) -> AnalyticsEvent | None:
    """
    Create an AnalyticsEvent record.

    Parameters
    ----------
    event_type:     One of the EVENT_TYPES choices (e.g. 'user_logged_in').
    user:           The Django user instance, or None for anonymous events.
    tenant_schema:  Schema name of the tenant. Auto-detected from request if omitted.
    object_type:    Model name/type the event relates to (optional).
    object_id:      PK / identifier of the related object (optional).
    metadata:       Arbitrary JSON-serialisable dict for extra context.
    request:        Django HttpRequest; used to extract IP, UA, session, tenant.
    """
    if metadata is None:
        metadata = {}

    # Auto-detect tenant schema from request if not supplied
    if not tenant_schema and request is not None:
        tenant_schema = _get_tenant_schema(request)

    ip_address = _get_client_ip(request)
    user_agent = ''
    session_id = ''
    device_type = 'web'

    if request is not None:
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        session_id = request.session.session_key or '' if hasattr(request, 'session') else ''
        device_type = _detect_device_type(user_agent)

    try:
        event = AnalyticsEvent.objects.create(
            event_type=event_type,
            user=user,
            tenant_schema=tenant_schema,
            object_type=object_type,
            object_id=str(object_id),
            metadata=metadata,
            ip_address=ip_address,
            device_type=device_type,
            user_agent=user_agent,
            session_id=session_id,
        )
        return event
    except Exception as exc:
        logger.warning('analytics.track_event failed for %s: %s', event_type, exc)
        return None


# ---------------------------------------------------------------------------
# Django auth signal receivers
# ---------------------------------------------------------------------------

@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    track_event(
        event_type='user_logged_in',
        user=user,
        request=request,
        metadata={'username': user.get_username()},
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    track_event(
        event_type='user_logged_out',
        user=user,
        request=request,
        metadata={'username': user.get_username() if user else 'anonymous'},
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    track_event(
        event_type='user_login_failed',
        user=None,
        request=request,
        metadata={'username_attempted': credentials.get('username', '')},
    )
