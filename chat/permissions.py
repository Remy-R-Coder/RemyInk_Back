from rest_framework.permissions import BasePermission
from .services import ChatThreadService


class IsThreadParticipant(BasePermission):
    
    def has_permission(self, request, view):
        thread_id = (
            view.kwargs.get("thread_pk")
            or view.kwargs.get("thread_id")
            or view.kwargs.get("pk")
        )
        if not thread_id:
            return True

        thread = ChatThreadService.get_thread_by_id(int(thread_id))
        if not thread:
            return False

        user = getattr(request, "user", None)
        session_key = (
            getattr(request.session, "session_key", None)
            or request.query_params.get("session_key")
        )

        return ChatThreadService.is_user_participant(thread, user, session_key)