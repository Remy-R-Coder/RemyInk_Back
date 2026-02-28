import uuid
from django.db import models
from django.utils.text import slugify
from django.conf import settings
from django.utils import timezone

def assignment_upload_path(instance, filename):
    return f"jobs/{instance.job.id}/assignments/{filename}"

def plag_report_upload_path(instance, filename):
    return f"jobs/{instance.job.id}/plagiarism_reports/{filename}"

def ai_report_upload_path(instance, filename):
    return f"jobs/{instance.job.id}/ai_reports/{filename}"


def delivery_attachment_upload_path(instance, filename):
    return f"jobs/{instance.submission.job.id}/deliverables/{filename}"

class JobStatus(models.TextChoices):
    PROVISIONAL = 'PROVISIONAL', 'Provisional - Awaiting Payment Intent'
    PENDING_PAYMENT = 'PENDING_PAYMENT', 'Pending Client Payment'
    PAYMENT_FAILED = 'PAYMENT_FAILED', 'Client Payment Failed'
    PAID = 'PAID', 'Paid by Client - Funds Held'
    ASSIGNED = 'ASSIGNED', 'Assigned to Freelancer'
    IN_PROGRESS = 'IN_PROGRESS', 'In Progress - Work Being Done'
    DELIVERED = 'DELIVERED', 'Delivered - Awaiting Client Review'
    CLIENT_COMPLETED = 'CLIENT_COMPLETED', 'Client Completed - Payout Ready'
    DISPUTE_OPEN = 'DISPUTE_OPEN', 'Dispute Open'
    DISPUTE_RESOLVED = 'DISPUTE_RESOLVED', 'Dispute Resolved'
    CANCELLED = 'CANCELLED', 'Cancelled'

class TaskCategory(models.Model): 
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True, db_index=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True, editable=False)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class TaskSubjectArea(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, db_index=True)
    slug = models.SlugField(max_length=120, blank=True, editable=False)
    task_category = models.ForeignKey(TaskCategory, on_delete=models.CASCADE, related_name="subject_areas")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "task_category"], name="jobs_unique_subject_per_category"),
            models.UniqueConstraint(fields=["slug", "task_category"], name="jobs_unique_slug_per_category")
        ]
        # Ensures each subject area (and slug) is unique within its parent TaskCategory.
        ordering = ["task_category", "name"]

    def save(self, *args, **kwargs):
        if not self.slug or self._state.adding:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.task_category.name})"

class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, default="")
    description = models.TextField(default="")
    category = models.ForeignKey(TaskCategory, on_delete=models.SET_NULL, null=True, related_name='jobs')
    subject_area = models.ForeignKey(TaskSubjectArea, on_delete=models.SET_NULL, null=True, related_name='jobs')
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='posted_jobs', limit_choices_to={'role': 'CLIENT'})
    freelancer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_jobs', limit_choices_to={'role': 'FREELANCER'}, null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    delivery_time_days = models.PositiveIntegerField(null=True, blank=True)
    allowed_reviews = models.PositiveIntegerField(default=2)
    reviews_used = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50, choices=JobStatus.choices, default=JobStatus.PROVISIONAL)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    client_marked_complete_at = models.DateTimeField(null=True, blank=True)
    paystack_reference = models.CharField(max_length=255, null=True, blank=True, unique=True, db_index=True)
    paystack_authorization_url = models.URLField(max_length=500, null=True, blank=True)
    paystack_status = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['client']),
            models.Index(fields=['freelancer']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        client_name = self.client.get_full_name() if hasattr(self.client, 'get_full_name') else self.client.username
        freelancer_name = self.freelancer.get_full_name() if hasattr(self.freelancer, 'get_full_name') else (self.freelancer.username if self.freelancer else "Unassigned")
        return f"Job #{self.id} ({client_name} -> {freelancer_name}) - {self.get_status_display()}"

class JobSubmission(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='submission')
    submission_text = models.TextField(blank=True, default="")
    assignment = models.FileField(upload_to=assignment_upload_path, null=True, blank=True)
    plag_report = models.FileField(upload_to=plag_report_upload_path, null=True, blank=True)
    ai_report = models.FileField(upload_to=ai_report_upload_path, null=True, blank=True)
    revision_round = models.PositiveIntegerField(default=1)
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = 'Job Submissions'
        indexes = [models.Index(fields=['job'])]

    def __str__(self):
        return f"Submission for Job #{self.job.id}"


class JobSubmissionAttachment(models.Model):
    submission = models.ForeignKey(JobSubmission, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to=delivery_attachment_upload_path)
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['uploaded_at']
        indexes = [models.Index(fields=['submission'])]

    def __str__(self):
        return f"Attachment for Job #{self.submission.job.id}"

class Dispute(models.Model):
    DISPUTE_STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_REVIEW', 'In Review'),
        ('RESOLVED_REFUND', 'Resolved - Refunded'),
        ('RESOLVED_PAID', 'Resolved - Paid to Freelancer'),
    ]

    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='dispute')
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='jobs_disputes_raised')
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=DISPUTE_STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    admin_resolution_notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['job'])]

    def __str__(self):
        return f"Dispute for Job #{self.job.id} - Status: {self.get_status_display()}"
