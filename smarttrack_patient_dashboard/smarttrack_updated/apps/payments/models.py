import uuid
from decimal import Decimal

from django.db import models
from django.utils import timezone

from apps.accounts.models import CustomUser


class ConsultationPayment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
        ('cancelled', 'Cancelled'),
    ]
    PAYMENT_TYPE_CHOICES = [
        ('video', 'Video Consultation'),
        ('emergency_video', 'Emergency Video Consultation'),
    ]
    METHOD_CHOICES = [
        ('upi', 'UPI'),
        ('card', 'Credit/Debit Card'),
        ('netbanking', 'Net Banking'),
        ('wallet', 'Wallet'),
        ('razorpay', 'Razorpay'),
        ('demo', 'Demo Payment'),
    ]

    payment_id = models.CharField(max_length=32, unique=True, editable=False)
    receipt_id = models.CharField(max_length=32, blank=True, unique=True, null=True)
    patient = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='consultation_payments',
    )
    doctor = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='doctor_payments_received',
    )
    appointment = models.OneToOneField(
        'appointments.Appointment', on_delete=models.CASCADE, related_name='consultation_payment',
    )
    paid_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments_made',
    )
    caregiver = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='caregiver_payments_made',
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    appointment_type = models.CharField(max_length=20)
    payment_gateway = models.CharField(max_length=30, default='razorpay')
    gateway_order_id = models.CharField(max_length=100, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, blank=True)
    payment_status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    verified = models.BooleanField(default=False)
    otp_verified = models.BooleanField(default=False)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payment_status', 'doctor']),
            models.Index(fields=['payment_status', 'patient']),
            models.Index(fields=['created_at']),
        ]

    def save(self, *args, **kwargs):
        if not self.payment_id:
            self.payment_id = f'TXN{uuid.uuid4().hex[:10].upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.payment_id} — ₹{self.amount} ({self.payment_status})'

    @property
    def total_amount(self):
        return self.amount + (self.tax_amount or Decimal('0'))

    @property
    def is_payable(self):
        return self.payment_status in ('pending', 'failed')

    @property
    def consultation_type(self):
        return self.appointment_type_display

    @property
    def payment_time(self):
        return self.paid_at

    @property
    def appointment_type_display(self):
        labels = {'video': 'Video Consultation', 'emergency_video': 'Emergency Video Consultation'}
        return labels.get(self.appointment_type, self.appointment_type)
