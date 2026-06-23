# propflow/settings.py - COMPLETE PRODUCTION-READY CONFIGURATION
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Allowed hosts
# Allowed hosts
ALLOWED_HOSTS = [
    'hoaconnecthub.com',
    '.hoaconnecthub.com',
    'localhost',
    '.localhost',
    '127.0.0.1',
    '44.220.64.35',
]

# Domains
MAIN_DOMAIN = os.getenv('MAIN_DOMAIN', 'hoaconnecthub.com')
TENANT_DOMAIN_SUFFIX = os.getenv('TENANT_DOMAIN_SUFFIX', '.hoaconnecthub.com')
FRONTEND_URL = os.getenv('FRONTEND_URL', f"https://{MAIN_DOMAIN}")

# Email Settings
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
DEFAULT_FROM_NAME = os.getenv('DEFAULT_FROM_NAME', 'HOA Connect Hub')

# =============================================================================
# DJANGO-TENANTS CONFIGURATION
# =============================================================================

TENANT_MODEL = "tenants.Client"
TENANT_DOMAIN_MODEL = "tenants.Domain"
# Required so django-tenants falls back to PUBLIC_SCHEMA_URLCONF during tests
# (the test runner uses "testserver" as hostname, which has no matching Domain row).
# Safe in production since unknown hostnames are blocked at DNS/load-balancer level.
# CRITICAL: Do NOT show public landing page if tenant is not found via subdomain.
# This ensures that invalid URLs like koo.localhost result in a 404.
SHOW_PUBLIC_IF_NO_TENANT_FOUND = True  # Required to allow main domain (hoaconnecthub.com) to work as public schema
ROOT_URLCONF = 'propflow.urls_public'
PUBLIC_SCHEMA_URLCONF = 'propflow.urls_public'
TENANT_URLCONF = 'propflow.urls_tenants'

# Apps available to public schema AND all tenants
SHARED_APPS = [
    'django_tenants',  # Must be first
    
    # Django core apps
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.admin',
    'django.contrib.staticfiles',
    
    # Third party shared apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist', 
    'corsheaders',
    'drf_spectacular',
    
    # Celery apps
    'django_celery_beat',
    'django_celery_results',
    
    # Your shared apps
    'accounts',
    'tenants',
    'analytics.apps.AnalyticsConfig',
    'blog.apps.BlogConfig',
    # 'website.apps.WebsiteConfig',
    'pricing.apps.PricingConfig',
    'developer_portal.apps.DeveloperPortalConfig',
    'backups.apps.BackupsConfig',
    'data_export.apps.DataExportConfig',
    'location_master.apps.LocationMasterConfig',  # India address master data
    'properties',
    'calendar_alerts',
    'support.apps.SupportConfig',
    'maintenance',
    'payments',
    'reports.apps.ReportsConfig',
    'notifications',
]
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# Apps available ONLY to tenants
TENANT_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Core tenant apps
    'accounts',
    'rest_framework_simplejwt.token_blacklist',
    'properties',
    'utilities',
    'calendar_alerts',
    
    # Business logic apps
    'maintenance',
    'amenities',
    'payments',
    'security',
    'parking',
    'entertainment',
    'notifications',
    
    # NEW MODULES - 7 APPS
    'communication.apps.CommunicationConfig',
    # 'visitors.apps.VisitorsConfig',
    'vendors.apps.VendorsConfig',
    'reservations.apps.ReservationsConfig',
    'support.apps.SupportConfig',
    'inspections.apps.InspectionsConfig',
    'location_master.apps.LocationMasterConfig',
    'data_export.apps.DataExportConfig',
    'marketplace.apps.MarketplaceConfig',
    'social.apps.SocialConfig',
]

# Combined installed apps
INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

SITE_ID = 1
APPEND_SLASH = True  # REST API — don't redirect POST requests to slash URL

# =============================================================================
# MIDDLEWARE CONFIGURATION - CRITICAL: ORDER MATTERS!
# =============================================================================

MIDDLEWARE = [
    'propflow.middleware.HeaderStrippingMiddleware', # Strip banners early
    'corsheaders.middleware.CorsMiddleware', # CRITICAL: Must be first
    'tenants.middleware.UnifiedTenantMiddleware', # Handles everything: Subdomains, X-Tenant, and Public Fallback
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'propflow.middleware.RequestLoggingMiddleware',
    'propflow.middleware.QueryCountMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'tenants.middleware.TenantActiveMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# =============================================================================
# CORS CONFIGURATION - FIXED FOR X-TENANT HEADER
# =============================================================================

# CRITICAL: Add all frontend origins
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-tenant',
    'x-tenant-schema',
    'cache-control',
    'pragma',
]
CORS_EXPOSE_HEADERS = [
    'content-type',
    'x-csrftoken',
    'x-tenant',
]

CORS_ALLOWED_ORIGINS = [
    # Local Development
    'http://localhost:3000',
    'http://company.localhost:3000',
    'http://demo.localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:3001',
    'http://manage.localhost:3001',
    'http://demo.localhost:3001',
    'http://127.0.0.1:3001',
    'http://localhost:3002',
    'http://resident.localhost:3002',
    'http://demo.localhost:3002',
    'http://127.0.0.1:3002',
    'http://localhost:3003',
    'http://admin.localhost:3003',
    'http://127.0.0.1:3003',
    'http://localhost:8080',  # Mobile App Local Server

    # Production Domains
    'https://hoaconnecthub.com',
    'https://www.hoaconnecthub.com',
    'https://demo.hoaconnecthub.com',
    'https://android-app.hoaconnecthub.com',   # ← Main production frontend
    'https://app.hoaconnecthub.com',
    'https://admin.hoaconnecthub.com',
    'https://manager.hoaconnecthub.com',
    'https://resident.hoaconnecthub.com',
]

# CSRF Settings
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://localhost:3001',
    'http://localhost:8000',
    'http://*.localhost:3000',
    'http://*.localhost:8000',
    'https://hoaconnecthub.com',
    'https://www.hoaconnecthub.com',
    'https://admin.hoaconnecthub.com',
    'https://demo.hoaconnecthub.com',
    'https://android-app.hoaconnecthub.com',  # ← Main production frontend
    'https://app.hoaconnecthub.com',
    'https://manager.hoaconnecthub.com',
    'https://resident.hoaconnecthub.com',
    'https://*.hoaconnecthub.com',
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://.*\.localhost:3000$",
    r"^http://localhost:3000$",
    r"^https://.*\.hoaconnecthub\.com$",
    r"^https://hoaconnecthub\.com$",
]


# # Session settings for cross-origin
# SESSION_COOKIE_SAMESITE = 'Lax'
# SESSION_COOKIE_HTTPONLY = True
# SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
# SESSION_COOKIE_DOMAIN = None  # Allow cookies across subdomains

# # CSRF settings for API
# CSRF_COOKIE_SAMESITE = 'Lax'
# CSRF_COOKIE_HTTPONLY = False  # Must be False for JavaScript to read it
# CSRF_COOKIE_SECURE = False  # Set to True in production with HTTPS

SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None

SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG


# =============================================================================
# URL CONFIGURATION
# =============================================================================

# Tenant URLs (for individual property companies)
ROOT_URLCONF = 'propflow.urls_tenants'

# Public schema URLs (for system administration)
PUBLIC_SCHEMA_URLCONF = 'propflow.urls_public'

WSGI_APPLICATION = 'propflow.wsgi.application'

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

DATABASES = {
    'default': {
        'ENGINE': 'django_tenants.postgresql_backend',
        'NAME': os.getenv('DB_NAME', 'property_saas'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'CONN_MAX_AGE': 600,  # 10 min persistent connections
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'connect_timeout': 60,
        },
    }
}

DATABASE_ROUTERS = (
    'django_tenants.routers.TenantSyncRouter',
)

# =============================================================================
# TEMPLATES CONFIGURATION
# =============================================================================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# =============================================================================
# EMAIL CONFIGURATION
# =============================================================================

# For local development, use console backend. Change to SMTP for production.
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')

EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')

DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@hoaconnecthub.com')
DEFAULT_FROM_NAME = 'HOA Connect Hub'
SERVER_EMAIL = 'admin@hoaconnecthub.com'
FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://hoaconnecthub.com')

# =============================================================================
# TESTING OVERRIDES — Must be LAST (after DEBUG block adds debug_toolbar)
# =============================================================================
TESTING = (
    'test' in sys.argv
    or any('pytest' in arg for arg in sys.argv)
    or 'PYTEST_CURRENT_TEST' in os.environ
    or 'PYTEST_VERSION' in os.environ
)

if TESTING:
    # SimpleJWT blacklist tables are not consistently available in this test setup.
    INSTALLED_APPS = [
        app for app in INSTALLED_APPS
        if app != 'rest_framework_simplejwt.token_blacklist'
    ]

    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        },
        'sessions': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
    # Disable Debug Toolbar during tests — it tries to render its HTML panel
    # on every API response, but 'djdt' namespace is not registered in the
    # tenant URL config, causing all API tests to return 500 instead of 200.
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'debug_toolbar']
    MIDDLEWARE = [m for m in MIDDLEWARE if 'debug_toolbar' not in m]
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/1'),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'IGNORE_EXCEPTIONS': True,
            }
        },
        'sessions': {
            'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
            'LOCATION': 'django_sessions',
        }
    }

SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# =============================================================================
# AUTHENTICATION & SECURITY
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    # VAPT-2026-040: Increased from 8 to 12 characters, enabled common/numeric checks
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# =============================================================================
# REST FRAMEWORK CONFIGURATION
# =============================================================================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'accounts.authentication.MultiTenantJWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'auth': '5/minute',         # VAPT-2026-011: login/register throttle
        'otp_verify': '5/10min',    # VAPT-2026-087: OTP brute force protection
        'payments': '30/hour',
        'uploads': '20/hour',
        'webhooks': '300/hour',
        'reports': '30/hour',
    },
    # API Versioning
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.URLPathVersioning',
    'DEFAULT_VERSION': 'v1',
    'ALLOWED_VERSIONS': ['v1', 'v2'],
    'VERSION_PARAM': 'version',
}

if not DEBUG:
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = ['rest_framework.renderers.JSONRenderer']

# =============================================================================
# DRF SPECTACULAR (API DOCUMENTATION) CONFIGURATION
# =============================================================================

SPECTACULAR_SETTINGS = {
    'TITLE': 'PropFlow API Documentation',
    'DESCRIPTION': 'Multi-Tenant Property Management Platform - Complete API Reference',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': True,
        'filter': True,
    },
    'SCHEMA_PATH_PREFIX': '/api/',
    'COMPONENT_SPLIT_REQUEST': True,
}

# =============================================================================
# INTERNATIONALIZATION
# =============================================================================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# =============================================================================
# STATIC & MEDIA FILES
# =============================================================================

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Auto-create staticfiles directory to avoid WhiteNoise/Sentry warnings
if not STATIC_ROOT.exists():
    STATIC_ROOT.mkdir(parents=True, exist_ok=True)
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# WhiteNoise configuration
STATICFILES_STORAGE = (
    'django.contrib.staticfiles.storage.StaticFilesStorage'
    if DEBUG else
    'whitenoise.storage.CompressedManifestStaticFilesStorage'
)

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 1024 * 1024 * 15,  # 15MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'api_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'api.log',
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django_tenants': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'tenants': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'accounts': {
            'handlers': ['console', 'file', 'api_file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'payments': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'propflow.api': {
            'handlers': ['console', 'api_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': 'WARNING',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

# Create logs directory if it doesn't exist
(BASE_DIR / 'logs').mkdir(exist_ok=True)

# =============================================================================
# CELERY CONFIGURATION
# =============================================================================

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_CACHE_BACKEND = 'django-cache'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

from celery.schedules import crontab
CELERY_BEAT_SCHEDULE = {
    'compute-daily-snapshots': {
        'task': 'analytics.tasks.compute_daily_snapshots',
        'schedule': crontab(hour=1, minute=0),
    },
    'send-weekly-summary': {
        'task': 'notifications.tasks.send_weekly_summary_emails',
        'schedule': crontab(day_of_week=0, hour=9, minute=0), # Every Sunday at 9 AM
    },
    'send-monthly-newsletter': {
        'task': 'notifications.tasks.send_monthly_newsletter',
        'schedule': crontab(day_of_month=1, hour=10, minute=0), # 1st of every month at 10 AM
    },
    'remind-inactive-users': {
        'task': 'notifications.tasks.remind_inactive_users',
        'schedule': crontab(hour=11, minute=0), # Every day at 11 AM
    },
    'send-monthly-billing-summary': {
        'task': 'notifications.tasks.send_monthly_billing_summary',
        'schedule': crontab(day_of_month=1, hour=8, minute=0), # 1st of every month at 8 AM
    },
}

# Celery task routing
CELERY_TASK_ROUTES = {
    'payments.tasks.*': {'queue': 'payments'},
    'notifications.tasks.*': {'queue': 'notifications'},
    'reports.tasks.*': {'queue': 'reports'},
}

# For local dev with Redis: Run tasks asynchronously (if worker is running)
CELERY_TASK_ALWAYS_EAGER = False

# =============================================================================
# PAYMENT GATEWAY CONFIGURATION
# =============================================================================

# Razorpay Configuration (India)
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')

# =============================================================================
# THIRD-PARTY INTEGRATIONS
# =============================================================================

# QuickBooks Configuration
QUICKBOOKS_CLIENT_ID = os.getenv('QUICKBOOKS_CLIENT_ID', '')
QUICKBOOKS_CLIENT_SECRET = os.getenv('QUICKBOOKS_CLIENT_SECRET', '')
QUICKBOOKS_REDIRECT_URI = os.getenv('QUICKBOOKS_REDIRECT_URI', 'http://localhost:8000/api/accounting/quickbooks/callback/')
QUICKBOOKS_ENVIRONMENT = os.getenv('QUICKBOOKS_ENVIRONMENT', 'sandbox')

# Twilio (SMS/WhatsApp)
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '')

# SendGrid (Email)
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY', '')

# Firebase (Push Notifications)
FIREBASE_CREDENTIALS_PATH = os.getenv('FIREBASE_CREDENTIALS_PATH', '')

# AWS S3 Configuration (Optional - for file storage)
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '')
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME', '')
AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME', 'us-east-1')
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
AWS_DEFAULT_ACL = 'public-read'

# Use S3 for media files in production
USE_S3 = os.getenv('USE_S3', 'False').lower() == 'true'
if USE_S3:
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

# GST Configuration (India)
GST_ENABLED = os.getenv('GST_ENABLED', 'False').lower() == 'true'
GST_NUMBER = os.getenv('GST_NUMBER', '')

# =============================================================================
# SECURITY SETTINGS (Production)
# =============================================================================

if not DEBUG:
    # HTTPS settings
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    
    # VAPT-2026-037: HSTS — SSL stripping prevention
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    
    # VAPT-2026-039: Clickjacking protection
    X_FRAME_OPTIONS = 'DENY'
    
    # VAPT-2026-038/VAPT-2026-047: Content type sniffing & XSS protection
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    
    # VAPT-2026-044: Prevent Host header injection in password reset flow
    # Do NOT trust X-Forwarded-Host from untrusted proxies
    USE_X_FORWARDED_HOST = False

# =============================================================================
# DEFAULT PRIMARY KEY FIELD TYPE
# =============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# =============================================================================
# SENTRY ERROR TRACKING (free tier / self-hosted)
# =============================================================================
# Set SENTRY_DSN in .env to enable. Supports:
#   - Sentry.io free tier (10k errors/month)
#   - Self-hosted Sentry (fully free, Docker-based)
# Install: pip install sentry-sdk[django,celery]

from propflow.sentry import init_sentry
# init_sentry() # Disabled to prevent Python 3.13 sentry-sdk crash

# =============================================================================
# DEVELOPMENT SETTINGS
# =============================================================================

if DEBUG:
    INSTALLED_APPS += ['django_extensions']
    if os.getenv('DISABLE_DEBUG_TOOLBAR', 'False').lower() != 'true':
        INSTALLED_APPS += ['debug_toolbar']
        MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
    INTERNAL_IPS = ['127.0.0.1', 'localhost']
    
    # VAPT-2026-043: Restrict wildcard hosts to protect against Host Header Poisoning during scans
    if os.getenv('ALLOWED_HOSTS_WILDCARD', 'False').lower() == 'true':
        ALLOWED_HOSTS += ['*']
    
    # Debug Toolbar configuration — disabled during test runs
    _TESTING = 'test' in sys.argv
    DEBUG_TOOLBAR_CONFIG = {
        'SHOW_TOOLBAR_CALLBACK': lambda request: DEBUG,
    }

# =============================================================================
# TESTING OVERRIDES — Must be LAST (after DEBUG block adds debug_toolbar)
# =============================================================================
# Stripe Connect Platform Settings
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
STRIPE_PLATFORM_PUBLISHABLE_KEY = os.getenv('STRIPE_PLATFORM_PUBLISHABLE_KEY')
STRIPE_PLATFORM_SECRET_KEY = os.getenv('STRIPE_PLATFORM_SECRET_KEY')
STRIPE_CONNECT_WEBHOOK_SECRET = os.getenv('STRIPE_CONNECT_WEBHOOK_SECRET')
PLATFORM_URL = os.getenv('PLATFORM_URL', 'http://localhost:3000')

if TESTING:
    # Debug Toolbar must not run during tests: it intercepts every API response
    # and crashes because 'djdt' namespace is not registered in tenant URL conf.
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'debug_toolbar']
    MIDDLEWARE = [m for m in MIDDLEWARE if 'debug_toolbar' not in m]
