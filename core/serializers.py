import re
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from .models import (
    LoanRequest, RepaymentInstallment, Payment,
    InsuranceProduct, InsuranceSubscription, Notification,
    ChatConversation, ChatMessage, AuditLog
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Validateurs réutilisables
# ---------------------------------------------------------------------------

PHONE_REGEX = re.compile(r'^\+?[0-9][\d\s\-\.]{6,19}$')

def validate_phone_number(value):
    """
    Valide le numéro de téléphone :
    - Commence par + ou un chiffre
    - Contient uniquement chiffres, espaces, tirets ou points
    - Entre 7 et 20 caractères au total
    Exemples valides : +225 0707070707, 0707070707, +33-6-12-34-56-78
    """
    if value and not PHONE_REGEX.match(value.strip()):
        raise serializers.ValidationError(
            "Numéro de téléphone invalide. Utilisez uniquement des chiffres, "
            "espaces, tirets ou le signe + en début (ex: +225 0707070707)."
        )
    return value.strip() if value else value


def validate_username_chars(value):
    """Le nom d'utilisateur doit contenir uniquement des lettres, chiffres, points, tirets ou underscores."""
    if not re.match(r'^[\w.@+-]+$', value):
        raise serializers.ValidationError(
            "Le nom d'utilisateur ne peut contenir que des lettres, chiffres, "
            "points (.), tirets (-) ou underscores (_)."
        )
    if len(value) < 3:
        raise serializers.ValidationError("Le nom d'utilisateur doit contenir au moins 3 caractères.")
    return value


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class UserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'region', 'phone',
                  'first_name', 'last_name', 'avatar', 'avatar_url', 'created_at')
        read_only_fields = ('id', 'role', 'created_at', 'avatar_url')
        extra_kwargs = {
            'avatar': {'write_only': False, 'required': False},
        }

    def get_avatar_url(self, obj):
        request = self.context.get('request')
        if obj.avatar:
            url = obj.avatar.url
            if request:
                return request.build_absolute_uri(url)
            return url
        return None

    def validate_phone(self, value):
        return validate_phone_number(value)

    def validate_username(self, value):
        return validate_username_chars(value)


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        min_length=8,
        style={'input_type': 'password'},
        help_text="Minimum 8 caractères avec au moins une lettre et un chiffre."
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        help_text="Répétez le mot de passe pour confirmation."
    )

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'password_confirm', 'email', 'role',
                  'region', 'phone', 'first_name', 'last_name')
        read_only_fields = ('id',)

    # --- Validations champ par champ ---

    def validate_phone(self, value):
        """Refuse les lettres dans le numéro de téléphone."""
        return validate_phone_number(value)

    def validate_username(self, value):
        """Refuse les caractères spéciaux non autorisés dans le nom d'utilisateur."""
        return validate_username_chars(value)

    def validate_password(self, value):
        """
        Mot de passe fort :
        - Minimum 8 caractères
        - Au moins une lettre (a-z ou A-Z)
        - Au moins un chiffre (0-9)
        """
        if not re.search(r'[A-Za-z]', value):
            raise serializers.ValidationError(
                "Le mot de passe doit contenir au moins une lettre (a-z ou A-Z)."
            )
        if not re.search(r'\d', value):
            raise serializers.ValidationError(
                "Le mot de passe doit contenir au moins un chiffre (0-9)."
            )
        return value

    def validate_role(self, value):
        """
        Un utilisateur ne peut pas s'auto-inscrire en tant qu'ADMIN.
        Seul un administrateur peut créer un compte ADMIN.
        """
        request = self.context.get('request')
        if value == 'ADMIN':
            if not request or not request.user.is_authenticated or request.user.role != 'ADMIN':
                raise serializers.ValidationError(
                    "Vous n'êtes pas autorisé à créer un compte Administrateur."
                )
        return value

    def validate_email(self, value):
        """Vérifie que l'email n'est pas déjà utilisé."""
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Cette adresse email est déjà associée à un compte.")
        return value.lower()

    def validate_region(self, value):
        """La région ne doit pas contenir de chiffres ou de caractères spéciaux."""
        if not re.match(r'^[\w\s\-\'éèêëàâùûüîïôœçÉÈÊËÀÂÙÛÜÎÏÔŒÇ]+$', value):
            raise serializers.ValidationError(
                "La région ne doit contenir que des lettres, espaces ou tirets."
            )
        return value

    # --- Validation croisée ---

    def validate(self, data):
        """Vérifie que les deux mots de passe correspondent."""
        password = data.get('password')
        password_confirm = data.pop('password_confirm', None)
        if password and password_confirm and password != password_confirm:
            raise serializers.ValidationError({
                'password_confirm': "Les mots de passe ne correspondent pas."
            })
        return data

    def create(self, validated_data):
        # password_confirm a déjà été retiré dans validate()
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)


class RepaymentInstallmentSerializer(serializers.ModelSerializer):
    total_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    remaining_balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = RepaymentInstallment
        fields = (
            'id', 'loan_request', 'due_date', 'amount_due', 'penalty_amount',
            'total_due', 'amount_paid', 'remaining_balance', 'is_paid'
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['total_due'] = instance.total_due
        data['remaining_balance'] = instance.remaining_balance
        return data


class LoanRequestSerializer(serializers.ModelSerializer):
    client_details = UserSerializer(source='client', read_only=True)
    installments = RepaymentInstallmentSerializer(many=True, read_only=True)

    class Meta:
        model = LoanRequest
        fields = (
            'id', 'client', 'client_details', 'amount', 'reason', 'status',
            'supporting_document', 'eligibility_score', 'eligibility_score_detail',
            'interest_rate', 'duration_weeks', 'installments', 'created_at', 'updated_at'
        )
        read_only_fields = (
            'id', 'client', 'eligibility_score', 'eligibility_score_detail',
            'interest_rate', 'duration_weeks', 'created_at', 'updated_at'
        )

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Le montant doit être strictement supérieur à 0.")
        return value


class PaymentSerializer(serializers.ModelSerializer):
    recorded_by_details = UserSerializer(source='recorded_by', read_only=True)

    class Meta:
        model = Payment
        fields = ('id', 'loan_request', 'installment', 'amount', 'paid_at', 'recorded_by', 'recorded_by_details')
        read_only_fields = ('id', 'paid_at', 'recorded_by')

    def validate(self, data):
        loan = data['loan_request']
        amount = data['amount']
        
        if amount <= 0:
            raise serializers.ValidationError("Le montant du paiement doit être supérieur à 0.")
            
        # Vérifier si le crédit est décaissé
        if loan.status != 'DECAISSEE':
            raise serializers.ValidationError("Le paiement ne peut être enregistré que pour un crédit au statut 'Décaissé'.")
            
        # Calculer le montant restant dû sur le crédit (capital + pénalités)
        total_due = sum(inst.total_due for inst in loan.installments.all())
        total_paid = sum(inst.amount_paid for inst in loan.installments.all())
        remaining = total_due - total_paid
        
        if remaining <= 0:
            raise serializers.ValidationError("Ce crédit est déjà entièrement remboursé.")
            
        if amount > remaining:
            # On accepte le paiement mais on avertit ou on limite au restant dû
            # optionnel : raise serializers.ValidationError(f"Le montant dépasse le solde restant dû ({remaining} FCFA).")
            pass
            
        return data


class InsuranceProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceProduct
        fields = ('id', 'name', 'description', 'premium_amount', 'coverage_amount', 'duration_days')


class InsuranceSubscriptionSerializer(serializers.ModelSerializer):
    client_details = UserSerializer(source='client', read_only=True)
    product_details = InsuranceProductSerializer(source='product', read_only=True)

    class Meta:
        model = InsuranceSubscription
        fields = ('id', 'client', 'client_details', 'product', 'product_details', 'start_date', 'end_date', 'is_active')
        read_only_fields = ('id', 'client', 'start_date', 'end_date', 'is_active')

    def validate(self, data):
        """Refuse une double souscription au même produit d'assurance actif."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            product = data.get('product')
            if product and InsuranceSubscription.has_active_subscription(request.user, product):
                raise serializers.ValidationError(
                    f"Vous avez déjà une souscription active pour '{product.name}'. "
                    "Attendez l'expiration avant de renouveler."
                )
        return data


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ('id', 'user', 'message', 'is_read', 'notification_type', 'created_at')
        read_only_fields = ('id', 'user', 'created_at')


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    sender_role = serializers.CharField(source='sender.role', read_only=True)

    class Meta:
        model = ChatMessage
        fields = ('id', 'conversation', 'sender', 'sender_username', 'sender_role', 'message', 'timestamp')
        read_only_fields = ('id', 'sender', 'timestamp')


class ChatConversationSerializer(serializers.ModelSerializer):
    client_details = UserSerializer(source='client', read_only=True)
    agent_details = UserSerializer(source='agent', read_only=True)
    messages = ChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = ChatConversation
        fields = ('id', 'client', 'client_details', 'agent', 'agent_details', 'status', 'messages', 'created_at')
        read_only_fields = ('id', 'client', 'agent', 'created_at')


# ---------------------------------------------------------------------------
# Serializer — Changement de mot de passe (CLIENT / toute personne connectée)
# ---------------------------------------------------------------------------

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(
        required=True, write_only=True,
        style={'input_type': 'password'},
        help_text="Votre mot de passe actuel."
    )
    new_password = serializers.CharField(
        required=True, write_only=True,
        min_length=8,
        style={'input_type': 'password'},
        help_text="Nouveau mot de passe (min. 8 caractères, 1 lettre + 1 chiffre)."
    )
    new_password_confirm = serializers.CharField(
        required=True, write_only=True,
        style={'input_type': 'password'},
        help_text="Confirmez le nouveau mot de passe."
    )

    def validate_new_password(self, value):
        if not re.search(r'[A-Za-z]', value):
            raise serializers.ValidationError("Le nouveau mot de passe doit contenir au moins une lettre.")
        if not re.search(r'\d', value):
            raise serializers.ValidationError("Le nouveau mot de passe doit contenir au moins un chiffre.")
        return value

    def validate(self, data):
        if data['new_password'] != data['new_password_confirm']:
            raise serializers.ValidationError({
                'new_password_confirm': "Les nouveaux mots de passe ne correspondent pas."
            })
        return data


# ---------------------------------------------------------------------------
# Serializer — Journal d'audit (AGENT / ADMIN)
# ---------------------------------------------------------------------------

class AuditLogSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source='actor.username', read_only=True)
    actor_role = serializers.CharField(source='actor.role', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            'id', 'actor', 'actor_username', 'actor_role',
            'action', 'action_display', 'target_model', 'target_id',
            'description', 'timestamp'
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Serializer — Gestion des utilisateurs par l'ADMIN
# ---------------------------------------------------------------------------

class UserAdminSerializer(serializers.ModelSerializer):
    """
    Serializer réservé aux administrateurs pour voir/créer/modifier des comptes.
    Expose is_active pour activer ou désactiver un compte.
    """
    password = serializers.CharField(
        write_only=True, required=False,
        min_length=8,
        style={'input_type': 'password'},
        help_text="Mot de passe initial (obligatoire à la création, ignorable en modification)."
    )
    loans_count = serializers.SerializerMethodField(read_only=True)
    active_subscriptions_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'role', 'region', 'phone',
            'first_name', 'last_name', 'is_active', 'created_at',
            'password', 'loans_count', 'active_subscriptions_count'
        )
        read_only_fields = ('id', 'created_at')

    def get_loans_count(self, obj):
        if obj.role == 'CLIENT':
            return obj.loans.count()
        return None

    def get_active_subscriptions_count(self, obj):
        if obj.role == 'CLIENT':
            return obj.subscriptions.filter(is_active=True).count()
        return None

    def validate_phone(self, value):
        return validate_phone_number(value)

    def validate_username(self, value):
        return validate_username_chars(value)

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({'password': "Le mot de passe est obligatoire lors de la création."})
        validated_data['password'] = make_password(password)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password:
            validated_data['password'] = make_password(password)
        return super().update(instance, validated_data)


# ---------------------------------------------------------------------------
# Serializer — Upload de photo de profil
# ---------------------------------------------------------------------------

class AvatarUploadSerializer(serializers.ModelSerializer):
    """
    Serializer dédié à l'upload de photo de profil.
    Validations :
      - Format accepté : JPEG ou PNG uniquement
      - Taille max : 5 Mo
    Retourne l'URL absolue de l'avatar après upload.
    """
    avatar = serializers.ImageField(
        required=True,
        allow_empty_file=False,
        help_text="Photo de profil (JPEG ou PNG, max 5 Mo)."
    )

    class Meta:
        model = User
        fields = ('avatar',)

    def validate_avatar(self, image):
        # --- Vérification du type MIME ---
        allowed_types = ['image/jpeg', 'image/png', 'image/jpg']
        if hasattr(image, 'content_type') and image.content_type not in allowed_types:
            raise serializers.ValidationError(
                "Format non supporté. Utilisez uniquement JPEG ou PNG."
            )

        # --- Vérification de l'extension ---
        import os
        ext = os.path.splitext(image.name)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png']:
            raise serializers.ValidationError(
                "Extension invalide. Seuls .jpg, .jpeg et .png sont acceptés."
            )

        # --- Vérification de la taille (max 5 Mo) ---
        max_size_mb = 5
        if image.size > max_size_mb * 1024 * 1024:
            raise serializers.ValidationError(
                f"La photo est trop volumineuse ({image.size // (1024*1024)} Mo). "
                f"Taille maximum : {max_size_mb} Mo."
            )

        return image

    def update(self, instance, validated_data):
        # Supprimer l'ancienne photo avant de sauvegarder la nouvelle
        if instance.avatar:
            import os
            if os.path.isfile(instance.avatar.path):
                os.remove(instance.avatar.path)

        instance.avatar = validated_data['avatar']
        instance.save(update_fields=['avatar'])
        return instance
