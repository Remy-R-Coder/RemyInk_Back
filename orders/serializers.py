from rest_framework import serializers
from typing import Any
from .models import Job, JobSubmission, JobSubmissionAttachment, Dispute, JobStatus


class JobSubmissionReadSerializer(serializers.ModelSerializer):
    assignment_url = serializers.SerializerMethodField()
    plag_report_url = serializers.SerializerMethodField()
    ai_report_url = serializers.SerializerMethodField()
    attachment_files = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    all_attachments = serializers.SerializerMethodField()

    class Meta:
        model = JobSubmission
        fields = [
            'submission_text',
            'assignment_url',
            'plag_report_url',
            'ai_report_url',
            'attachment_files',
            'attachments',
            'all_attachments',
            'revision_round',
            'submitted_at',
        ]

    def _abs(self, url: str | None) -> str | None:
        request = self.context.get('request')
        if request and url:
            return request.build_absolute_uri(url)
        return url

    def get_assignment_url(self, obj: JobSubmission) -> str | None:
        return self._abs(obj.assignment.url) if obj.assignment else None

    def get_plag_report_url(self, obj: JobSubmission) -> str | None:
        return self._abs(obj.plag_report.url) if obj.plag_report else None

    def get_ai_report_url(self, obj: JobSubmission) -> str | None:
        return self._abs(obj.ai_report.url) if obj.ai_report else None

    def get_attachment_files(self, obj: JobSubmission) -> list[str]:
        return [self._abs(att.file.url) for att in obj.attachments.all() if att.file]

    def get_attachments(self, obj: JobSubmission) -> list[str]:
        return self.get_attachment_files(obj)

    def _attachment_item(self, label: str, file_field: Any) -> dict[str, str] | None:
        if not file_field:
            return None
        try:
            name = file_field.name.split('/')[-1] if file_field.name else ''
        except Exception:
            name = ''
        return {
            'label': label,
            'name': name,
            'url': self._abs(file_field.url),
        }

    def get_all_attachments(self, obj: JobSubmission) -> list[dict[str, str]]:
        job_id = str(obj.job.id)
        items = []
        for label, field in [
            ('assignment', obj.assignment),
            ('plag_report', obj.plag_report),
            ('ai_report', obj.ai_report),
        ]:
            item = self._attachment_item(label, field)
            if item:
                item['download_url'] = self._abs(f"/api/orders/jobs/{job_id}/submission/legacy/{label}/download/")
                items.append(item)

        for att in obj.attachments.all():
            if not att.file:
                continue
            name = att.file.name.split('/')[-1] if att.file.name else ''
            items.append({
                'label': 'deliverable',
                'name': name,
                'url': self._abs(att.file.url),
                'download_url': self._abs(f"/api/orders/jobs/{job_id}/submission/attachments/{att.id}/download/"),
            })
        return items


class JobSerializer(serializers.ModelSerializer):
    client_id = serializers.UUIDField(source='client.id', read_only=True)
    client_username = serializers.CharField(source='client.username', read_only=True)
    client_email = serializers.EmailField(source='client.email', read_only=True)

    freelancer_id = serializers.UUIDField(source='freelancer.id', read_only=True)
    freelancer_username = serializers.CharField(source='freelancer.username', read_only=True)
    freelancer_email = serializers.EmailField(source='freelancer.email', read_only=True)

    category_name = serializers.CharField(source='category.name', read_only=True)
    subject_name = serializers.CharField(source='subject_area.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    reviews_remaining = serializers.SerializerMethodField()
    submission = JobSubmissionReadSerializer(read_only=True)
    dispute = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            'id',
            'client_id', 'client_username', 'client_email',
            'freelancer_id', 'freelancer_username', 'freelancer_email',
            'category_name', 'subject_name', 'price', 'total_amount',
            'allowed_reviews', 'reviews_used', 'reviews_remaining',
            'status', 'status_display', 'created_at', 'updated_at', 
            'paystack_reference', 'paystack_authorization_url', 'paystack_status',
            'client_marked_complete_at',
            'submission',
            'dispute',
        ]
        read_only_fields = fields

    def get_reviews_remaining(self, obj: Job) -> int:
        remaining = int(obj.allowed_reviews or 0) - int(obj.reviews_used or 0)
        return remaining if remaining > 0 else 0

    def get_dispute(self, obj: Job) -> dict[str, Any] | None:
        dispute = getattr(obj, 'dispute', None)
        if not dispute:
            return None
        return DisputeSerializer(dispute, context=self.context).data


class JobCreateSerializer(serializers.ModelSerializer):
    # Backward-compatible alias: accepts `subject` payload and stores it on `subject_area`.
    subject = serializers.PrimaryKeyRelatedField(
        source='subject_area',
        queryset=Job._meta.get_field('subject_area').remote_field.model.objects.all(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = Job
        fields = ['category', 'subject_area', 'subject', 'price', 'freelancer', 'allowed_reviews']
        extra_kwargs = {
            'subject_area': {'required': False},
        }

    def validate(self, attrs):
        if not attrs.get('subject_area'):
            raise serializers.ValidationError({'subject_area': 'This field is required.'})
        return attrs


class JobSubmissionSerializer(serializers.ModelSerializer):
    attachments = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
        allow_empty=True
    )
    attachment_files = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = JobSubmission
        fields = [
            'submission_text',
            'assignment',
            'plag_report',
            'ai_report',
            'revision_round',
            'attachments',
            'attachment_files',
        ]
        read_only_fields = ['revision_round']

    def validate(self, attrs):
        has_text = bool((attrs.get('submission_text') or '').strip())
        has_legacy_file = any([
            attrs.get('assignment'),
            attrs.get('plag_report'),
            attrs.get('ai_report'),
        ])
        has_attachments = bool(attrs.get('attachments'))

        if not (has_text or has_legacy_file or has_attachments):
            raise serializers.ValidationError(
                'Provide at least one of submission_text, a file attachment, or legacy report files.'
            )
        return attrs

    def create(self, validated_data):
        attachments = validated_data.pop('attachments', [])
        submission = super().create(validated_data)
        for uploaded in attachments:
            JobSubmissionAttachment.objects.create(submission=submission, file=uploaded)
        return submission

    def update(self, instance, validated_data):
        attachments = validated_data.pop('attachments', [])
        instance = super().update(instance, validated_data)
        for uploaded in attachments:
            JobSubmissionAttachment.objects.create(submission=instance, file=uploaded)
        return instance

    def get_attachment_files(self, obj):
        request = self.context.get('request')
        files = []
        for att in obj.attachments.all():
            if not att.file:
                continue
            url = att.file.url
            files.append(request.build_absolute_uri(url) if request else url)
        return files


class DisputeSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source='job.id', read_only=True)
    raised_by_id = serializers.UUIDField(source='raised_by.id', read_only=True)
    raised_by_username = serializers.CharField(source='raised_by.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Dispute
        fields = [
            'id',
            'job',
            'job_id',
            'raised_by',
            'raised_by_id',
            'raised_by_username',
            'reason',
            'status',
            'status_display',
            'admin_resolution_notes',
            'created_at',
            'resolved_at',
        ]
        read_only_fields = [
            'id',
            'job',
            'job_id',
            'raised_by',
            'raised_by_id',
            'raised_by_username',
            'status_display',
            'created_at',
            'resolved_at',
        ]
