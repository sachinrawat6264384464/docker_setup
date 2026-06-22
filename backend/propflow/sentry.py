# propflow/sentry.py - Sentry error tracking configuration (free / self-hosted)
"""
Sentry integration for error tracking and performance monitoring.

Supports:
  1. Sentry.io free tier (10k errors/month, 10k transactions/month)
  2. Self-hosted Sentry (fully free, run via Docker)

Configuration via environment variables:
  SENTRY_DSN           — Your Sentry DSN URL
  SENTRY_ENVIRONMENT   — e.g., 'production', 'staging', 'development'
  SENTRY_TRACES_RATE   — Performance monitoring sample rate (0.0 to 1.0)
  SENTRY_PROFILES_RATE — Profiling sample rate (0.0 to 1.0)
  SENTRY_RELEASE       — Release version tag (optional)

Self-hosted setup:
  1. git clone https://github.com/getsentry/self-hosted.git
  2. cd self-hosted && ./install.sh
  3. docker compose up -d
  4. Set SENTRY_DSN to http://your-server:9000/...
"""

import os
import logging

logger = logging.getLogger(__name__)


def init_sentry():
    """
    Initialize Sentry SDK if SENTRY_DSN is configured.
    Call this from settings.py or wsgi.py.
    """
    dsn = os.getenv('SENTRY_DSN', '')
    if not dsn:
        logger.info('Sentry DSN not configured — error tracking disabled')
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning(
            'sentry-sdk not installed. Run: pip install sentry-sdk[django,celery]'
        )
        return

    environment = os.getenv('SENTRY_ENVIRONMENT', 'development')
    traces_rate = float(os.getenv('SENTRY_TRACES_RATE', '0.1'))
    profiles_rate = float(os.getenv('SENTRY_PROFILES_RATE', '0.1'))
    release = os.getenv('SENTRY_RELEASE', None)

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,

        # Integrations
        integrations=[
            DjangoIntegration(
                transaction_style='url',
                middleware_spans=True,
            ),
            CeleryIntegration(
                monitor_beat_tasks=True,
            ),
            RedisIntegration(),
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
        ],

        # Performance monitoring
        traces_sample_rate=traces_rate,
        profiles_sample_rate=profiles_rate,

        # Send PII (user info) to Sentry for better debugging
        send_default_pii=True,

        # Before-send hook to scrub sensitive data
        before_send=_before_send,

        # Ignore common non-errors
        ignore_errors=[
            KeyboardInterrupt,
            SystemExit,
        ],
    )

    logger.info(f'Sentry initialized: env={environment}, traces={traces_rate}')


def _before_send(event, hint):
    """
    Scrub sensitive information before sending to Sentry.
    This runs for every event/error.
    """
    # Remove password fields from request data
    if 'request' in event and 'data' in event['request']:
        data = event['request']['data']
        if isinstance(data, dict):
            sensitive_keys = ['password', 'new_password', 'old_password',
                              'token', 'refresh', 'access', 'otp_code',
                              'credit_card', 'card_number', 'cvv', 'ssn']
            for key in sensitive_keys:
                if key in data:
                    data[key] = '[REDACTED]'

    # Add tenant schema as tag
    try:
        from django.db import connection
        schema = getattr(connection, 'schema_name', 'unknown')
        if 'tags' not in event:
            event['tags'] = {}
        event['tags']['tenant_schema'] = schema
    except Exception:
        pass

    return event


def capture_exception(exc, **kwargs):
    """
    Capture an exception to Sentry if configured.
    Safe to call even if Sentry is not initialized.
    """
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc, **kwargs)
    except ImportError:
        logger.exception('Error (Sentry not available): %s', exc)


def capture_message(message, level='info', **kwargs):
    """
    Capture a message to Sentry if configured.
    Safe to call even if Sentry is not initialized.
    """
    try:
        import sentry_sdk
        sentry_sdk.capture_message(message, level=level, **kwargs)
    except ImportError:
        logger.log(
            getattr(logging, level.upper(), logging.INFO),
            'Message (Sentry not available): %s', message,
        )


def set_user_context(user):
    """Set the current user context in Sentry."""
    try:
        import sentry_sdk
        sentry_sdk.set_user({
            'id': str(user.id),
            'username': user.username,
            'email': user.email,
            'role': getattr(user, 'role', 'unknown'),
        })
    except ImportError:
        pass


def set_tenant_context(schema_name):
    """Set the current tenant context in Sentry."""
    try:
        import sentry_sdk
        sentry_sdk.set_tag('tenant_schema', schema_name)
    except ImportError:
        pass
