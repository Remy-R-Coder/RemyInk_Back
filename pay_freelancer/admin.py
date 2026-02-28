from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import Payout, PayoutLog

class PayoutLogInline(admin.TabularInline):
    model = PayoutLog
    extra = 0
    readonly_fields = ('status_update', 'timestamp', 'triggered_by')
    can_delete = False
    
    def has_add_permission(self, request, obj):
        return False

@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ('reference', 'freelancer', 'job_link', 'payout_amount', 'net_amount', 'status', 'created_at')
    list_filter = ('status', 'created_at', 'freelancer')
    search_fields = ('reference', 'freelancer__email', 'freelancer__username', 'transfer_code')
    readonly_fields = ('created_at', 'updated_at', 'reference', 'net_amount', 'is_completed', 'can_retry')
    inlines = [PayoutLogInline]
    
    def job_link(self, obj):
        if obj.job:
            url = reverse('admin:orders_job_change', args=[obj.job.id])
            return format_html('<a href="{}">{}</a>', url, obj.job.id)
        return "No Job"
    job_link.short_description = 'Job'
    
    def net_amount(self, obj):
        return obj.net_amount
    net_amount.short_description = 'Net Amount'
    
    def has_add_permission(self, request):
        return False
    
    fieldsets = (
        ('Basic Information', {'fields': ('reference', 'freelancer', 'job')}),
        ('Amount Details', {'fields': ('payout_amount', 'fee_amount', 'net_amount')}),
        ('Payment Details', {'fields': ('recipient_code', 'transfer_code')}),
        ('Status', {'fields': ('status', 'retry_count', 'last_retry_at', 'processed_at', 'is_completed', 'can_retry')}),
        ('Response Data', {'fields': ('response_data', 'error_message')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

@admin.register(PayoutLog)
class PayoutLogAdmin(admin.ModelAdmin):
    list_display = ('payout', 'status_update', 'timestamp', 'triggered_by')
    list_filter = ('timestamp', 'triggered_by')
    search_fields = ('payout__reference', 'status_update')
    readonly_fields = ('payout', 'status_update', 'timestamp', 'triggered_by', 'response_data')
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False