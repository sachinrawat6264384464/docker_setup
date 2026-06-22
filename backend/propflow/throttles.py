from rest_framework.throttling import UserRateThrottle


class AuthRateThrottle(UserRateThrottle):
    scope = 'auth'


class PaymentRateThrottle(UserRateThrottle):
    scope = 'payments'


class UploadRateThrottle(UserRateThrottle):
    scope = 'uploads'


class WebhookRateThrottle(UserRateThrottle):
    scope = 'webhooks'


class ReportRateThrottle(UserRateThrottle):
    scope = 'reports'
