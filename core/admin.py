from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.utils import timezone

from .models import (
    User, LoanRequest, RepaymentInstallment, Payment,
    InsuranceProduct, InsuranceSubscription,
    Notification, ChatConversation, ChatMessage, AuditLog
)

# =============================================================================
# Configuration du site d'administration
# =============================================================================

admin.site.site_header = "🏦 COFINANCE CI — Administration"
admin.site.site_title = "COFINANCE CI Admin"
admin.site.index_title = "Tableau de bord administrateur"


# =============================================================================
# Inlines
# =============================================================================

class RepaymentInstallmentInline(admin.TabularInline):
    model = RepaymentInstallment
    extra = 0
    readonly_fields = ('due_date', 'amount_due', 'amount_paid', 'is_paid')
    can_delete = False
    verbose_name = "Échéance"
    verbose_name_plural = "Échéancier"


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ('paid_at', 'amount', 'recorded_by')
    can_delete = False
    verbose_name = "Paiement"
    verbose_name_plural = "Paiements enregistrés"


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ('sender', 'message', 'timestamp')
    can_delete = False
    verbose_name = "Message"
    verbose_name_plural = "Messages"


# =============================================================================
# MODULE 01 — Utilisateurs
# =============================================================================

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'username', 'full_name', 'role_badge', 'region',
        'phone', 'avatar_preview', 'is_active', 'created_at'
    )
    list_filter = ('role', 'region', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'avatar_preview_large')

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Informations COFINANCE CI', {
            'fields': ('role', 'region', 'phone', 'avatar', 'avatar_preview_large', 'created_at')
        }),
    )

    def full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or "—"
    full_name.short_description = "Nom complet"

    def role_badge(self, obj):
        colors = {'CLIENT': '#2196F3', 'AGENT': '#FF9800', 'ADMIN': '#F44336'}
        color = colors.get(obj.role, '#9E9E9E')
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;'
            'border-radius:12px;font-size:11px;font-weight:bold;">{}</span>',
            color, obj.get_role_display()
        )
    role_badge.short_description = "Rôle"

    def avatar_preview(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" width="36" height="36" '
                'style="border-radius:50%;object-fit:cover;border:2px solid #ddd;" />',
                obj.avatar.url
            )
        return format_html('<span style="color:#999;">—</span>')
    avatar_preview.short_description = "Photo"

    def avatar_preview_large(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" width="120" height="120" '
                'style="border-radius:8px;object-fit:cover;border:2px solid #ddd;" />',
                obj.avatar.url
            )
        return "Aucun avatar"
    avatar_preview_large.short_description = "Aperçu de l'avatar"


# =============================================================================
# MODULE 02 — Crédits
# =============================================================================

@admin.register(LoanRequest)
class LoanRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'client_link', 'amount_formatted', 'status_badge',
        'eligibility_score_bar', 'created_at'
    )
    list_filter = ('status', 'client__region', 'created_at')
    search_fields = ('client__username', 'client__email', 'reason')
    readonly_fields = (
        'eligibility_score', 'eligibility_score_detail',
        'created_at', 'updated_at'
    )
    ordering = ('-created_at',)
    inlines = [RepaymentInstallmentInline, PaymentInline]
    date_hierarchy = 'created_at'

    def client_link(self, obj):
        return format_html(
            '<a href="/admin/core/user/{}/change/">{}</a>',
            obj.client.id, obj.client.username
        )
    client_link.short_description = "Client"

    def amount_formatted(self, obj):
        return format_html('<strong>{:,.0f} FCFA</strong>', obj.amount)
    amount_formatted.short_description = "Montant"

    def status_badge(self, obj):
        colors = {
            'SOUMISE': '#9E9E9E',
            'EN_ANALYSE': '#2196F3',
            'APPROUVEE': '#4CAF50',
            'DECAISSEE': '#FF9800',
        }
        color = colors.get(obj.status, '#9E9E9E')
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;'
            'border-radius:12px;font-size:11px;font-weight:bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Statut"

    def eligibility_score_bar(self, obj):
        score = obj.eligibility_score
        color = '#4CAF50' if score >= 70 else ('#FF9800' if score >= 40 else '#F44336')
        return format_html(
            '<div style="width:100px;background:#eee;border-radius:4px;overflow:hidden;">'
            '<div style="width:{}px;background:{};height:12px;border-radius:4px;"></div>'
            '</div> <small>{}/100</small>',
            score, color, score
        )
    eligibility_score_bar.short_description = "Score"


# =============================================================================
# MODULE 03 — Remboursements
# =============================================================================

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'loan_client', 'amount_formatted', 'recorded_by', 'paid_at')
    list_filter = ('paid_at', 'recorded_by')
    search_fields = ('loan_request__client__username', 'recorded_by__username')
    readonly_fields = ('paid_at',)
    ordering = ('-paid_at',)

    def loan_client(self, obj):
        return obj.loan_request.client.username
    loan_client.short_description = "Client"

    def amount_formatted(self, obj):
        return format_html('<strong>{:,.0f} FCFA</strong>', obj.amount)
    amount_formatted.short_description = "Montant"


# =============================================================================
# MODULE 04 — Assurances
# =============================================================================

@admin.register(InsuranceProduct)
class InsuranceProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'premium_formatted', 'coverage_formatted', 'duration_days')
    search_fields = ('name', 'description')

    def premium_formatted(self, obj):
        return f"{obj.premium_amount:,.0f} FCFA"
    premium_formatted.short_description = "Prime"

    def coverage_formatted(self, obj):
        return f"{obj.coverage_amount:,.0f} FCFA"
    coverage_formatted.short_description = "Couverture"


@admin.register(InsuranceSubscription)
class InsuranceSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'product', 'start_date', 'end_date', 'status_badge')
    list_filter = ('is_active', 'product')
    search_fields = ('client__username', 'product__name')
    readonly_fields = ('start_date', 'end_date')

    def status_badge(self, obj):
        today = timezone.localdate()
        if not obj.is_active or (obj.end_date and obj.end_date < today):
            return format_html(
                '<span style="background:#F44336;color:white;padding:2px 8px;'
                'border-radius:12px;font-size:11px;">Expirée</span>'
            )
        return format_html(
            '<span style="background:#4CAF50;color:white;padding:2px 8px;'
            'border-radius:12px;font-size:11px;">Active</span>'
        )
    status_badge.short_description = "Statut"


# =============================================================================
# MODULE 06 — Notifications
# =============================================================================

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'notification_type', 'is_read', 'short_message', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('user__username', 'message')
    ordering = ('-created_at',)

    def short_message(self, obj):
        return obj.message[:60] + "..." if len(obj.message) > 60 else obj.message
    short_message.short_description = "Message"


# =============================================================================
# MODULE 07 — Chat
# =============================================================================

@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'agent', 'status_badge', 'messages_count', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('client__username', 'agent__username')
    readonly_fields = ('created_at',)
    inlines = [ChatMessageInline]

    def status_badge(self, obj):
        color = '#4CAF50' if obj.status == 'OPEN' else '#9E9E9E'
        label = "Ouverte" if obj.status == 'OPEN' else "Fermée"
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;'
            'border-radius:12px;font-size:11px;">{}</span>',
            color, label
        )
    status_badge.short_description = "Statut"

    def messages_count(self, obj):
        count = obj.messages.count()
        return format_html('<span style="font-weight:bold;">{}</span>', count)
    messages_count.short_description = "Messages"


# =============================================================================
# JOURNAL D'AUDIT — Lecture seule (intégrité absolue)
# =============================================================================

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        'timestamp', 'actor_link', 'action_badge',
        'target_model', 'target_id', 'short_description'
    )
    list_filter = ('action', 'target_model', 'timestamp')
    search_fields = ('actor__username', 'description', 'target_model')
    ordering = ('-timestamp',)
    date_hierarchy = 'timestamp'

    # Lecture seule totale — le journal d'audit ne doit JAMAIS être modifié
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def actor_link(self, obj):
        if obj.actor:
            return format_html(
                '<a href="/admin/core/user/{}/change/">{}</a>',
                obj.actor.id, obj.actor.username
            )
        return "Système"
    actor_link.short_description = "Acteur"

    def action_badge(self, obj):
        colors = {
            'CREDIT_STATUS_CHANGE': '#2196F3',
            'PAYMENT_RECORDED': '#4CAF50',
            'CHAT_JOINED': '#FF9800',
            'CHAT_ASSIGNED': '#9C27B0',
            'USER_TOGGLED': '#F44336',
            'USER_CREATED': '#009688',
        }
        color = colors.get(obj.action, '#9E9E9E')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;'
            'border-radius:12px;font-size:10px;font-weight:bold;">{}</span>',
            color, obj.get_action_display()
        )
    action_badge.short_description = "Action"

    def short_description(self, obj):
        return obj.description[:80] + "..." if len(obj.description) > 80 else obj.description
    short_description.short_description = "Description"
