from django.contrib import admin
from .models import ConsultationPayment


@admin.register(ConsultationPayment)
class ConsultationPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'payment_id', 'patient', 'doctor', 'amount', 'payment_status',
        'appointment_type', 'paid_at', 'created_at',
    )
    list_filter = ('payment_status', 'payment_type', 'payment_gateway')
    search_fields = ('payment_id', 'transaction_id', 'patient__email', 'doctor__email')
    readonly_fields = (
        'payment_id', 'patient', 'doctor', 'appointment', 'amount', 'payment_type',
        'appointment_type', 'payment_gateway', 'gateway_order_id', 'transaction_id',
        'payment_method', 'payment_status', 'tax_amount', 'paid_by', 'caregiver',
        'created_at', 'paid_at', 'failure_reason', 'metadata',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
