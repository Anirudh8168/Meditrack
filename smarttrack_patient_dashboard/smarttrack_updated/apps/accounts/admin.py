from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, OTPRecord


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_email_verified', 'otp_verified', 'is_active', 'last_login')
    list_filter = ('role', 'is_active', 'is_email_verified', 'otp_verified')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    fieldsets = UserAdmin.fieldsets + (
        ('SmartTrack Auth', {
            'fields': ('role', 'is_email_verified', 'otp_verified', 'last_activity'),
        }),
    )


@admin.register(OTPRecord)
class OTPRecordAdmin(admin.ModelAdmin):
    list_display = ('email', 'purpose', 'is_used', 'created_at')
