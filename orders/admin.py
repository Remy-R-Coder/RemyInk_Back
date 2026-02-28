from django.contrib import admin
from django.utils.html import format_html
from django.db import transaction
from django.utils import timezone
from .models import Job, JobSubmission, JobSubmissionAttachment, Dispute, JobStatus

class JobSubmissionInline(admin.TabularInline):
    model = JobSubmission
    extra = 0
    fields = ('job', 'submission_text', 'assignment', 'plag_report', 'ai_report', 'revision_round', 'submitted_at')
    readonly_fields = ('job', 'submitted_at')
    verbose_name_plural = 'Submission Details'


class DisputeInline(admin.StackedInline):
    model = Dispute
    extra = 0
    fields = (
        'raised_by',
        'reason',
        ('status', 'resolved_at'),
        'admin_resolution_notes',
    )
    readonly_fields = ('raised_by', 'created_at')
    max_num = 1


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'freelancer', 'status', 'total_amount', 'created_at')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('client__username', 'freelancer__username', 'id', 'paystack_reference')
    ordering = ('-created_at',)
    list_per_page = 25
    inlines = [JobSubmissionInline, DisputeInline]
    
    fieldsets = (
        ('A. Core Job Details', {
            'fields': (
                ('client', 'freelancer'),
                ('category', 'subject_area'), 
                'description', 
                # 'deadline',
                'status',
            ),
        }),
        ('B. Financial & Payment Status (Paystack)', {
            'fields': (
                ('price', 'total_amount'),
                ('allowed_reviews', 'reviews_used'),
                'paystack_reference',
                'paystack_authorization_url',
                'paystack_status',
                'client_marked_complete_at',
            ),
        }),
        ('C. Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',),
        }),
    )
    
    readonly_fields = (
        'created_at', 'updated_at', 'total_amount', 
        'paystack_reference', 'paystack_authorization_url', 'paystack_status',
        'client_marked_complete_at', 'completed_at', 'reviews_used'
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('client', 'freelancer', 'category', 'subject_area')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is None and 'client' in form.base_fields:
            if not form.base_fields['client'].initial:
                form.base_fields['client'].initial = request.user
            form.base_fields['client'].disabled = False
        return form


@admin.register(JobSubmission)
class JobSubmissionAdmin(admin.ModelAdmin):
    list_display = ('job', 'submitted_at', 'assignment_link') # Simplified list display
    search_fields = ('job__id',)
    readonly_fields = ('job', 'submitted_at', 'submission_text', 'assignment', 'plag_report', 'ai_report', 'revision_round')

    def assignment_link(self, obj):
        if obj.assignment:
            return format_html('<a href="{}" target="_blank">Download</a>', obj.assignment.url)
        return "N/A"
    assignment_link.allow_tags = True
    assignment_link.short_description = 'Assignment File'


@admin.register(JobSubmissionAttachment)
class JobSubmissionAttachmentAdmin(admin.ModelAdmin):
    list_display = ('submission', 'file', 'uploaded_at')
    search_fields = ('submission__job__id',)
    readonly_fields = ('uploaded_at',)


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ('job', 'raised_by', 'status', 'created_at', 'resolved_at')
    list_filter = ('status', 'created_at')
    search_fields = ('job__id', 'raised_by__username')
    readonly_fields = ('job', 'raised_by', 'created_at')
    fieldsets = (
        (None, {
            'fields': ('job', 'raised_by', 'reason', 'status')
        }),
        ('Resolution', {
            'fields': ('admin_resolution_notes', 'resolved_at'),
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )
