from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import RepaymentInstallment, InsuranceSubscription, Notification
from core.services import apply_late_penalties


class Command(BaseCommand):
    help = 'Exécute les alertes quotidiennes : échéances (J-3, J+1), pénalités et assurances (J-15).'

    def handle(self, *args, **options):
        today = timezone.localdate()
        self.stdout.write(f"Exécution des alertes quotidiennes pour le {today}...")

        # 1. Échéance dans 3 jours (J-3)
        target_j3 = today + timezone.timedelta(days=3)
        upcoming_installments = RepaymentInstallment.objects.filter(
            due_date=target_j3,
            is_paid=False
        )

        for inst in upcoming_installments:
            client = inst.loan_request.client
            message = (
                f"Rappel : votre échéance de {inst.total_due} FCFA est prévue dans 3 jours "
                f"(le {inst.due_date}) pour le crédit #{inst.loan_request.id}."
            )
            if not Notification.objects.filter(user=client, message=message).exists():
                Notification.objects.create(
                    user=client,
                    message=message,
                    notification_type='CREDIT_STATUS'
                )
                self.stdout.write(f"Alerte J-3 créée pour le client : {client.username}")

        # 2. Échéance en retard d'un jour (J+1)
        target_j_plus1 = today - timezone.timedelta(days=1)
        overdue_j_plus1 = RepaymentInstallment.objects.filter(
            due_date=target_j_plus1,
            is_paid=False
        )

        for inst in overdue_j_plus1:
            client = inst.loan_request.client
            message = (
                f"Alerte : votre échéance de {inst.total_due} FCFA du {inst.due_date} "
                f"est en retard d'un jour. Veuillez effectuer le remboursement dès que possible."
            )
            if not Notification.objects.filter(user=client, message=message).exists():
                Notification.objects.create(
                    user=client,
                    message=message,
                    notification_type='CREDIT_STATUS'
                )
                self.stdout.write(f"Alerte J+1 créée pour le client : {client.username}")

        # 3. Appliquer les pénalités de retard en base de données
        penalty_updates = apply_late_penalties(today)
        self.stdout.write(f"Pénalités mises à jour sur {penalty_updates} échéance(s).")

        overdue_all = RepaymentInstallment.objects.filter(
            due_date__lt=today,
            is_paid=False
        )

        for inst in overdue_all:
            client = inst.loan_request.client
            penalty = inst.penalty_amount
            if penalty <= 0:
                continue
            days_late = (today - inst.due_date).days
            message = (
                f"Pénalités appliquées : votre échéance du {inst.due_date} a accumulé "
                f"{penalty} FCFA de pénalités de retard ({days_late} jour(s) de retard). "
                f"Montant total dû : {inst.total_due} FCFA."
            )
            if not Notification.objects.filter(user=client, message=message).exists():
                Notification.objects.create(
                    user=client,
                    message=message,
                    notification_type='PAYMENT'
                )
                self.stdout.write(
                    f"Notification de pénalité ({penalty} FCFA) pour le client : {client.username}"
                )

        # 4. Expiration assurance dans 15 jours (J-15)
        target_j15 = today + timezone.timedelta(days=15)
        expiring_subscriptions = InsuranceSubscription.objects.filter(
            end_date=target_j15,
            is_active=True
        )

        for sub in expiring_subscriptions:
            client = sub.client
            message = (
                f"Attention : votre contrat d'assurance '{sub.product.name}' "
                f"(souscription #{sub.id}) expire dans 15 jours (le {sub.end_date}). "
                f"Pensez à renouveler."
            )
            if not Notification.objects.filter(user=client, message=message).exists():
                Notification.objects.create(
                    user=client,
                    message=message,
                    notification_type='INSURANCE'
                )
                self.stdout.write(f"Alerte J-15 assurance pour le client : {client.username}")

        self.stdout.write(self.style.SUCCESS("Traitement des alertes quotidiennes terminé."))
