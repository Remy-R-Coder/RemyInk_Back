from django.contrib import admin
from .models import TaskCategory, TaskSubjectArea

@admin.register(TaskCategory)
class TaskCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description_snippet', 'created_at')
    search_fields = ('name', 'description')
    ordering = ('name',)
    list_per_page = 25

    def description_snippet(self, obj):
        return (obj.description[:75] + "...") if obj.description and len(obj.description) > 75 else obj.description
    description_snippet.short_description = 'Description'


@admin.register(TaskSubjectArea)
class SubjectAreaAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'created_at')
    search_fields = ('name', 'category__name')
    list_filter = ('category',)
    ordering = ('category', 'name')
    list_per_page = 25