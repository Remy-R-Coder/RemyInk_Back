import uuid
from django.db import models
from django.utils.text import slugify
from django.conf import settings
from django.utils import timezone

class TaskCategory(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        blank=False,
        help_text="Unique name of the category (e.g., Computing and IT)."
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
        editable=False,
        help_text="Auto-generated slug from name, used for URLs and lookups."
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of this category."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "TaskCategory"
        verbose_name_plural = "Task Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<Task Category id='{self.id}' name='{self.name}'>"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class TaskSubjectArea(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    name = models.CharField(
        max_length=100,
        db_index=True,
        blank=False,
        help_text="Name of the subject area (e.g., Data Analytics)."
    )
    slug = models.SlugField(
        max_length=120,
        blank=True,
        editable=False,
        help_text="Auto-generated slug from name."
    )
    category = models.ForeignKey(
        TaskCategory,
        on_delete=models.CASCADE,
        related_name="subject_areas",
        help_text="The parent category this subject area belongs to."
    )
    description = models.TextField(
        blank=True,
        help_text="Description of this subject area (Optional)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "category"],
                name="unique_subject_per_category"
            ),
            models.UniqueConstraint(
                fields=["slug", "category"],
                name="unique_slug_per_category"
            )
        ]
        ordering = ["category__name", "name"]
        verbose_name = "Task Subject Area"
        verbose_name_plural = "Task Subject Areas"

    def __str__(self):
        return f"{self.name} ({self.category.name})"

    def __repr__(self):
        return f"<Task SubjectArea id='{self.id}' name='{self.name}' category='{self.category.name}'>"

    def save(self, *args, **kwargs):
        if not self.slug or self._state.adding:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)