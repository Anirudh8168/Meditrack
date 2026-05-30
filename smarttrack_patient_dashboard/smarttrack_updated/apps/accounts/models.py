from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """
    Login / authentication only — stored in auth_user table.
    Profile, medical, and contact data live in role-specific profile tables.
    """
    ROLE_CHOICES = (
        ('patient', 'Patient'),
        ('doctor', 'Doctor'),
        ('admin', 'Admin'),
        ('caregiver', 'Caregiver'),
        ('family', 'Family Member'),
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='patient')
    is_email_verified = models.BooleanField(default=False, help_text='Email verified (is_verified)')
    otp_verified = models.BooleanField(default=False)
    last_activity = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'auth_user'
        indexes = [
            models.Index(fields=['role', 'is_active']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.role})'

    def get_dashboard_url(self):
        role_urls = {
            'patient': '/dashboard/patient/',
            'doctor': '/dashboard/doctor/',
            'admin': '/system-admin/',
            'caregiver': '/dashboard/caregiver/',
            'family': '/dashboard/family/',
        }
        return role_urls.get(self.role, '/dashboard/')

    def get_display_name(self):
        return self.get_full_name() or self.username

    def get_title(self):
        return 'Dr. ' if self.role == 'doctor' else ''

    def get_full_name(self):
        from apps.profiles.profile_bridge import get_user_full_name
        return get_user_full_name(self)

    @property
    def phone(self):
        from apps.profiles.profile_bridge import get_user_phone
        return get_user_phone(self)

    @phone.setter
    def phone(self, value):
        from apps.profiles.profile_bridge import set_user_phone, ensure_role_profile
        ensure_role_profile(self)
        set_user_phone(self, value)

    @property
    def unique_id(self):
        from apps.profiles.profile_bridge import get_user_public_id
        return get_user_public_id(self)

    @property
    def profile_completed(self):
        from apps.profiles.profile_bridge import is_profile_completed
        return is_profile_completed(self)

    @profile_completed.setter
    def profile_completed(self, value):
        from apps.profiles.profile_bridge import set_profile_completed, ensure_role_profile
        ensure_role_profile(self)
        set_profile_completed(self, value)

    @property
    def preferred_language(self):
        profile = self._role_profile()
        if profile and getattr(profile, 'preferred_language', None):
            return profile.preferred_language
        return 'en'

    @property
    def is_online(self):
        if not self.last_activity:
            return False
        from django.utils import timezone
        return (timezone.now() - self.last_activity).total_seconds() < 300

    def _role_profile(self):
        from apps.profiles.profile_bridge import get_role_profile
        return get_role_profile(self)


class OTPRecord(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    purpose = models.CharField(max_length=30, default='password_reset')
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'auth_otp_record'

    def __str__(self):
        return f'OTP for {self.email}'
