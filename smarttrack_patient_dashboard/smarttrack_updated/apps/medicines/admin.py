from django.contrib import admin
from .models import (
    Medicine, MedicineLog, MedicineRefill, MedicinePurchase, MedicineInventoryEvent,
    RiskScore, RiskScoreHistory, Activity, DailyHealthCheck, FamilyContact,
    MissedAlertLog, HealthRiskAlert, ReminderTracking,
)

@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ('name', 'patient', 'prescribed_by', 'frequency', 'stock_quantity', 'is_active', 'created_at')
    list_filter = ('is_active', 'frequency', 'color')
    search_fields = ('name', 'patient__email', 'patient__first_name')

@admin.register(MedicineLog)
class MedicineLogAdmin(admin.ModelAdmin):
    list_display = ('medicine', 'patient', 'status', 'scheduled_time', 'taken_at')
    list_filter = ('status',)


@admin.register(ReminderTracking)
class ReminderTrackingAdmin(admin.ModelAdmin):
    list_display = ('reference_type', 'reference_id', 'patient', 'status', 'next_popup_at', 'current_reminder_count')
    list_filter = ('reference_type', 'status')

@admin.register(MedicineRefill)
class MedicineRefillAdmin(admin.ModelAdmin):
    list_display = ('medicine', 'patient', 'quantity_purchased', 'purchase_date', 'is_partial', 'created_at')
    list_filter = ('is_partial',)


@admin.register(MedicinePurchase)
class MedicinePurchaseAdmin(admin.ModelAdmin):
    list_display = ('medicine', 'patient', 'purchase_quantity', 'purchase_date', 'previous_stock', 'updated_stock', 'created_at')
    list_filter = ('purchase_date',)
    search_fields = ('medicine__name', 'patient__email')


@admin.register(MedicineInventoryEvent)
class MedicineInventoryEventAdmin(admin.ModelAdmin):
    list_display = ('medicine', 'event_type', 'quantity_delta', 'stock_after', 'created_at')
    list_filter = ('event_type',)


@admin.register(RiskScore)
class RiskScoreAdmin(admin.ModelAdmin):
    list_display = ('patient', 'score', 'level', 'recorded_at')
    list_filter = ('level',)
    search_fields = ('patient__email', 'patient__first_name')


@admin.register(RiskScoreHistory)
class RiskScoreHistoryAdmin(admin.ModelAdmin):
    list_display = ('patient', 'score', 'level', 'recorded_at')
    list_filter = ('level',)

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('patient', 'activity_type', 'title', 'recorded_at')

@admin.register(DailyHealthCheck)
class DailyHealthCheckAdmin(admin.ModelAdmin):
    list_display = ('patient', 'feeling', 'checked_at')
    list_filter = ('feeling',)

@admin.register(FamilyContact)
class FamilyContactAdmin(admin.ModelAdmin):
    list_display = ('patient', 'name', 'relation', 'phone', 'notify_on_missed')

@admin.register(MissedAlertLog)
class MissedAlertLogAdmin(admin.ModelAdmin):
    list_display = ('patient', 'alert_type', 'medicine', 'sent_at')


@admin.register(HealthRiskAlert)
class HealthRiskAlertAdmin(admin.ModelAdmin):
    list_display = ('patient', 'escalation_level', 'risk_level', 'risk_score', 'consecutive_misses', 'sent_at')
    list_filter = ('escalation_level', 'risk_level')
    search_fields = ('patient__email', 'patient__first_name', 'patient__last_name')
