from rest_framework import viewsets, status, permissions, generics, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from decimal import Decimal
from datetime import datetime

from .models import (
    LoanRequest, RepaymentInstallment, Payment,
    InsuranceProduct, InsuranceSubscription, Notification,
    ChatConversation, ChatMessage, AuditLog
)
from .serializers import (
    UserSerializer, UserRegisterSerializer, UserAdminSerializer,
    ChangePasswordSerializer, AuditLogSerializer, AvatarUploadSerializer,
    LoanRequestSerializer, RepaymentInstallmentSerializer, PaymentSerializer,
    InsuranceProductSerializer, InsuranceSubscriptionSerializer,
    NotificationSerializer, ChatConversationSerializer, ChatMessageSerializer
)
from .permissions import IsClient, IsAgent, IsAdmin, IsClientOrAgent
from .services import assign_agent_to_conversation

User = get_user_model()


# =============================================================================
# PAGINATION GLOBALE
# =============================================================================

class StandardPagination(PageNumberPagination):
    """
    Pagination standard : 10 éléments par page.
    Paramètres : ?page=2&page_size=20 (max 100)
    """
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


# =============================================================================
# MODULE 01 — AUTHENTIFICATION & PROFIL
# =============================================================================

class UserRegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/ — Inscription publique.
    Retourne les tokens JWT à la création.
    """
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = (permissions.AllowAny,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }, status=status.HTTP_201_CREATED)


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    GET/PATCH /api/profile/ — Consulter et modifier son profil.
    Accessible à tous les rôles.
    """
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        return self.request.user

    def get_serializer_context(self):
        """Passe le request pour générer l'URL absolue de l'avatar."""
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class ChangePasswordView(APIView):
    """
    POST /api/auth/change-password/ — Changer son mot de passe.
    Accessible à tous les utilisateurs connectés (CLIENT, AGENT, ADMIN).
    Exige l'ancien mot de passe + nouveau (min 8 cars, 1 lettre + 1 chiffre) + confirmation.
    """
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        old_password = serializer.validated_data['old_password']
        new_password = serializer.validated_data['new_password']

        if not check_password(old_password, user.password):
            return Response(
                {'old_password': "L'ancien mot de passe est incorrect."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save()

        # Invalider les tokens actuels en forcéant un nouveau refresh
        refresh = RefreshToken.for_user(user)
        return Response({
            'message': "Mot de passe modifié avec succès.",
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_200_OK)


class AvatarUploadView(APIView):
    """
    Gestion de la photo de profil — accessible à tous les utilisateurs connectés.

    POST  /api/profile/avatar/ — Uploader ou remplacer la photo de profil.
        Body : multipart/form-data avec le champ 'avatar' (JPEG/PNG, max 5 Mo).
        Réponse : {message, avatar_url}

    DELETE /api/profile/avatar/ — Supprimer la photo de profil.
        Réponse : {message}
    """
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes_override = None  # Accepte multipart et JSON

    def post(self, request):
        """Upload ou remplacement de la photo de profil."""
        serializer = AvatarUploadSerializer(
            instance=request.user,
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        avatar_url = None
        if user.avatar:
            avatar_url = request.build_absolute_uri(user.avatar.url)

        return Response({
            'message': "Photo de profil mise à jour avec succès.",
            'avatar_url': avatar_url,
        }, status=status.HTTP_200_OK)

    def delete(self, request):
        """Suppression de la photo de profil."""
        user = request.user
        if not user.avatar:
            return Response(
                {'error': "Vous n'avez pas de photo de profil à supprimer."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Supprimer le fichier physiquement
        import os
        if os.path.isfile(user.avatar.path):
            os.remove(user.avatar.path)
        user.avatar = None
        user.save(update_fields=['avatar'])
        return Response(
            {'message': "Photo de profil supprimée avec succès."},
            status=status.HTTP_200_OK
        )


# =============================================================================
# MODULE 02 — GESTION DES CRÉDITS
# =============================================================================

class CreditViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour les demandes de crédit — montées sous /api/credits/

    CLIENT:
      - POST /api/credits/                  → déposer UNE demande (bloqué si 1 crédit actif)
      - GET  /api/credits/                  → ses propres demandes UNIQUEMENT (paginaté)
      - GET  /api/credits/{id}/echeancier/  → voir son échéancier
      - PUT/PATCH sur crédit SOUMIS  → autorisé
      - PUT/PATCH sur crédit EN_ANALYSE/APPROUVEE/DECAISSEE → INTERDIT (409)
      - DELETE sur crédit EN_ANALYSE/APPROUVEE/DECAISSEE     → INTERDIT (409)

    AGENT / ADMIN:
      - GET  /api/credits/                  → TOUTES les demandes (paginaté)
      - PATCH /api/credits/{id}/status/     → avancer le statut (workflow unidirectionnel)
    """
    serializer_class = LoanRequestSerializer
    permission_classes = (permissions.IsAuthenticated,)
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        if user.role in ['AGENT', 'ADMIN']:
            return LoanRequest.objects.all().order_by('-created_at')
        return LoanRequest.objects.filter(client=user).order_by('-created_at')

    def get_permissions(self):
        if self.action == 'create':
            return [IsClient()]
        if self.action == 'change_status':
            return [IsAgent()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        user = self.request.user
        # ——— Règle métier : 1 seul crédit actif à la fois ———
        active_loan = LoanRequest.objects.filter(
            client=user,
            status__in=LoanRequest.ACTIVE_STATUSES
        ).first()
        if active_loan:
            raise serializers.ValidationError(
                f"Vous avez déjà un crédit actif (#{active_loan.id} — statut : {active_loan.get_status_display()}). "
                "Votre demande ne peut pas être soumise tant qu'il n'est pas décaissé et remboursé."
            )
        loan = serializer.save(client=user, status='SOUMISE')
        for staff in User.objects.filter(role__in=['AGENT', 'ADMIN']):
            Notification.objects.create(
                user=staff,
                message=(
                    f"Nouvelle demande de crédit #{loan.id} soumise par "
                    f"{user.username} pour {loan.amount} FCFA."
                ),
                notification_type='CREDIT_STATUS'
            )

    def update(self, request, *args, **kwargs):
        """Bloquer la modification d'une demande déjà en traitement."""
        loan = self.get_object()
        if request.user.role == 'CLIENT' and loan.status != 'SOUMISE':
            return Response(
                {'error': f"Ce crédit est au statut '{loan.get_status_display()}' et ne peut plus être modifié."},
                status=status.HTTP_409_CONFLICT
            )
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Bloquer la suppression d'une demande déjà en traitement."""
        loan = self.get_object()
        if request.user.role == 'CLIENT' and loan.status != 'SOUMISE':
            return Response(
                {'error': f"Ce crédit est au statut '{loan.get_status_display()}' et ne peut pas être supprimé."},
                status=status.HTTP_409_CONFLICT
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['patch'], permission_classes=[IsAgent], url_path='status')
    def change_status(self, request, pk=None):
        """
        PATCH /api/credits/{id}/status/ — Agents et Admins uniquement.
        Workflow STRICTEMENT unidirectionnel : SOUMISE → EN_ANALYSE → APPROUVEE → DECAISSEE.
        Toute rétrogradation est refusée avec un message explicite.
        """
        loan = self.get_object()
        new_status = request.data.get('status')

        valid_statuses = [c[0] for c in LoanRequest.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response(
                {'error': f"Statut invalide. Valeurs possibles : {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ——— Contrôle workflow unidirectionnel ———
        current_order = LoanRequest.WORKFLOW_ORDER.get(loan.status, -1)
        new_order = LoanRequest.WORKFLOW_ORDER.get(new_status, -1)
        if new_order <= current_order:
            return Response(
                {
                    'error': (
                        f"Rétrogradation interdite. Le crédit est au statut '{loan.get_status_display()}' "
                        f"et ne peut pas passer à '{new_status}'. "
                        f"Workflow autorisé : SOUMISE → EN_ANALYSE → APPROUVEE → DECAISSEE."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        old_status = loan.status
        loan.status = new_status

        if new_status == 'APPROUVEE' and old_status != 'APPROUVEE':
            loan.generate_schedule()

        loan.save()

        # Notification client
        Notification.objects.create(
            user=loan.client,
            message=(
                f"Le statut de votre demande de crédit #{loan.id} est passé "
                f"de '{old_status}' à '{new_status}'."
            ),
            notification_type='CREDIT_STATUS'
        )

        # Journal d'audit
        AuditLog.objects.create(
            actor=request.user,
            action='CREDIT_STATUS_CHANGE',
            target_model='LoanRequest',
            target_id=loan.id,
            description=(
                f"{request.user.username} a fait passer le crédit #{loan.id} "
                f"de '{old_status}' à '{new_status}' "
                f"(client : {loan.client.username}, montant : {loan.amount} FCFA)."
            )
        )
        return Response(LoanRequestSerializer(loan).data)

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated], url_path='echeancier')
    def echeancier(self, request, pk=None):
        """
        GET /api/credits/{id}/echeancier/ — Échéancier d'un crédit.
        Un CLIENT ne voit QUE son propre échéancier.
        """
        loan = self.get_object()
        if request.user.role == 'CLIENT' and loan.client != request.user:
            return Response(
                {'error': "Vous n'avez pas accès à ce crédit."},
                status=status.HTTP_403_FORBIDDEN
            )
        installments = loan.installments.all()
        return Response(RepaymentInstallmentSerializer(installments, many=True).data)


# =============================================================================
# MODULE 03 — SUIVI DES REMBOURSEMENTS
# =============================================================================

class RepaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour les remboursements — monté sous /api/repayments/

    AGENT / ADMIN: POST /api/repayments/   → enregistrer un paiement (+ AuditLog)
    CLIENT:        GET  /api/repayments/   → son historique uniquement
    """
    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAuthenticated,)
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        if user.role in ['AGENT', 'ADMIN']:
            return Payment.objects.all().order_by('-paid_at')
        return Payment.objects.filter(loan_request__client=user).order_by('-paid_at')

    def get_permissions(self):
        if self.action == 'create':
            return [IsAgent()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        payment = serializer.save(recorded_by=self.request.user)
        Notification.objects.create(
            user=payment.loan_request.client,
            message=(
                f"Un remboursement de {payment.amount} FCFA a été enregistré "
                f"pour votre crédit #{payment.loan_request.id}."
            ),
            notification_type='PAYMENT'
        )
        # Journal d'audit
        AuditLog.objects.create(
            actor=self.request.user,
            action='PAYMENT_RECORDED',
            target_model='Payment',
            target_id=payment.id,
            description=(
                f"{self.request.user.username} a enregistré un paiement de {payment.amount} FCFA "
                f"pour le crédit #{payment.loan_request.id} du client {payment.loan_request.client.username}."
            )
        )


# =============================================================================
# MODULE 04 — PRODUITS D'ASSURANCE MOBILE
# =============================================================================

class InsuranceProductListView(generics.ListAPIView):
    """
    GET /api/insurance/products/ — Catalogue public des formules d'assurance.
    """
    queryset = InsuranceProduct.objects.all()
    serializer_class = InsuranceProductSerializer
    permission_classes = (permissions.AllowAny,)


class InsuranceSubscribeView(generics.CreateAPIView):
    """
    POST /api/insurance/subscribe/ — Souscrire à une formule (CLIENT uniquement).
    Refusé si le client a déjà une souscription active pour ce produit.
    """
    serializer_class = InsuranceSubscriptionSerializer
    permission_classes = (IsClient,)

    def perform_create(self, serializer):
        subscription = serializer.save(client=self.request.user, is_active=True)
        Notification.objects.create(
            user=self.request.user,
            message=(
                f"Félicitations ! Vous avez souscrit à la formule "
                f"'{subscription.product.name}'. Validité : {subscription.start_date} au {subscription.end_date}."
            ),
            notification_type='INSURANCE'
        )


class MyInsurancePoliciesView(generics.ListAPIView):
    """
    GET /api/insurance/my-policies/ — Polices actives du CLIENT connecté.
    """
    serializer_class = InsuranceSubscriptionSerializer
    permission_classes = (IsClient,)

    def get_queryset(self):
        return InsuranceSubscription.objects.filter(
            client=self.request.user
        ).order_by('-start_date')


# =============================================================================
# MODULE 05 — TABLEAU DE BORD ADMIN (ENRICHI)
# =============================================================================

class AdminDashboardView(APIView):
    """
    GET /api/dashboard/ — Tableau de bord enrichi. ADMIN UNIQUEMENT.
    Filtres : ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&agent=<id>&region=<str>
    Nouvelles métriques : clients actifs, agents, crédits du jour, souscriptions expirées.
    """
    permission_classes = (IsAdmin,)

    def get(self, request):
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        agent_id = request.query_params.get('agent')
        region = request.query_params.get('region')

        loans = LoanRequest.objects.all()
        payments = Payment.objects.all()
        subscriptions = InsuranceSubscription.objects.filter(is_active=True)
        chats = ChatConversation.objects.filter(status='OPEN')
        installments = RepaymentInstallment.objects.all()

        if region:
            loans = loans.filter(client__region__iexact=region)
            payments = payments.filter(loan_request__client__region__iexact=region)
            subscriptions = subscriptions.filter(client__region__iexact=region)
            chats = chats.filter(client__region__iexact=region)
            installments = installments.filter(loan_request__client__region__iexact=region)

        if agent_id:
            payments = payments.filter(recorded_by_id=agent_id)
            chats = chats.filter(agent_id=agent_id)

        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                loans = loans.filter(created_at__range=(start_date, end_date))
                payments = payments.filter(paid_at__range=(start_date, end_date))
                installments = installments.filter(due_date__range=(start_date, end_date))
            except ValueError:
                return Response(
                    {'error': "Format de date invalide. Utilisez YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        status_volumes = loans.values('status').annotate(
            count=Count('id'),
            total_amount=Sum('amount')
        )

        total_due = installments.aggregate(
            total=Sum(F('amount_due') + F('penalty_amount'))
        )['total'] or Decimal('0.00')
        total_paid = installments.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        recovery_rate = float((total_paid / total_due) * 100) if total_due > 0 else 0.0

        today = timezone.localdate()
        credits_today = LoanRequest.objects.filter(created_at__date=today).count()
        payments_today = Payment.objects.filter(paid_at__date=today).count()
        expired_subscriptions = InsuranceSubscription.objects.filter(
            is_active=True, end_date__lt=today
        ).count()

        return Response({
            # —— Métriques principales ——
            'loans_by_status': status_volumes,
            'recovery_stats': {
                'total_due': total_due,
                'total_paid': total_paid,
                'recovery_rate': round(recovery_rate, 2)
            },
            'active_subscriptions_count': subscriptions.count(),
            'open_chats_count': chats.count(),
            # —— Métriques utilisateurs ——
            'users_summary': {
                'total_clients': User.objects.filter(role='CLIENT', is_active=True).count(),
                'total_agents': User.objects.filter(role='AGENT', is_active=True).count(),
                'total_admins': User.objects.filter(role='ADMIN', is_active=True).count(),
                'inactive_accounts': User.objects.filter(is_active=False).count(),
            },
            # —— Activité du jour ——
            'today_activity': {
                'credits_submitted_today': credits_today,
                'payments_recorded_today': payments_today,
                'expired_subscriptions': expired_subscriptions,
            },
            'filters_applied': {
                'start_date': start_date_str,
                'end_date': end_date_str,
                'agent': agent_id,
                'region': region
            }
        })


# =============================================================================
# MODULE 05B — GESTION DES UTILISATEURS (ADMIN UNIQUEMENT)
# =============================================================================

class UserManagementViewSet(viewsets.ModelViewSet):
    """
    ViewSet de gestion des utilisateurs réservé aux ADMINS.

    GET    /api/admin/users/                → lister tous les utilisateurs (paginaté, filtrable)
    POST   /api/admin/users/                → créer un agent ou un admin
    GET    /api/admin/users/{id}/           → détail d'un utilisateur
    PATCH  /api/admin/users/{id}/           → modifier un utilisateur
    PATCH  /api/admin/users/{id}/toggle_active/ → activer/désactiver un compte

    Filtres : ?role=CLIENT|AGENT|ADMIN&region=Abidjan&is_active=true|false
    """
    serializer_class = UserAdminSerializer
    permission_classes = (IsAdmin,)
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = User.objects.all().order_by('-date_joined')
        role = self.request.query_params.get('role')
        region = self.request.query_params.get('region')
        is_active = self.request.query_params.get('is_active')
        if role:
            qs = qs.filter(role=role.upper())
        if region:
            qs = qs.filter(region__icontains=region)
        if is_active is not None:
            qs = qs.filter(is_active=(is_active.lower() == 'true'))
        return qs

    def perform_create(self, serializer):
        user = serializer.save()
        AuditLog.objects.create(
            actor=self.request.user,
            action='USER_CREATED',
            target_model='User',
            target_id=user.id,
            description=(
                f"L'administrateur {self.request.user.username} a créé le compte "
                f"'{user.username}' (rôle : {user.role}, région : {user.region})."
            )
        )

    @action(detail=True, methods=['patch'], url_path='toggle_active')
    def toggle_active(self, request, pk=None):
        """
        PATCH /api/admin/users/{id}/toggle_active/ — Activer ou désactiver un compte.
        Un admin ne peut pas désactiver son propre compte.
        """
        user = self.get_object()
        if user == request.user:
            return Response(
                {'error': "Vous ne pouvez pas désactiver votre propre compte."},
                status=status.HTTP_400_BAD_REQUEST
            )
        user.is_active = not user.is_active
        user.save()
        action_label = "activé" if user.is_active else "désactivé"
        AuditLog.objects.create(
            actor=request.user,
            action='USER_TOGGLED',
            target_model='User',
            target_id=user.id,
            description=f"L'administrateur {request.user.username} a {action_label} le compte de {user.username}."
        )
        return Response({
            'id': user.id,
            'username': user.username,
            'is_active': user.is_active,
            'message': f"Le compte de '{user.username}' a été {action_label} avec succès."
        })


# =============================================================================
# MODULE 06 — NOTIFICATIONS INTERNES
# =============================================================================

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/notifications/ — Notifications de l'utilisateur connecté.
    Chaque utilisateur ne voit QUE ses propres notifications.
    """
    serializer_class = NotificationSerializer
    permission_classes = (permissions.IsAuthenticated,)
    pagination_class = StandardPagination

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=['patch'])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=['patch'])
    def mark_all_as_read(self, request):
        Notification.objects.filter(user=self.request.user, is_read=False).update(is_read=True)
        return Response({'status': 'Toutes les notifications ont été marquées comme lues.'})


# =============================================================================
# MODULE 06B — JOURNAL D'AUDIT DE L'AGENT
# =============================================================================

class AgentActivityView(generics.ListAPIView):
    """
    GET /api/agent/activity/ — Journal des actions de l'agent connecté.
    Chaque agent ne voit QUE ses propres actions enregistrées.
    Les ADMINS voient l'activité de tous les agents.
    Filtres : ?action=CREDIT_STATUS_CHANGE|PAYMENT_RECORDED|CHAT_JOINED
    """
    serializer_class = AuditLogSerializer
    permission_classes = (IsAgent,)
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        qs = AuditLog.objects.all() if user.role == 'ADMIN' else AuditLog.objects.filter(actor=user)
        action_filter = self.request.query_params.get('action')
        if action_filter:
            qs = qs.filter(action=action_filter.upper())
        return qs


class AgentClientProfileView(APIView):
    """
    GET /api/agent/clients/{id}/ — Profil client agrégé pour agents et admins.
    Retourne : informations client, crédits, échéanciers, remboursements, score moyen.
    """
    permission_classes = (IsAgent,)

    def get(self, request, client_id):
        try:
            client = User.objects.get(id=client_id, role='CLIENT')
        except User.DoesNotExist:
            return Response(
                {'error': "Client introuvable avec cet identifiant."},
                status=status.HTTP_404_NOT_FOUND
            )

        loans = LoanRequest.objects.filter(client=client).order_by('-created_at')
        payments = Payment.objects.filter(loan_request__client=client).order_by('-paid_at')
        subscriptions = InsuranceSubscription.objects.filter(client=client, is_active=True)

        total_due = Decimal('0.00')
        total_paid = Decimal('0.00')
        overdue_count = 0
        today = timezone.localdate()

        for loan in loans.filter(status='DECAISSEE'):
            for inst in loan.installments.all():
                total_due += inst.total_due
                total_paid += inst.amount_paid
                if not inst.is_paid and inst.due_date < today:
                    overdue_count += 1

        scores = [loan.eligibility_score for loan in loans]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 50

        return Response({
            'client': UserSerializer(client, context={'request': request}).data,
            'summary': {
                'total_loans': loans.count(),
                'active_loans': loans.filter(status__in=LoanRequest.ACTIVE_STATUSES).count(),
                'disbursed_loans': loans.filter(status='DECAISSEE').count(),
                'average_eligibility_score': avg_score,
                'total_due': total_due,
                'total_paid': total_paid,
                'remaining_balance': max(Decimal('0.00'), total_due - total_paid),
                'overdue_installments': overdue_count,
                'active_insurance_policies': subscriptions.count(),
            },
            'loans': LoanRequestSerializer(loans, many=True).data,
            'payments': PaymentSerializer(payments, many=True).data,
            'insurance_policies': InsuranceSubscriptionSerializer(subscriptions, many=True).data,
        })


class RunAlertsView(APIView):
    """
    POST /api/admin/run-alerts/ — Déclenche manuellement les alertes J-3, J+1, J-15 et pénalités.
    Réservé aux administrateurs (simule l'exécution du cron journalier).
    """
    permission_classes = (IsAdmin,)

    def post(self, request):
        from django.core.management import call_command
        from io import StringIO

        output = StringIO()
        call_command('run_alerts', stdout=output)
        return Response({
            'message': "Alertes quotidiennes exécutées avec succès.",
            'details': output.getvalue().strip().split('\n'),
        })


# =============================================================================
# MODULE 07 — CHAT EN TEMPS REEL
# =============================================================================

class ChatConversationViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour les conversations de support — monte sous /api/chat/conversations/

    CLIENT:
      - POST /api/chat/conversations/      → ouvrir une conversation
      - GET  /api/chat/conversations/      → ses propres conversations uniquement

    AGENT:
      - GET  /api/chat/conversations/      → toutes les conversations ouvertes
      - WS   /ws/chat/conversations/{id}/  → rejoindre une session

    ADMIN:
      - GET  /api/chat/conversations/          → toutes les conversations
      - PATCH /api/chat/conversations/{id}/assign/ → assigner manuellement un agent
    """
    serializer_class = ChatConversationSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        user = self.request.user
        if user.role in ['AGENT', 'ADMIN']:
            return ChatConversation.objects.all().order_by('-created_at')
        # CLIENT voit uniquement ses propres conversations
        return ChatConversation.objects.filter(client=user).order_by('-created_at')

    def get_permissions(self):
        if self.action == 'create':
            return [IsClient()]
        if self.action == 'assign':
            return [IsAdmin()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        conversation = serializer.save(client=self.request.user, status='OPEN')
        assigned_agent = assign_agent_to_conversation(conversation)

        if assigned_agent:
            Notification.objects.create(
                user=assigned_agent,
                message=(
                    f"Le client {self.request.user.username} a ouvert une session de support "
                    f"chat #{conversation.id}. Vous avez été assigné automatiquement."
                ),
                notification_type='SUPPORT'
            )
            Notification.objects.create(
                user=self.request.user,
                message=(
                    f"L'agent {assigned_agent.username} a été assigné à votre conversation "
                    f"de support #{conversation.id}."
                ),
                notification_type='SUPPORT'
            )
        else:
            for agent in User.objects.filter(role='AGENT', is_active=True):
                Notification.objects.create(
                    user=agent,
                    message=(
                        f"Le client {self.request.user.username} a ouvert "
                        f"une session de support chat #{conversation.id} (en attente d'assignation)."
                    ),
                    notification_type='SUPPORT'
                )

    @action(detail=True, methods=['post'], permission_classes=[IsAgent], url_path='join')
    def join(self, request, pk=None):
        """
        POST /api/chat/conversations/{id}/join/ — Agent rejoint une conversation.
        """
        conversation = self.get_object()
        if conversation.status == 'CLOSED':
            return Response(
                {'error': "Cette conversation est fermée."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if conversation.agent and conversation.agent != request.user and request.user.role != 'ADMIN':
            return Response(
                {
                    'error': (
                        f"Cette conversation est déjà prise en charge par "
                        f"l'agent {conversation.agent.username}."
                    )
                },
                status=status.HTTP_409_CONFLICT
            )
        conversation.agent = request.user
        conversation.save()
        Notification.objects.create(
            user=conversation.client,
            message=f"L'agent {request.user.username} a rejoint votre conversation de support.",
            notification_type='SUPPORT'
        )
        AuditLog.objects.create(
            actor=request.user,
            action='CHAT_JOINED',
            target_model='ChatConversation',
            target_id=conversation.id,
            description=f"{request.user.username} a rejoint la conversation de support #{conversation.id} du client {conversation.client.username}."
        )
        return Response(ChatConversationSerializer(conversation).data)

    @action(detail=True, methods=['patch'], permission_classes=[IsAdmin], url_path='assign')
    def assign(self, request, pk=None):
        """
        PATCH /api/chat/conversations/{id}/assign/ — ADMIN uniquement.
        Assigner manuellement un agent à une conversation.
        """
        conversation = self.get_object()
        agent_id = request.data.get('agent_id')
        if not agent_id:
            return Response(
                {'error': "Le champ 'agent_id' est requis."},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            agent = User.objects.get(id=agent_id, role='AGENT')
        except User.DoesNotExist:
            return Response(
                {'error': "Agent introuvable avec cet identifiant."},
                status=status.HTTP_404_NOT_FOUND
            )
        conversation.agent = agent
        conversation.save()
        Notification.objects.create(
            user=conversation.client,
            message=f"L'agent {agent.username} a été assigné à votre conversation de support.",
            notification_type='SUPPORT'
        )
        Notification.objects.create(
            user=agent,
            message=f"Vous avez été assigné à la conversation de support de {conversation.client.username}.",
            notification_type='SUPPORT'
        )
        AuditLog.objects.create(
            actor=request.user,
            action='CHAT_ASSIGNED',
            target_model='ChatConversation',
            target_id=conversation.id,
            description=f"{request.user.username} a assigné l'agent {agent.username} à la conversation #{conversation.id} de {conversation.client.username}."
        )
        return Response(ChatConversationSerializer(conversation).data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated], url_path='close')
    def close(self, request, pk=None):
        """
        POST /api/chat/conversations/{id}/close/ — Fermer une conversation.
        """
        conversation = self.get_object()
        conversation.status = 'CLOSED'
        conversation.save()
        return Response(ChatConversationSerializer(conversation).data)

    @action(detail=True, methods=['get', 'post'], permission_classes=[permissions.IsAuthenticated], url_path='messages')
    def messages(self, request, pk=None):
        """
        GET  /api/chat/conversations/{id}/messages/ — Historique des messages.
        POST /api/chat/conversations/{id}/messages/ — Envoyer un message (fallback REST).
        """
        conversation = self.get_object()

        # Sécurité : un client ne peut voir que ses propres conversations
        if request.user.role == 'CLIENT' and conversation.client != request.user:
            return Response(
                {'error': "Vous n'avez pas accès à cette conversation."},
                status=status.HTTP_403_FORBIDDEN
            )

        if request.method == 'POST':
            serializer = ChatMessageSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            message = serializer.save(conversation=conversation, sender=request.user)
            return Response(ChatMessageSerializer(message).data, status=status.HTTP_201_CREATED)

        msgs = conversation.messages.all()
        return Response(ChatMessageSerializer(msgs, many=True).data)
