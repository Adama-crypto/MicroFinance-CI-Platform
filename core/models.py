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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class LoanRequest(models.Model):
    STATUS_CHOICES = (
        ('SOUMISE', 'Soumise'),
        ('EN_ANALYSE', 'En analyse'),
        ('APPROUVEE', 'Approuvée'),
        ('DECAISSEE', 'Décaissée'),
    )
    
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='loans', limit_choices_to={'role': 'CLIENT'})
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SOUMISE')
    supporting_document = models.FileField(upload_to='supporting_documents/', blank=True, null=True)
    eligibility_score = models.IntegerField(default=50)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'))  # 10% par défaut
    duration_weeks = models.IntegerField(default=8)  # 8 semaines par défaut (2 mois)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def calculate_eligibility_score(self):
        """
        Calcule un score d'éligibilité simplifié basé sur :
        - Historique de remboursement des anciens prêts (+10 par prêt payé)
        - Prêts en cours non payés (-15 par prêt actif)
        - Montant demandé par rapport à une limite
        """
        score = 50  # Score de base
        
        # Historique
        past_loans = LoanRequest.objects.filter(client=self.client).exclude(id=self.id)
        active_loans_count = past_loans.filter(status__in=['APPROUVEE', 'DECAISSEE']).count()
        
        score -= active_loans_count * 15
        
        # Prêts terminés
        completed_loans = past_loans.filter(status='DECAISSEE')
        for loan in completed_loans:
            # Si toutes les échéances sont payées
            if not loan.installments.filter(is_paid=False).exists() and loan.installments.exists():
                score += 15
                
        # Montant demandé impact
        if self.amount < Decimal('100000'):
            score += 15
        elif self.amount > Decimal('1000000'):
            score -= 15
            
        # Limiter entre 0 et 100
        return max(0, min(100, score))

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
        if is_new:
            # Premier calcul du score
            pass
        super().save(*args, **kwargs)
        
        # Mettre à jour le score d'éligibilité si nécessaire
        if is_new:
            self.eligibility_score = self.calculate_eligibility_score()
            super().save(update_fields=['eligibility_score'])

    def __str__(self):
        return f"Crédit #{self.id} - {self.client.username} - {self.amount} FCFA ({self.get_status_display()})"


class RepaymentInstallment(models.Model):
    loan_request = models.ForeignKey(LoanRequest, on_delete=models.CASCADE, related_name='installments')
    due_date = models.DateField()
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_paid = models.BooleanField(default=False)

    class Meta:
        ordering = ['due_date']

    def __str__(self):
        return f"Échéance du {self.due_date} ({self.amount_paid}/{self.amount_due} FCFA)"


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
                
            needed = inst.amount_due - inst.amount_paid
            if remaining_payment >= needed:
                inst.amount_paid = inst.amount_due
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
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

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
