from rest_framework.permissions import BasePermission


class IsClient(BasePermission):
    """
    Autorise uniquement les utilisateurs authentifies avec le role CLIENT.
    Un client ne peut voir QUE ses propres donnees.
    """
    message = "Acces reserve aux clients uniquement."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'CLIENT'
        )


class IsAgent(BasePermission):
    """
    Autorise les AGENT et les ADMIN (les agents ont les memes droits que les admins
    sauf pour le dashboard admin).
    """
    message = "Acces reserve aux agents et administrateurs."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in ['AGENT', 'ADMIN']
        )


class IsAdmin(BasePermission):
    """
    Autorise UNIQUEMENT les ADMIN. Les agents ne peuvent pas acceder au dashboard admin.
    """
    message = "Acces reserve aux administrateurs uniquement. Permission refusee (403)."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'ADMIN'
        )


class IsClientOrAgent(BasePermission):
    """
    Autorise les CLIENT, AGENT et ADMIN.
    Utile pour les endpoints accessibles a tous les utilisateurs authentifies.
    """
    message = "Vous devez etre authentifie pour acceder a cette ressource."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in ['CLIENT', 'AGENT', 'ADMIN']
        )
