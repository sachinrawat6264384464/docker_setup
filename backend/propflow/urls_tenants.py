# ============================================================================
# FILE 2: propflow/urls_tenants.py
# ============================================================================
# This handles: abc.localhost:8000, xyz.localhost:8000

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from propflow.health import health_check_detailed, health_check_simple, admin_health_check
from tenants.views import current_tenant
from accounts.views import LoginView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView
)
from rest_framework.permissions import IsAdminUser

# Custom admin site for tenant level
class TenantAdminSite(admin.AdminSite):
    site_header = "🏠 Property Management Dashboard"
    site_title = "Property Admin Panel"
    index_title = "Manage Your Properties & Residents"

    def each_context(self, request):
        context = super().each_context(request)
        tenant_name = getattr(request, 'tenant', None)
        context.update({
            'is_tenant_admin': True,
            'admin_level': 'TENANT',
            'admin_color': '#059669',
            'tenant_name': tenant_name.name if tenant_name else 'Unknown Property Company',
        })
        return context

# Create custom admin site instance
tenant_admin_site = TenantAdminSite(name='tenant_admin')

# =============================================================================
# MODEL IMPORTS
# =============================================================================

# Accounts
from accounts.models import User, UserProfile, ActivityLog
from accounts.csv_models import CSVUpload, CSVRowResult, CSVTemplate

# Properties & Utilities
from properties.models import Building, Unit, Lease, PropertyDocument
from utilities.models import UtilityType, UtilityBill, UtilityMeterReading, UtilityProvider, BuildingUtilityConnection
from calendar_alerts.models import CalendarAlert, AlertRecipient

# Maintenance
from maintenance.models import MaintenanceRequest, MaintenanceSchedule
from maintenance.models import Vendor as MaintenanceVendor

# Amenities
from amenities.models import Amenity, AmenityBooking, AmenityReview, AmenityMaintenance, AmenityUsageLog, AmenityRule

# Payments
from payments.models import (
    PaymentGateway, Invoice, Payment, PaymentMethod, Refund,
    PaymentPlan, Installment, Transaction,
    AutoPayEnrollment, AutoPaymentLog, RecurringInvoice,
)

# Notifications
from notifications.models import Notification, NotificationPreference, Announcement as NotificationAnnouncement

# Security
from security.models import (
    SecurityGuard, SecurityIncident, VisitorLog as SecurityVisitorLog,
    AccessControl, AccessLog, PatrolLog, EmergencyAlert, CCTVCamera,
    SecurityAnnouncement,
)

# Parking
from parking.models import ParkingSlot, Vehicle, ParkingPass, ParkingEntry

# Entertainment
from entertainment.models import Event, EventRegistration, Club

# Communication
from communication.models import (
    Conversation, ConversationParticipant, Message, MessageAttachment,
    MessageReaction, MessageReadReceipt,
    Announcement as CommAnnouncement, AnnouncementAttachment, AnnouncementView,
)

# Visitors
# from visitors.models import VisitorType, Visitor, VisitorPass, VisitorLog, BlacklistedVisitor, VisitorFeedback

# Vendors
from vendors.models import VendorCategory, Vendor, VendorService, VendorContract, VendorReview, VendorPayment, VendorInsurance

# Support
from support.models import TicketCategory, Ticket, TicketComment, FAQArticle

# Reports
from reports.models import ReportTemplate, GeneratedReport, ScheduledReport

# Reservations
from reservations.models import ReservableResource, Reservation

# Inspections
from inspections.models import InspectionTemplate, Inspection, InspectionPhoto

# =============================================================================
# ADMIN REGISTRATIONS (TENANT LEVEL)
# =============================================================================
from accounts.admin import UserAdmin, UserProfileAdmin, ActivityLogAdmin
from accounts.admin import CSVUploadAdmin, CSVRowResultAdmin, CSVTemplateAdmin
from properties.admin import BuildingAdmin, UnitAdmin, LeaseAdmin, PropertyDocumentAdmin
from utilities.admin import (
    UtilityTypeAdmin, UtilityBillAdmin, UtilityMeterReadingAdmin, 
    UtilityProviderAdmin, BuildingUtilityConnectionAdmin
)
from maintenance.admin import MaintenanceRequestAdmin, MaintenanceScheduleAdmin
from amenities.admin import (
    AmenityAdmin, AmenityBookingAdmin, AmenityReviewAdmin, 
    AmenityMaintenanceAdmin, AmenityUsageLogAdmin, AmenityRuleAdmin
)
from payments.admin import (
    PaymentGatewayAdmin, InvoiceAdmin, PaymentAdmin, PaymentMethodAdmin, RefundAdmin,
    PaymentPlanAdmin, InstallmentAdmin, TransactionAdmin,
    AutoPayEnrollmentAdmin, AutoPaymentLogAdmin, RecurringInvoiceAdmin
)
from notifications.admin import NotificationAdmin, NotificationPreferenceAdmin
from security.admin import (
    SecurityGuardAdmin, SecurityIncidentAdmin,
    AccessControlAdmin, AccessLogAdmin, PatrolLogAdmin, EmergencyAlertAdmin,
    CCTVCameraAdmin, SecurityAnnouncementAdmin
)
from parking.admin import ParkingSlotAdmin, VehicleAdmin, ParkingPassAdmin, ParkingEntryAdmin
from entertainment.admin import EventAdmin, EventRegistrationAdmin, ClubAdmin
from communication.admin import (
    ConversationAdmin, ConversationParticipantAdmin, MessageAdmin, MessageAttachmentAdmin,
    MessageReactionAdmin, MessageReadReceiptAdmin,
    AnnouncementAttachmentAdmin, AnnouncementViewAdmin
)
# from visitors.admin import (
#     VisitorTypeAdmin, VisitorAdmin, VisitorPassAdmin, VisitorLogAdmin,
#     BlacklistedVisitorAdmin, VisitorFeedbackAdmin
# )
from vendors.admin import (
    VendorCategoryAdmin, VendorAdmin, VendorServiceAdmin, VendorContractAdmin,
    VendorReviewAdmin, VendorPaymentAdmin, VendorInsuranceAdmin
)
from support.admin import TicketCategoryAdmin, TicketAdmin, TicketCommentAdmin, FAQArticleAdmin
from reports.admin import ReportTemplateAdmin, GeneratedReportAdmin, ScheduledReportAdmin
from reservations.admin import ReservableResourceAdmin, ReservationAdmin
from inspections.admin import InspectionTemplateAdmin, InspectionAdmin, InspectionPhotoAdmin

# --- Accounts ---
tenant_admin_site.register(User, UserAdmin)
tenant_admin_site.register(UserProfile, UserProfileAdmin)
tenant_admin_site.register(ActivityLog, ActivityLogAdmin)
tenant_admin_site.register(CSVUpload, CSVUploadAdmin)
tenant_admin_site.register(CSVRowResult, CSVRowResultAdmin)
tenant_admin_site.register(CSVTemplate, CSVTemplateAdmin)

# --- Properties & Utilities ---
tenant_admin_site.register(Building, BuildingAdmin)
tenant_admin_site.register(Unit, UnitAdmin)
tenant_admin_site.register(Lease, LeaseAdmin)
tenant_admin_site.register(PropertyDocument, PropertyDocumentAdmin)
tenant_admin_site.register(UtilityType, UtilityTypeAdmin)
tenant_admin_site.register(UtilityBill, UtilityBillAdmin)
tenant_admin_site.register(UtilityMeterReading, UtilityMeterReadingAdmin)
tenant_admin_site.register(UtilityProvider, UtilityProviderAdmin)
tenant_admin_site.register(BuildingUtilityConnection, BuildingUtilityConnectionAdmin)

# --- Maintenance ---
tenant_admin_site.register(MaintenanceRequest, MaintenanceRequestAdmin)
tenant_admin_site.register(MaintenanceSchedule, MaintenanceScheduleAdmin)

# --- Amenities ---
tenant_admin_site.register(Amenity, AmenityAdmin)
tenant_admin_site.register(AmenityBooking, AmenityBookingAdmin)
tenant_admin_site.register(AmenityReview, AmenityReviewAdmin)
tenant_admin_site.register(AmenityMaintenance, AmenityMaintenanceAdmin)
tenant_admin_site.register(AmenityUsageLog, AmenityUsageLogAdmin)
tenant_admin_site.register(AmenityRule, AmenityRuleAdmin)

# --- Payments ---
tenant_admin_site.register(PaymentGateway, PaymentGatewayAdmin)
tenant_admin_site.register(Invoice, InvoiceAdmin)
tenant_admin_site.register(Payment, PaymentAdmin)
tenant_admin_site.register(PaymentMethod, PaymentMethodAdmin)
tenant_admin_site.register(Refund, RefundAdmin)
tenant_admin_site.register(PaymentPlan, PaymentPlanAdmin)
tenant_admin_site.register(Installment, InstallmentAdmin)
tenant_admin_site.register(Transaction, TransactionAdmin)
tenant_admin_site.register(AutoPayEnrollment, AutoPayEnrollmentAdmin)
tenant_admin_site.register(AutoPaymentLog, AutoPaymentLogAdmin)
tenant_admin_site.register(RecurringInvoice, RecurringInvoiceAdmin)

# --- Notifications ---
tenant_admin_site.register(Notification, NotificationAdmin)
tenant_admin_site.register(NotificationPreference, NotificationPreferenceAdmin)

# --- Security ---
tenant_admin_site.register(SecurityGuard, SecurityGuardAdmin)
tenant_admin_site.register(SecurityIncident, SecurityIncidentAdmin)
tenant_admin_site.register(AccessControl, AccessControlAdmin)
tenant_admin_site.register(AccessLog, AccessLogAdmin)
tenant_admin_site.register(PatrolLog, PatrolLogAdmin)
tenant_admin_site.register(EmergencyAlert, EmergencyAlertAdmin)
tenant_admin_site.register(CCTVCamera, CCTVCameraAdmin)
tenant_admin_site.register(SecurityAnnouncement, SecurityAnnouncementAdmin)

# --- Parking ---
tenant_admin_site.register(ParkingSlot, ParkingSlotAdmin)
tenant_admin_site.register(Vehicle, VehicleAdmin)
tenant_admin_site.register(ParkingPass, ParkingPassAdmin)
tenant_admin_site.register(ParkingEntry, ParkingEntryAdmin)

# --- Entertainment ---
tenant_admin_site.register(Event, EventAdmin)
tenant_admin_site.register(EventRegistration, EventRegistrationAdmin)
tenant_admin_site.register(Club, ClubAdmin)

# --- Communication ---
tenant_admin_site.register(Conversation, ConversationAdmin)
tenant_admin_site.register(ConversationParticipant, ConversationParticipantAdmin)
tenant_admin_site.register(Message, MessageAdmin)
tenant_admin_site.register(MessageAttachment, MessageAttachmentAdmin)
tenant_admin_site.register(MessageReaction, MessageReactionAdmin)
tenant_admin_site.register(MessageReadReceipt, MessageReadReceiptAdmin)
tenant_admin_site.register(AnnouncementAttachment, AnnouncementAttachmentAdmin)
tenant_admin_site.register(AnnouncementView, AnnouncementViewAdmin)

# --- Visitors ---
# tenant_admin_site.register(VisitorType, VisitorTypeAdmin)
# tenant_admin_site.register(Visitor, VisitorAdmin)
# tenant_admin_site.register(VisitorPass, VisitorPassAdmin)
# tenant_admin_site.register(VisitorLog, VisitorLogAdmin)
# tenant_admin_site.register(BlacklistedVisitor, BlacklistedVisitorAdmin)
# tenant_admin_site.register(VisitorFeedback, VisitorFeedbackAdmin)

# --- Vendors ---
tenant_admin_site.register(VendorCategory, VendorCategoryAdmin)
tenant_admin_site.register(Vendor, VendorAdmin)
tenant_admin_site.register(VendorService, VendorServiceAdmin)
tenant_admin_site.register(VendorContract, VendorContractAdmin)
tenant_admin_site.register(VendorReview, VendorReviewAdmin)
tenant_admin_site.register(VendorPayment, VendorPaymentAdmin)
tenant_admin_site.register(VendorInsurance, VendorInsuranceAdmin)

# --- Support ---
tenant_admin_site.register(TicketCategory, TicketCategoryAdmin)
tenant_admin_site.register(Ticket, TicketAdmin)
tenant_admin_site.register(TicketComment, TicketCommentAdmin)
tenant_admin_site.register(FAQArticle, FAQArticleAdmin)

# --- Reports ---
tenant_admin_site.register(ReportTemplate, ReportTemplateAdmin)
tenant_admin_site.register(GeneratedReport, GeneratedReportAdmin)
tenant_admin_site.register(ScheduledReport, ScheduledReportAdmin)

# --- Reservations ---
tenant_admin_site.register(ReservableResource, ReservableResourceAdmin)
tenant_admin_site.register(Reservation, ReservationAdmin)

# --- Inspections ---
tenant_admin_site.register(InspectionTemplate, InspectionTemplateAdmin)
tenant_admin_site.register(Inspection, InspectionAdmin)
tenant_admin_site.register(InspectionPhoto, InspectionPhotoAdmin)




# V1 API patterns
v1_patterns = [
    path('auth/', include('accounts.urls')),
    path('properties/', include('properties.urls')),
    path('utilities/', include('utilities.urls')),
    path('calendar-alerts/', include('calendar_alerts.urls')),
    path('maintenance/', include('maintenance.urls')),
    path('amenities/', include('amenities.urls')),
    path('payments/', include('payments.urls')),
    path('notifications/', include('notifications.urls')),
    path('security/', include('security.urls')),
    path('parking/', include('parking.urls')),
    path('entertainment/', include('entertainment.urls')),
    path('communication/', include('communication.urls')),
    # path('visitors/', include('visitors.urls')),
    path('vendors/', include('vendors.urls')),
    path('marketplace/', include('marketplace.urls')),
    path('social/', include('social.urls')),
    
    # --- New Module APIs ---
    path('support/', include('support.urls')),
    path('analytics/', include('analytics.urls')),
    path('reports/', include('reports.urls')),
    path('system-reports/', include('reports.urls')),
    path('reservations/', include('reservations.urls')),
    path('inspections/', include('inspections.urls')),
    path('blog/', include('blog.urls')),
    # path('website/', include('website.urls')),
    path('system/tenants/', include('tenants.urls_system')),
    path('tenants/', include('tenants.urls')),
    path('location/', include('location_master.urls')),



    # --- Backup & Restore ---
    path('backups/', include('backups.urls')),

    # --- Developer Portal ---

    # --- SaaS Billing (tenants can manage their own subscription) ---
    path('pricing/', include('pricing.urls')),

    # --- Bulk Export ---
    path('export/', include('data_export.urls')),
]

urlpatterns = [
    # --- Auth & Roles (VVIP - MUST BE AT TOP) ---
    path('api/v1/auth/login/', LoginView.as_view(), name='tenant_login_direct'),
    path('api/v1/auth/login', LoginView.as_view(), name='tenant_login_direct_no_slash'),

    # --- System Info ---
    path('api/v1/system/tenants/current/', current_tenant),

    # Tenant admin interface
    path('admin/', tenant_admin_site.urls),

    # --- Versioned API (v1) ---
    path('api/v1/', include(v1_patterns)),

    # Backward compatibility (Legacy - will be deprecated)
    path('api/', include(v1_patterns)),
    path('api/auth/login/', LoginView.as_view()),
    path('api/system/auth/login/', LoginView.as_view()),
    path('api/system/tenants/current/', current_tenant),

    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[]), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema', permission_classes=[]), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema', permission_classes=[]), name='redoc'),

    # Health check
    path('api/health/', health_check_detailed, name='health'),
    path('api/health/live/', health_check_simple, name='health-liveness'),
    path('api/admin/health/', admin_health_check, name='health-admin'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if settings.DEBUG and 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns

# VAPT-2026-064 & VAPT-2026-066: Safe custom error handlers to prevent verbose pages leak
from propflow.urls_public import custom_handler404, custom_handler500
handler404 = custom_handler404
handler500 = custom_handler500
