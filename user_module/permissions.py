from rest_framework.permissions import BasePermission, SAFE_METHODS
from user_module.models import User

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.ADMIN

class IsFreelancer(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.FREELANCER

class IsClient(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.CLIENT

class IsAdminUserOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        # Allow any GET, HEAD, or OPTIONS request. These are "safe" methods
        # that do not modify the server state.
        if request.method in SAFE_METHODS:
            return True
        
        # For all other methods, only allow access if the user is an admin.
        # This checks if the user is authenticated and has the `is_staff` flag set.
        return request.user and request.user.is_authenticated and request.user.is_staff