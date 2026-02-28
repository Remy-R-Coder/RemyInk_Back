from rest_framework import permissions

class IsClient(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'CLIENT'


class IsFreelancerOrClient(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.freelancer == request.user or obj.client == request.user
