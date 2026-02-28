import uuid
from django.db import models
from django.utils.text import slugify
from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, generics
from rest_framework.response import Response
from rest_framework import status
from .models import TaskCategory, TaskSubjectArea
from .serializers import CategorySerializer, SubjectAreaSerializer
from user_module.permissions import IsAdminUserOrReadOnly

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = TaskCategory.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminUserOrReadOnly]

class SubjectAreaViewSet(viewsets.ModelViewSet):
    serializer_class = SubjectAreaSerializer
    permission_classes = [IsAdminUserOrReadOnly]

    def get_queryset(self):
        queryset = TaskSubjectArea.objects.all()
        category_id = self.request.query_params.get('category_id')
        
        if category_id is not None:
            return queryset.filter(category_id=category_id)
        
        return queryset
        
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)