from rest_framework import viewsets, status, permissions, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.db.models import Sum, Count, Q
from django.utils import timezone
from decimal import Decimal
from datetime import datetime

from .models import (
    LoanRequest, RepaymentInstallment, Payment,
    InsuranceProduct, InsuranceSubscription, Notification,
    ChatConversation, ChatMessage
)
from .serializers import (
    UserSerializer, UserRegisterSerializer,
    LoanRequestSerializer, RepaymentInstallmentSerializer, PaymentSerializer,
    InsuranceProductSerializer, InsuranceSubscriptionSerializer,
    NotificationSerializer, ChatConversationSerializer, ChatMessageSerializer
)
from .permissions import IsClient, IsAgent, IsAdmin, IsClientOrAgent

User = get_user_model()


# =============================================================================
# MODULE 01 — AUTHENTIFICATION & PROFIL
# =============================================================================

class UserRegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/ — Public registration endpoint.
    Returns JWT tokens on successful registration.
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
    GET/PATCH /api/profile/ — View and update the authenticated user's own profile.
    All roles can access their own profile.
    """
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        return self.request.user


# =============================================================================
# MODULE 02 — GESTION DES CREDITS (anciennement loans)
# =============================================================================

class CreditViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour les demandes de credit — montees sous /api/credits/

    CLIENT:
      - POST /api/credits/               → deposer une demande
      - GET  /api/credits/               → ses propres demandes UNIQUEMENT
      - GET  /api/credits/{id}/echeancier/ → voir son echeancier

    AGENT / ADMIN:
      - GET  /api/credits/               → TOUTES les demandes
      - PATCH /api/credits/{id}/status/  → changer le statut

    Regles de securite strictes:
      - Un client recoit 403 s'il tente PATCH /status/
      - Un client ne voit jamais les credits d'un autre client (filtre strict)
    """
    serializer_class = LoanRequestSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        user = self.request.user
        # AGENT et ADMIN voient tout
        if user.role in ['AGENT', 'ADMIN']:
            return LoanRequest.objects.all().order_by('-created_at')
        # CLIENT voit uniquement ses propres credits
        return LoanRequest.objects.filter(client=user).order_by('-created_at')

    def get_permissions(self):
        """
        - create: CLIENT uniquement
        - change_status: AGENT et ADMIN uniquement
        - echeancier: CLIENT uniquement (ses propres donnees)
        - list/retrieve: tous les utilisateurs authentifies (avec filtre queryset)
        """
        if self.action == 'create':
            return [IsClient()]
        if self.action == 'change_status':
            return [IsAgent()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        loan = serializer.save(client=self.request.user, status='SOUMISE')
        # Notifier tous les agents et admins
        for staff in User.objects.filter(role__in=['AGENT', 'ADMIN']):
            Notification.objects.create(
                user=staff,
                message=(
                    f"Nouvelle demande de credit #{loan.id} soumise par "
                    f"{self.request.user.username} pour {loan.amount} FCFA."
                ),
                notification_type='CREDIT_STATUS'
            )

    @action(detail=True, methods=['patch'], permission_classes=[IsAgent], url_path='status')
    def change_status(self, request, pk=None):
        """
        PATCH /api/credits/{id}/status/ — Agents et Admins uniquement.
        Un CLIENT qui appelle cet endpoint recevra 403 Forbidden.
        Workflow autorise : SOUMISE -> EN_ANALYSE -> APPROUVEE -> DECAISSEE
        """
        loan = self.get_object()
        new_status = request.data.get('status')

        valid_statuses = [c[0] for c in LoanRequest.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response(
                {'error': f"Statut invalide. Valeurs possibles : {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_status = loan.status
        loan.status = new_status

        # Generer l'echeancier automatiquement lors du passage a APPROUVEE
        if new_status == 'APPROUVEE' and old_status != 'APPROUVEE':
            loan.generate_schedule()

        loan.save()

        # Notification interne pour le client
        Notification.objects.create(
            user=loan.client,
            message=(
                f"Le statut de votre demande de credit #{loan.id} est passe "
                f"de '{old_status}' a '{new_status}'."
            ),
            notification_type='CREDIT_STATUS'
        )
        return Response(LoanRequestSerializer(loan).data)

    @action(detail=True, methods=['get'], permission_classes=[permissions.IsAuthenticated], url_path='echeancier')
    def echeancier(self, request, pk=None):
        """
        GET /api/credits/{id}/echeancier/ — Voir l'echeancier d'un credit.
        Un CLIENT ne voit QUE son propre echeancier (filtre via get_object).
        """
        loan = self.get_object()

        # Securite supplementaire : un client ne peut voir que son propre credit
        if request.user.role == 'CLIENT' and loan.client != request.user:
            return Response(
                {'error': "Vous n'avez pas acces a ce credit."},
                status=status.HTTP_403_FORBIDDEN
            )

        installments = loan.installments.all()
        return Response(RepaymentInstallmentSerializer(installments, many=True).data)


# =============================================================================
# MODULE 03 — SUIVI DES REMBOURSEMENTS
# =============================================================================

class RepaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour les remboursements — monte sous /api/repayments/

    AGENT / ADMIN: POST /api/repayments/   → enregistrer un paiement
    CLIENT:        GET  /api/repayments/   → son historique uniquement
    """
    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        user = self.request.user
        if user.role in ['AGENT', 'ADMIN']:
            return Payment.objects.all().order_by('-paid_at')
        # CLIENT : historique de remboursements de ses propres credits uniquement
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
                f"Un remboursement de {payment.amount} FCFA a ete enregistre "
                f"pour votre credit #{payment.loan_request.id}."
            ),
            notification_type='PAYMENT'
        )


# =============================================================================
# MODULE 04 — PRODUITS D'ASSURANCE MOBILE
# =============================================================================

class InsuranceProductListView(generics.ListAPIView):
    """
    GET /api/insurance/products/ — Catalogue public des formules d'assurance.
    Accessible a tous (public ou client connecte).
    """
    queryset = InsuranceProduct.objects.all()
    serializer_class = InsuranceProductSerializer
    permission_classes = (permissions.AllowAny,)


class InsuranceSubscribeView(generics.CreateAPIView):
    """
    POST /api/insurance/subscribe/ — Souscrire a une formule (CLIENT uniquement).
    """
    serializer_class = InsuranceSubscriptionSerializer
    permission_classes = (IsClient,)

    def perform_create(self, serializer):
        subscription = serializer.save(client=self.request.user, is_active=True)
        Notification.objects.create(
            user=self.request.user,
            message=(
                f"Felicitations ! Vous avez souscrit a la formule "
                f"'{subscription.product.name}'. Validite : {subscription.start_date} au {subscription.end_date}."
            ),
            notification_type='INSURANCE'
        )


class MyInsurancePoliciesView(generics.ListAPIView):
    """
    GET /api/insurance/my-policies/ — Polices actives du CLIENT connecte.
    Un client ne voit QUE ses propres polices.
    """
    serializer_class = InsuranceSubscriptionSerializer
    permission_classes = (IsClient,)

    def get_queryset(self):
        # Filtre strict : client voit uniquement ses propres polices
        return InsuranceSubscription.objects.filter(
            client=self.request.user
        ).order_by('-start_date')


# =============================================================================
# MODULE 05 — TABLEAU DE BORD ADMIN
# =============================================================================

class AdminDashboardView(APIView):
    """
    GET /api/dashboard/ — Tableau de bord complet. ADMIN UNIQUEMENT.
    Un Agent recevra 403 Forbidden s'il tente d'acceder a cet endpoint.
    Filtres: ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&agent=<id>&region=<str>
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

        total_due = installments.aggregate(total=Sum('amount_due'))['total'] or Decimal('0.00')
        total_paid = installments.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        recovery_rate = float((total_paid / total_due) * 100) if total_due > 0 else 0.0

        return Response({
            'loans_by_status': status_volumes,
            'recovery_stats': {
                'total_due': total_due,
                'total_paid': total_paid,
                'recovery_rate': round(recovery_rate, 2)
            },
            'active_subscriptions_count': subscriptions.count(),
            'open_chats_count': chats.count(),
            'filters_applied': {
                'start_date': start_date_str,
                'end_date': end_date_str,
                'agent': agent_id,
                'region': region
            }
        })


# =============================================================================
# MODULE 06 — NOTIFICATIONS INTERNES
# =============================================================================

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/notifications/ — Notifications de l'utilisateur connecte.
    Chaque utilisateur ne voit QUE ses propres notifications.
    """
    serializer_class = NotificationSerializer
    permission_classes = (permissions.IsAuthenticated,)

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
        return Response({'status': 'Toutes les notifications ont ete marquees comme lues.'})


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
        for agent in User.objects.filter(role='AGENT'):
            Notification.objects.create(
                user=agent,
                message=(
                    f"Le client {self.request.user.username} a ouvert "
                    f"une session de support chat #{conversation.id}."
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
                {'error': "Cette conversation est fermee."},
                status=status.HTTP_400_BAD_REQUEST
            )
        conversation.agent = request.user
        conversation.save()
        Notification.objects.create(
            user=conversation.client,
            message=f"L'agent {request.user.username} a rejoint votre conversation de support.",
            notification_type='SUPPORT'
        )
        return Response(ChatConversationSerializer(conversation).data)

    @action(detail=True, methods=['patch'], permission_classes=[IsAdmin], url_path='assign')
    def assign(self, request, pk=None):
        """
        PATCH /api/chat/conversations/{id}/assign/ — ADMIN uniquement.
        Assigner manuellement un agent a une conversation.
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
            message=f"L'agent {agent.username} a ete assigne a votre conversation de support.",
            notification_type='SUPPORT'
        )
        Notification.objects.create(
            user=agent,
            message=f"Vous avez ete assigne a la conversation de support de {conversation.client.username}.",
            notification_type='SUPPORT'
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

        # Securite : un client ne peut voir que ses propres conversations
        if request.user.role == 'CLIENT' and conversation.client != request.user:
            return Response(
                {'error': "Vous n'avez pas acces a cette conversation."},
                status=status.HTTP_403_FORBIDDEN
            )

        if request.method == 'POST':
            serializer = ChatMessageSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            message = serializer.save(conversation=conversation, sender=request.user)
            return Response(ChatMessageSerializer(message).data, status=status.HTTP_201_CREATED)

        msgs = conversation.messages.all()
        return Response(ChatMessageSerializer(msgs, many=True).data)
