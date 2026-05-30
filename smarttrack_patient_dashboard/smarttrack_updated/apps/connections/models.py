from django.db import models
from apps.accounts.models import CustomUser


class DoctorPatientConnection(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='patient_connections')
    doctor = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='doctor_connections')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sent_connections')
    request_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('patient', 'doctor')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.patient} <-> Dr.{self.doctor} [{self.status}]"
