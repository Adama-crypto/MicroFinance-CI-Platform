from rest_framework.permissions import BasePermission


class IsClient(BasePermission):
    """
    Autorise uniquement les utilisateurs authentifiés avec le rôle CLIENT.
    Un client ne peut voir QUE ses propres données.
    """
    message = "Accès réservé aux clients uniquement."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'CLIENT'
        )


class IsAgent(BasePermission):
    """
    Autorise les AGENT et les ADMIN (les agents ont les mêmes droits que les admins
    sauf pour le dashboard admin).
    """
    message = "Accès réservé aux agents et administrateurs."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in ['AGENT', 'ADMIN']
        )


class IsAdmin(BasePermission):
    """
    Autorise UNIQUEMENT les ADMIN. Les agents ne peuvent pas accéder au dashboard admin.
    """
    message = "Accès réservé aux administrateurs uniquement. Permission refusée (403)."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'ADMIN'
        )


class IsClientOrAgent(BasePermission):
    """
    Autorise les CLIENT, AGENT et ADMIN.
    Utile pour les endpoints accessibles à tous les utilisateurs authentifiés.
    """
    message = "Vous devez être authentifié pour accéder à cette ressource."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in ['CLIENT', 'AGENT', 'ADMIN']
        )
