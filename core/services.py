"""
Services métier partagés — assignation chat, pénalités de retard.
"""
from decimal import Decimal

from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import RepaymentInstallment

User = get_user_model()

PENALTY_RATE_PER_DAY = Decimal('0.01')  # 1 % par jour sur le solde impayé


def get_available_agent():
    """
    Retourne l'agent actif ayant le moins de conversations ouvertes.
    Utilisé pour l'assignation automatique des chats de support.
    """
    return (
        User.objects.filter(role='AGENT', is_active=True)
        .annotate(open_chats=Count('agent_conversations', filter=Q(agent_conversations__status='OPEN')))
        .order_by('open_chats', 'id')
        .first()
    )


def assign_agent_to_conversation(conversation):
    """Assigne automatiquement un agent disponible à une conversation."""
    if conversation.agent_id:
        return conversation.agent
    agent = get_available_agent()
    if agent:
        conversation.agent = agent
        conversation.save(update_fields=['agent'])
    return agent


def calculate_late_penalty(installment, reference_date=None):
    """Calcule la pénalité de retard pour une échéance impayée."""
    today = reference_date or timezone.localdate()
    if installment.is_paid or installment.due_date >= today:
        return Decimal('0.00')
    days_late = (today - installment.due_date).days
    remaining_unpaid = installment.amount_due - installment.amount_paid
    if remaining_unpaid <= 0:
        return Decimal('0.00')
    return (remaining_unpaid * PENALTY_RATE_PER_DAY * Decimal(days_late)).quantize(Decimal('0.01'))


def apply_late_penalties(reference_date=None):
    """
    Applique les pénalités de retard sur toutes les échéances en souffrance.
    Retourne le nombre d'échéances mises à jour.
    """
    today = reference_date or timezone.localdate()
    updated = 0
    overdue = RepaymentInstallment.objects.filter(due_date__lt=today, is_paid=False)
    for inst in overdue:
        penalty = calculate_late_penalty(inst, today)
        if inst.penalty_amount != penalty:
            inst.penalty_amount = penalty
            inst.save(update_fields=['penalty_amount'])
            updated += 1
    return updated
