# accounts/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from . import views, dashboard_views
from .views import available_roles
from . import owner_views

# Router for ViewSets
router = DefaultRouter()
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'roles', views.RoleViewSet, basename='role')
router.register(r'permissions', views.PermissionViewSet, basename='permission')

urlpatterns = [
    # ViewSet routes (includes users/, roles/, permissions/ and their actions)
    path('', include(router.urls)),

    # --- Authentication ---
    path('available-roles/', available_roles, name='available_roles'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('token/refresh/', views.CookieTokenRefreshView.as_view(), name='token_refresh'),

    # --- Password management ---
    path('change-password/', views.change_password, name='change_password'),
    path('request-password-reset/', views.request_password_reset, name='request_password_reset'),
    path('reset-password/', views.reset_password, name='reset_password'),

    # --- OTP ---
    path('request-otp/', views.request_otp, name='request_otp'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),

    # --- Email verification ---
    path('verify-email/', views.verify_email, name='verify_email'),

    # --- Current user / profile ---
    path('me/', views.current_user, name='current_user'),
    path('profile/', views.update_profile, name='update_profile'),

    # --- RBAC endpoints ---
    path('my-permissions/', views.my_permissions, name='my_permissions'),
    path('check-permissions/', views.check_permissions, name='check_permissions'),

    # --- Notification preferences ---
    path('notification-preferences/', views.notification_preferences, name='notification_preferences'),

    # --- Dashboard & activity ---
    path('dashboard/stats/', views.dashboard_stats, name='dashboard_stats'),
    path('activity/', views.activity_logs, name='activity_logs'),
    path('activity/<int:pk>/', views.activity_log_detail, name='activity_log_detail'),

    # --- Role-specific dashboard views ---
    path('dashboard/master-admin-stats/', dashboard_views.master_admin_stats, name='master_admin_stats'),
    path('dashboard/facility-manager-stats/', dashboard_views.facility_manager_stats, name='facility_manager_stats'),
    path('dashboard/resident-stats/', dashboard_views.resident_stats, name='resident_stats'),

    # --- Owner self-service APIs ---
    path('owner/dashboard/stats/', owner_views.owner_dashboard_stats, name='owner_dashboard_stats'),
    path('owner/tenants/', owner_views.owner_tenants_list, name='owner_tenants_list'),
    path('owner/tenants/invite/', owner_views.owner_invite_tenant, name='owner_invite_tenant'),
    path('owner/tenants/<uuid:tenant_id>/', owner_views.owner_tenant_detail, name='owner_tenant_detail'),
    path('owner/tenants/<uuid:tenant_id>/approve/', owner_views.owner_approve_tenant, name='owner_approve_tenant'),
    path('owner/tenants/<uuid:tenant_id>/summary/', owner_views.owner_tenant_summary, name='owner_tenant_summary'),

    # --- CSV Processing ---
    path('csv/', include('accounts.csv_urls')),

    # --- People Hub ---
    path('people-hub/', include('accounts.people_hub_urls')),

    # --- Backward compatibility aliases ---
    path('profile/update/', views.update_profile, name='profile_update'),
    path('users/me/', views.current_user, name='user_me'),
]
