from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from .models import (
    LoanRequest, RepaymentInstallment, Payment,
    InsuranceProduct, InsuranceSubscription, Notification,
    ChatConversation, ChatMessage
)

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'region', 'phone', 'first_name', 'last_name', 'created_at')
        read_only_fields = ('id', 'role', 'created_at')


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'email', 'role', 'region', 'phone', 'first_name', 'last_name')
        read_only_fields = ('id',)

    def create(self, validated_data):
        # Hash user password
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)


class RepaymentInstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepaymentInstallment
        fields = ('id', 'loan_request', 'due_date', 'amount_due', 'amount_paid', 'is_paid')


class LoanRequestSerializer(serializers.ModelSerializer):
    client_details = UserSerializer(source='client', read_only=True)
    installments = RepaymentInstallmentSerializer(many=True, read_only=True)

    class Meta:
        model = LoanRequest
        fields = ('id', 'client', 'client_details', 'amount', 'reason', 'status', 
                  'supporting_document', 'eligibility_score', 'interest_rate', 
                  'duration_weeks', 'installments', 'created_at', 'updated_at')
        read_only_fields = ('id', 'client', 'eligibility_score', 'interest_rate', 'duration_weeks', 'created_at', 'updated_at')

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
            
        # Calculer le montant restant dû sur le crédit
        total_due = sum(inst.amount_due for inst in loan.installments.all())
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
