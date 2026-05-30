from django.db import models
from apps.accounts.models import CustomUser

class Notification(models.Model):
    TYPE_CHOICES = [
        ('medicine', 'Medicine'),
        ('activity', 'Activity'),
        ('appointment', 'Appointment'),
        ('connection', 'Connection'),
        ('report', 'Report'),
        ('alert', 'Alert'),
        ('message', 'Message'),
        ('general', 'General'),
    ]
    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='general')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='low')
    category = models.CharField(max_length=100, null=True, blank=True) # For deduplication (e.g. 'med_reminder_123')
    related_id = models.IntegerField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.notification_type}] {self.title} -> {self.user}"
