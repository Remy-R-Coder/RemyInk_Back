from rest_framework import serializers
from .models import TaskCategory, TaskSubjectArea

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskCategory
        fields = '__all__'

class SubjectAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskSubjectArea
        fields = '__all__'
