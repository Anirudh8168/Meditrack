from django.db import models
from apps.accounts.models import CustomUser


class AdminActionLog(models.Model):
    ACTION_CHOICES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('suspend', 'Suspend'),
        ('activate', 'Activate'),
        ('verify', 'Verify'),
        ('notify', 'Send Notification'),
        ('export', 'Export'),
        ('other', 'Other'),
    ]

    admin_user = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='admin_actions',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='other')
    target_model = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=50, blank=True)
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action}: {self.description[:60]}'
