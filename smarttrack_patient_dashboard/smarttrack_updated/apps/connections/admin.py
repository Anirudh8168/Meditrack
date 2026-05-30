from django.contrib import admin
from .models import DoctorPatientConnection

@admin.register(DoctorPatientConnection)
class DoctorPatientConnectionAdmin(admin.ModelAdmin):
    list_display = ('patient', 'doctor', 'status', 'requested_by', 'created_at')
    list_filter = ('status',)
