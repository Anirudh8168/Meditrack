from django.contrib import admin
from .models import Appointment, DoctorSchedule

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('patient', 'doctor', 'appointment_date', 'appointment_time', 'appointment_type', 'status', 'is_emergency')
    list_filter = ('status', 'appointment_type', 'is_emergency')
    search_fields = ('patient__email', 'doctor__email')
    readonly_fields = ('created_at', 'updated_at', 'cancelled_at')

@admin.register(DoctorSchedule)
class DoctorScheduleAdmin(admin.ModelAdmin):
    list_display = ('doctor', 'day_of_week', 'start_time', 'end_time', 'is_available')
    list_filter = ('day_of_week', 'is_available')
