from django.contrib import admin
from .models import Payment, PaymentWebhookLog


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['reference', 'job', 'user', 'amount', 'currency', 'status', 'created_at', 'paid_at']
    list_filter = ['status', 'currency', 'created_at', 'paid_at']
    search_fields = ['reference', 'user__email', 'user__username', 'job__title']
    readonly_fields = ['id', 'reference', 'created_at', 'updated_at', 'verified_at', 'paid_at', 'paystack_response']
    ordering = ['-created_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'job', 'user', 'amount', 'currency', 'status')
        }),
        ('Paystack Details', {
            'fields': ('reference', 'authorization_url', 'access_code', 'paystack_response')
        }),
        ('Verification', {
            'fields': ('verified_at', 'paid_at')
        }),
        ('Metadata', {
            'fields': ('ip_address', 'user_agent', 'created_at', 'updated_at')
        }),
    )


@admin.register(PaymentWebhookLog)
class PaymentWebhookLogAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'reference', 'payment', 'processed', 'created_at']
    list_filter = ['event_type', 'processed', 'created_at']
    search_fields = ['reference', 'event_type']
    readonly_fields = ['id', 'event_type', 'reference', 'payload', 'payment', 'processed', 'processing_error', 'created_at']
    ordering = ['-created_at']

    fieldsets = (
        ('Webhook Information', {
            'fields': ('id', 'event_type', 'reference', 'payment')
        }),
        ('Processing', {
            'fields': ('processed', 'processing_error')
        }),
        ('Payload', {
            'fields': ('payload',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at',)
        }),
    )
