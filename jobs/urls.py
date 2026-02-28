from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, SubjectAreaViewSet

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'subject-areas', SubjectAreaViewSet, basename='subjectarea')

urlpatterns = [
    path('', include(router.urls)),
]