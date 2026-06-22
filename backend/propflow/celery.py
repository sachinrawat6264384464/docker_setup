# propflow/celery.py
import os
from celery import Celery
from celery.schedules import crontab

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'propflow.settings')

# Create Celery app
app = Celery('propflow')

# Load config from Django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all installed apps
app.autodiscover_tasks()


# ═══════════════════════════════════════════════════════════════════════════
# CELERY BEAT SCHEDULE - AUTO-PAY & RECURRING TASKS
# ═══════════════════════════════════════════════════════════════════════════

app.conf.beat_schedule = {
    # ────────────────────────────────────────────────────────────────────────
    # AUTO-PAY TASKS
    # ────────────────────────────────────────────────────────────────────────
    
    'process-autopay-payments-daily': {
        'task': 'payments.tasks.run_autopay_for_all_tenants',
        'schedule': crontab(hour=2, minute=0),  # Run daily at 2:00 AM
        'options': {
            'expires': 3600,  # Task expires after 1 hour if not executed
        }
    },
    
    'generate-recurring-invoices-daily': {
        'task': 'payments.tasks.generate_recurring_invoices',
        'schedule': crontab(hour=1, minute=0),  # Run daily at 1:00 AM
        'options': {
            'expires': 3600,
        }
    },
    
    'send-autopay-reminders-daily': {
        'task': 'payments.tasks.send_autopay_reminder_notifications',
        'schedule': crontab(hour=9, minute=0),  # Run daily at 9:00 AM
        'options': {
            'expires': 3600,
        }
    },
    
    # ────────────────────────────────────────────────────────────────────────
    # PAYMENT REMINDERS & NOTIFICATIONS
    # ────────────────────────────────────────────────────────────────────────
    
    'check-overdue-invoices': {
        'task': 'payments.tasks.check_overdue_invoices',
        'schedule': crontab(hour=10, minute=0),  # Run daily at 10:00 AM
        'options': {
            'expires': 3600,
        }
    },
    
    'send-payment-reminders': {
        'task': 'payments.tasks.send_payment_reminders',
        'schedule': crontab(hour=8, minute=0),  # Run daily at 8:00 AM
        'options': {
            'expires': 3600,
        }
    },
    
    # ────────────────────────────────────────────────────────────────────────
    # MAINTENANCE & CLEANUP TASKS
    # ────────────────────────────────────────────────────────────────────────
    
    'cleanup-failed-payments': {
        'task': 'payments.tasks.cleanup_failed_payments',
        'schedule': crontab(hour=3, minute=0, day_of_week=1),  # Weekly on Monday at 3 AM
        'options': {
            'expires': 7200,
        }
    },
    
    'cleanup-draft-payments': {
        'task': 'payments.tasks.cleanup_draft_payments',
        'schedule': crontab(hour=2, minute=30),  # Run daily at 2:30 AM
        'options': {
            'expires': 3600,
        }
    },
    
    'update-subscription-statuses': {
        'task': 'payments.tasks.update_subscription_statuses',
        'schedule': crontab(hour=4, minute=0),  # Run daily at 4:00 AM
        'options': {
            'expires': 3600,
        }
    },
    
    # ────────────────────────────────────────────────────────────────────────
    # REPORTING TASKS
    # ────────────────────────────────────────────────────────────────────────
    
    'generate-daily-payment-report': {
        'task': 'payments.tasks.generate_daily_payment_report',
        'schedule': crontab(hour=23, minute=30),  # Run daily at 11:30 PM
        'options': {
            'expires': 3600,
        }
    },
    
    'generate-monthly-revenue-report': {
        'task': 'payments.tasks.generate_monthly_revenue_report',
        'schedule': crontab(hour=0, minute=30, day_of_month=1),  # First day of month at 12:30 AM
        'options': {
            'expires': 7200,
        }
    },
    
    # ────────────────────────────────────────────────────────────────────────
    # OPTIONAL: SECURITY TASKS (if you want to add)
    # ────────────────────────────────────────────────────────────────────────
    
    # 'check-expired-visitor-passes': {
    #     'task': 'security.tasks.check_expired_visitor_passes',
    #     'schedule': crontab(hour='*/6', minute=0),  # Every 6 hours
    # },
    
    # 'generate-security-report': {
    #     'task': 'security.tasks.generate_daily_security_report',
    #     'schedule': crontab(hour=23, minute=0),  # Daily at 11:00 PM
    # },
    
    # ────────────────────────────────────────────────────────────────────────
    # OPTIONAL: MAINTENANCE MODULE TASKS
    # ────────────────────────────────────────────────────────────────────────
    
    # 'check-pending-maintenance': {
    #     'task': 'maintenance.tasks.check_pending_maintenance_requests',
    #     'schedule': crontab(hour='*/4', minute=0),  # Every 4 hours
    # },
    
    # ────────────────────────────────────────────────────────────────────────
    # UTILITY BILLING TASKS
    # ────────────────────────────────────────────────────────────────────────
    
    'generate-utility-bills-monthly': {
        'task': 'utilities.tasks.run_utility_billing_for_all_tenants',
        'schedule': crontab(hour=0, minute=0, day_of_month=1),  # Run monthly on the 1st at 12:00 AM
        'options': {
            'expires': 7200,
        }
    },
    
    # ────────────────────────────────────────────────────────────────────────
    # LEASE & PROPERTY TASKS
    # ────────────────────────────────────────────────────────────────────────
    
    'check-lease-expiries-daily': {
        'task': 'properties.tasks.run_lease_checks_for_all_tenants',
        'schedule': crontab(hour=5, minute=0),  # Run daily at 5:00 AM
        'options': {
            'expires': 3600,
        }
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# CELERY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

app.conf.timezone = 'UTC'  # Or your timezone, e.g., 'America/New_York', 'Asia/Kolkata'

# Task execution settings
app.conf.task_soft_time_limit = 300  # 5 minutes
app.conf.task_time_limit = 600  # 10 minutes (hard limit)
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1

# Task result settings
app.conf.result_expires = 3600  # Results expire after 1 hour
app.conf.result_backend = 'redis://localhost:6379/0'  # Or your Redis URL

# Task routing (optional - for advanced setups)
app.conf.task_routes = {
    'payments.tasks.*': {'queue': 'payments'},
    'notifications.tasks.*': {'queue': 'notifications'},
    # Add more routes as needed
}

# Worker settings
app.conf.worker_max_tasks_per_child = 1000  # Restart worker after 1000 tasks


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to test Celery is working"""
    print(f'Request: {self.request!r}')