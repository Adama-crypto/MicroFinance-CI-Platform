from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from core.models import RepaymentInstallment, InsuranceSubscription, Notification


class Command(BaseCommand):
    help = 'Runs daily checks for repayments and insurance expirations, creating notifications.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        self.stdout.write(f"Running daily alerts for {today}...")

        # 1. Repayment due in 3 days (J-3)
        target_j3 = today + timezone.timedelta(days=3)
        upcoming_installments = RepaymentInstallment.objects.filter(
            due_date=target_j3,
            is_paid=False
        )
        
        for inst in upcoming_installments:
            client = inst.loan_request.client
            message = f"Rappel: Votre échéance de {inst.amount_due} FCFA est prévue dans 3 jours (le {inst.due_date}) pour le crédit #{inst.loan_request.id}."
            
            # Check if notification already exists to avoid duplication
            if not Notification.objects.filter(user=client, message=message).exists():
                Notification.objects.create(
                    user=client,
                    message=message,
                    notification_type='CREDIT_STATUS'
                )
                self.stdout.write(f"Created J-3 alert for client: {client.username}")

        # 2. Repayment overdue by 1 day (J+1)
        target_j_plus1 = today - timezone.timedelta(days=1)
        overdue_j_plus1 = RepaymentInstallment.objects.filter(
            due_date=target_j_plus1,
            is_paid=False
        )
        
        for inst in overdue_j_plus1:
            client = inst.loan_request.client
            message = f"Alerte: Votre échéance de {inst.amount_due} FCFA du {inst.due_date} est en retard d'un jour. Veuillez effectuer le remboursement dès que possible."
            
            if not Notification.objects.filter(user=client, message=message).exists():
                Notification.objects.create(
                    user=client,
                    message=message,
                    notification_type='CREDIT_STATUS'
                )
                self.stdout.write(f"Created J+1 alert for client: {client.username}")

        # 3. Calculate delay penalties for all overdue installments (due_date < today)
        overdue_all = RepaymentInstallment.objects.filter(
            due_date__lt=today,
            is_paid=False
        )
        
        for inst in overdue_all:
            client = inst.loan_request.client
            days_late = (today - inst.due_date).days
            
            # 1% penalty per day on the remaining unpaid due amount
            remaining_unpaid = inst.amount_due - inst.amount_paid
            penalty_rate = Decimal('0.01')  # 1%
            penalty = (remaining_unpaid * penalty_rate * Decimal(days_late)).quantize(Decimal('0.01'))
            
            if penalty > 0:
                message = f"Pénalités appliquées: Votre échéance du {inst.due_date} a accumulé {penalty} FCFA d'intérêts de pénalité de retard ({days_late} jours de retard)."
                if not Notification.objects.filter(user=client, message=message).exists():
                    Notification.objects.create(
                        user=client,
                        message=message,
                        notification_type='PAYMENT'
                    )
                    self.stdout.write(f"Created late penalty alert of {penalty} FCFA for client: {client.username}")

        # 4. Insurance subscription expiration warning in 15 days (J-15)
        target_j15 = today + timezone.timedelta(days=15)
        expiring_subscriptions = InsuranceSubscription.objects.filter(
            end_date=target_j15,
            is_active=True
        )
        
        for sub in expiring_subscriptions:
            client = sub.client
            message = f"Attention: Votre contrat d'assurance '{sub.product.name}' (Souscription #{sub.id}) expire dans 15 jours (le {sub.end_date}). Pensez à renouveler."
            
            if not Notification.objects.filter(user=client, message=message).exists():
                Notification.objects.create(
                    user=client,
                    message=message,
                    notification_type='INSURANCE'
                )
                self.stdout.write(f"Created J-15 insurance warning for client: {client.username}")

        self.stdout.write(self.style.SUCCESS("Daily alerts processing completed."))
