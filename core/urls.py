from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    UserRegisterView, UserProfileView,
    CreditViewSet, RepaymentViewSet,
    InsuranceProductListView, InsuranceSubscribeView, MyInsurancePoliciesView,
    AdminDashboardView,
    NotificationViewSet,
    ChatConversationViewSet,
)

router = DefaultRouter()
router.register(r'credits', CreditViewSet, basename='credit')
router.register(r'repayments', RepaymentViewSet, basename='repayment')
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'chat/conversations', ChatConversationViewSet, basename='chat')

urlpatterns = [
    # --- MODULE 01 : Authentification & Profil ---
    path('auth/register/', UserRegisterView.as_view(), name='auth_register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('profile/', UserProfileView.as_view(), name='profile'),

    # --- MODULE 04 : Assurances ---
    # GET  /api/insurance/products/      → Catalogue public
    # POST /api/insurance/subscribe/     → Souscrire (Client)
    # GET  /api/insurance/my-policies/   → Polices actives du client
    path('insurance/products/', InsuranceProductListView.as_view(), name='insurance_products'),
    path('insurance/subscribe/', InsuranceSubscribeView.as_view(), name='insurance_subscribe'),
    path('insurance/my-policies/', MyInsurancePoliciesView.as_view(), name='insurance_my_policies'),

    # --- MODULE 05 : Tableau de bord Admin ---
    # GET /api/dashboard/  (Admin uniquement)
    path('dashboard/', AdminDashboardView.as_view(), name='admin_dashboard'),

    # --- Router ViewSets (credits, repayments, notifications, chat) ---
    path('', include(router.urls)),
]
