from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    UserRegisterView, UserProfileView, ChangePasswordView, AvatarUploadView,
    CreditViewSet, RepaymentViewSet,
    InsuranceProductListView, InsuranceSubscribeView, MyInsurancePoliciesView,
    AdminDashboardView, UserManagementViewSet,
    NotificationViewSet, AgentActivityView, AgentClientProfileView, RunAlertsView,
    ChatConversationViewSet,
)

router = DefaultRouter()
router.register(r'credits', CreditViewSet, basename='credit')
router.register(r'repayments', RepaymentViewSet, basename='repayment')
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'chat/conversations', ChatConversationViewSet, basename='chat')
router.register(r'admin/users', UserManagementViewSet, basename='admin-users')

urlpatterns = [
    # --- MODULE 01 : Authentification & Profil ---
    path('auth/register/', UserRegisterView.as_view(), name='auth_register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('profile/avatar/', AvatarUploadView.as_view(), name='profile_avatar'),

    # --- MODULE 04 : Assurances ---
    path('insurance/products/', InsuranceProductListView.as_view(), name='insurance_products'),
    path('insurance/subscribe/', InsuranceSubscribeView.as_view(), name='insurance_subscribe'),
    path('insurance/my-policies/', MyInsurancePoliciesView.as_view(), name='insurance_my_policies'),

    # --- MODULE 05 : Tableau de bord Admin ---
    path('dashboard/', AdminDashboardView.as_view(), name='admin_dashboard'),

    # --- MODULE 06B : Journal d'audit Agent ---
    path('agent/activity/', AgentActivityView.as_view(), name='agent_activity'),
    path('agent/clients/<int:client_id>/', AgentClientProfileView.as_view(), name='agent_client_profile'),

    # --- MODULE 05C : Alertes & pilotage admin ---
    path('admin/run-alerts/', RunAlertsView.as_view(), name='admin_run_alerts'),

    # --- Router ViewSets ---
    path('', include(router.urls)),
]
