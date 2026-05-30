from django.contrib import admin
from .models import Report

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('patient', 'doctor', 'risk_level', 'adherence_pct', 'status', 'created_at')
    list_filter = ('risk_level', 'status')
