import time
import logging

logger = logging.getLogger('propflow.api')


class RequestLoggingMiddleware:
    """Logs API request/response times and detects slow requests."""

    SLOW_REQUEST_THRESHOLD = 2.0  # seconds

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)

        start_time = time.time()
        response = self.get_response(request)
        duration = time.time() - start_time

        # Log slow requests as warnings
        if duration > self.SLOW_REQUEST_THRESHOLD:
            logger.warning(
                'SLOW REQUEST: %s %s took %.2fs (status=%s, user=%s)',
                request.method, request.path, duration,
                response.status_code,
                getattr(request, 'user', 'anonymous'),
            )
        else:
            logger.info(
                '%s %s %.3fs status=%s',
                request.method, request.path, duration,
                response.status_code,
            )

        return response


class QueryCountMiddleware:
    """Detects views with excessive database queries (N+1 problem)."""

    QUERY_WARNING_THRESHOLD = 15

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)

        from django.conf import settings
        if not settings.DEBUG:
            return self.get_response(request)

        from django.db import connection
        initial_queries = len(connection.queries)
        response = self.get_response(request)
        total_queries = len(connection.queries) - initial_queries

        if total_queries > self.QUERY_WARNING_THRESHOLD:
            logger.warning(
                'EXCESSIVE QUERIES: %s %s made %d queries',
                request.method, request.path, total_queries,
            )

        return response


class HeaderStrippingMiddleware:
    """VAPT-2026-047 & VAPT-2026-048: Removes sensitive Server and X-Powered-By headers from response."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.has_header('Server'):
            del response['Server']
        if response.has_header('X-Powered-By'):
            del response['X-Powered-By']
        return response
