from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from decimal import Decimal


class User(AbstractUser):
    ROLE_CHOICES = (
        ('CLIENT', 'Client'),
        ('AGENT', 'Agent'),
        ('ADMIN', 'Administrateur'),
    )

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='CLIENT')
    region = models.CharField(max_length=100, default='Abidjan')
    phone = models.CharField(max_length=20, blank=True, null=True)
    avatar = models.ImageField(
        upload_to='avatars/',
        null=True,
        blank=True,
        help_text="Photo de profil de l'utilisateur (JPEG/PNG, max 5 Mo recommandé)."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    @property
    def avatar_url(self):
        """Retourne l'URL de l'avatar ou None si aucun avatar."""
        if self.avatar:
            return self.avatar.url
        return None



class LoanRequest(models.Model):
    STATUS_CHOICES = (
        ('SOUMISE', 'Soumise'),
        ('EN_ANALYSE', 'En analyse'),
        ('APPROUVEE', 'Approuvée'),
        ('DECAISSEE', 'Décaissée'),
    )

    # Workflow strictement unidirectionnel — chaque statut ne peut avancer que vers le suivant
    WORKFLOW_ORDER = {
        'SOUMISE': 0,
        'EN_ANALYSE': 1,
        'APPROUVEE': 2,
        'DECAISSEE': 3,
    }

    # Statuts considérés comme « actifs » (bloquent une nouvelle demande)
    ACTIVE_STATUSES = ('SOUMISE', 'EN_ANALYSE', 'APPROUVEE')

    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loans', limit_choices_to={'role': 'CLIENT'})
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SOUMISE')
    supporting_document = models.FileField(upload_to='supporting_documents/', blank=True, null=True)
    eligibility_score = models.IntegerField(default=50)
    eligibility_score_detail = models.TextField(blank=True, default='')  # Explication lisible du score
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'))  # 10% par défaut
    duration_weeks = models.IntegerField(default=8)  # 8 semaines par défaut (2 mois)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def calculate_eligibility_score(self):
        """
        Calcule un score d'éligibilité simplifié basé sur :
        - Score de base : 50 points
        - Prêts actifs (APPROUVEE/DECAISSEE non remboursés) : -15 par prêt
        - Prêts antérieurs entièrement remboursés : +15 par prêt
        - Montant demandé < 100 000 FCFA : +15 | > 1 000 000 FCFA : -15
        Retourne (score, detail_text)
        """
        score = 50
        details = ["Score de base : 50 pts"]

        past_loans = LoanRequest.objects.filter(client=self.client).exclude(id=self.id)
        active_loans = past_loans.filter(status__in=['APPROUVEE', 'DECAISSEE'])
        active_count = active_loans.count()

        if active_count > 0:
            score -= active_count * 15
            details.append(f"{active_count} crédit(s) actif(s) non remboursé(s) : -{active_count * 15} pts")

        completed_loans = past_loans.filter(status='DECAISSEE')
        repaid_count = 0
        for loan in completed_loans:
            if not loan.installments.filter(is_paid=False).exists() and loan.installments.exists():
                score += 15
                repaid_count += 1
        if repaid_count > 0:
            details.append(f"{repaid_count} crédit(s) entièrement remboursé(s) : +{repaid_count * 15} pts")

        if self.amount < Decimal('100000'):
            score += 15
            details.append("Montant < 100 000 FCFA : +15 pts")
        elif self.amount > Decimal('1000000'):
            score -= 15
            details.append("Montant > 1 000 000 FCFA : -15 pts")

        final_score = max(0, min(100, score))
        detail_text = " | ".join(details) + f" → Total : {final_score}/100"
        return final_score, detail_text

    def generate_schedule(self):
        """
        Génère automatiquement l'échéancier de remboursement.
        Divise le montant total (capital + intérêt) en 4 échéances régulières.
        """
        # Supprimer l'échéancier précédent s'il existe
        self.installments.all().delete()
        
        interest_amount = self.amount * (self.interest_rate / Decimal('100.00'))
        total_payable = self.amount + interest_amount
        
        num_installments = 4
        amount_per_installment = (total_payable / Decimal(num_installments)).quantize(Decimal('0.01'))
        
        start_date = timezone.localdate()
        for i in range(1, num_installments + 1):
            # Échéance toutes les 2 semaines
            due_date = start_date + timezone.timedelta(weeks=i * 2)
            RepaymentInstallment.objects.create(
                loan_request=self,
                due_date=due_date,
                amount_due=amount_per_installment,
                amount_paid=Decimal('0.00'),
                is_paid=False
            )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            score, detail = self.calculate_eligibility_score()
            self.eligibility_score = score
            self.eligibility_score_detail = detail
            super().save(update_fields=['eligibility_score', 'eligibility_score_detail'])

    def __str__(self):
        return f"Crédit #{self.id} - {self.client.username} - {self.amount} FCFA ({self.get_status_display()})"


class RepaymentInstallment(models.Model):
    loan_request = models.ForeignKey(LoanRequest, on_delete=models.CASCADE, related_name='installments')
    due_date = models.DateField()
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    penalty_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        help_text="Pénalités de retard accumulées (1 % par jour sur le solde impayé)."
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_paid = models.BooleanField(default=False)

    class Meta:
        ordering = ['due_date']

    @property
    def total_due(self):
        """Montant total dû incluant les pénalités de retard."""
        return self.amount_due + self.penalty_amount

    @property
    def remaining_balance(self):
        """Solde restant à payer sur cette échéance."""
        return max(Decimal('0.00'), self.total_due - self.amount_paid)

    def __str__(self):
        return f"Échéance du {self.due_date} ({self.amount_paid}/{self.total_due} FCFA)"


class Payment(models.Model):
    loan_request = models.ForeignKey(LoanRequest, on_delete=models.CASCADE, related_name='payments')
    installment = models.ForeignKey(RepaymentInstallment, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'role__in': ['AGENT', 'ADMIN']})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Assigner à l'échéance non payée la plus ancienne
        self.apply_payment_to_installments()

    def apply_payment_to_installments(self):
        """
        Répartit le paiement sur les échéances non payées du crédit.
        """
        remaining_payment = self.amount
        installments = self.loan_request.installments.filter(is_paid=False).order_by('due_date')
        
        for inst in installments:
            if remaining_payment <= 0:
                break
                
            needed = inst.remaining_balance
            if remaining_payment >= needed:
                inst.amount_paid = inst.total_due
                inst.is_paid = True
                remaining_payment -= needed
            else:
                inst.amount_paid += remaining_payment
                remaining_payment = Decimal('0.00')
            inst.save()

    def __str__(self):
        return f"Paiement #{self.id} - {self.amount} FCFA par {self.recorded_by.username}"


class InsuranceProduct(models.Model):
    name = models.CharField(max_length=150)
    description = models.TextField()
    premium_amount = models.DecimalField(max_digits=12, decimal_places=2)
    coverage_amount = models.DecimalField(max_digits=12, decimal_places=2)
    duration_days = models.IntegerField(default=30)

    def __str__(self):
        return f"{self.name} - {self.premium_amount} FCFA"


class InsuranceSubscription(models.Model):
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions', limit_choices_to={'role': 'CLIENT'})
    product = models.ForeignKey(InsuranceProduct, on_delete=models.CASCADE)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    @classmethod
    def has_active_subscription(cls, client, product):
        """Vérifie si le client a déjà une souscription active pour ce produit."""
        return cls.objects.filter(
            client=client,
            product=product,
            is_active=True,
            end_date__gte=timezone.localdate()
        ).exists()

    def save(self, *args, **kwargs):
        if not self.end_date:
            self.end_date = self.start_date + timezone.timedelta(days=self.product.duration_days)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Souscription #{self.id} - {self.client.username} - {self.product.name}"


class Notification(models.Model):
    TYPE_CHOICES = (
        ('CREDIT_STATUS', 'Changement de statut de crédit'),
        ('PAYMENT', 'Enregistrement de remboursement'),
        ('INSURANCE', 'Souscription assurance'),
        ('SUPPORT', 'Support client'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification pour {self.user.username} - {self.get_notification_type_display()}"


class ChatConversation(models.Model):
    STATUS_CHOICES = (
        ('OPEN', 'Ouverte'),
        ('CLOSED', 'Fermée'),
    )
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='client_conversations', limit_choices_to={'role': 'CLIENT'})
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='agent_conversations', limit_choices_to={'role': 'AGENT'})
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        agent_name = self.agent.username if self.agent else "Aucun"
        return f"Chat #{self.id} (Client: {self.client.username}, Agent: {agent_name}, Statut: {self.status})"


class ChatMessage(models.Model):
    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Message #{self.id} par {self.sender.username} dans Chat #{self.conversation.id}"


# =============================================================================
# JOURNAL D'AUDIT — Traçabilité complète des actions agents/admins
# =============================================================================

class AuditLog(models.Model):
    ACTION_CHOICES = (
        ('CREDIT_STATUS_CHANGE', 'Changement de statut de crédit'),
        ('PAYMENT_RECORDED', 'Paiement enregistré'),
        ('CHAT_JOINED', 'Conversation rejointe'),
        ('CHAT_ASSIGNED', 'Conversation assignée'),
        ('USER_TOGGLED', 'Compte utilisateur activé/désactivé'),
        ('USER_CREATED', 'Utilisateur créé par admin'),
    )

    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='audit_logs',
        help_text="L'agent ou l'admin qui a effectué l'action."
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    target_model = models.CharField(max_length=50, blank=True, help_text="Modèle concerné (ex: LoanRequest, Payment).")
    target_id = models.PositiveIntegerField(null=True, blank=True, help_text="ID de l'objet concerné.")
    description = models.TextField(help_text="Description lisible de l'action effectuée.")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        actor_name = self.actor.username if self.actor else "Système"
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {actor_name} — {self.get_action_display()}"
