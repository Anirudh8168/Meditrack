from django.db import models
from django.utils import timezone
from apps.accounts.models import CustomUser
from datetime import date


class Medicine(models.Model):
    PRESCRIPTION_STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('stopped', 'Stopped'),
    ]
    FREQUENCY_CHOICES = [
        ('once_daily', 'Once Daily'),
        ('twice_daily', 'Twice Daily'),
        ('thrice_daily', 'Three Times Daily'),
        ('four_times', 'Four Times Daily'),
        ('weekly', 'Weekly'),
        ('as_needed', 'As Needed'),
    ]
    FREQUENCY_COUNT = {
        'once_daily': 1, 'twice_daily': 2,
        'thrice_daily': 3, 'four_times': 4,
        'weekly': 1, 'as_needed': 99,
    }
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='medicines')
    prescribed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='prescribed_medicines')
    name = models.CharField(max_length=200)
    dosage = models.CharField(max_length=100)
    frequency = models.CharField(max_length=30, choices=FREQUENCY_CHOICES)
    time_slots = models.JSONField(default=list)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    instructions = models.TextField(blank=True)
    stock_quantity = models.IntegerField(default=0, help_text='Available stock (doses/units) — set only via patient purchase')
    prescribed_quantity = models.PositiveIntegerField(default=0)
    units_per_dose = models.PositiveSmallIntegerField(default=1)
    low_stock_threshold = models.IntegerField(default=7)
    critical_stock_threshold = models.IntegerField(default=3)
    expected_end_date = models.DateField(null=True, blank=True)
    refill_required = models.BooleanField(default=False)
    prescription_status = models.CharField(
        max_length=20, choices=PRESCRIPTION_STATUS_CHOICES, default='active',
    )
    total_refilled_quantity = models.PositiveIntegerField(default=0)
    stock_depleted_at = models.DateField(null=True, blank=True)
    last_low_stock_alert_at = models.DateTimeField(null=True, blank=True)
    low_stock_snooze_until = models.DateTimeField(null=True, blank=True)
    is_critical_medicine = models.BooleanField(default=False)
    expiry_date = models.DateField(null=True, blank=True)
    color = models.CharField(max_length=30, default='blue')
    is_active = models.BooleanField(default=True)
    deleted_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_medicines',
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    deletion_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} for {self.patient.get_full_name()}"

    @property
    def max_daily_doses(self):
        return self.FREQUENCY_COUNT.get(self.frequency, 1)

    @property
    def remaining_stock(self):
        return self.stock_quantity

    @property
    def low_stock_alert_at(self):
        return self.critical_stock_threshold

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold

    @property
    def is_critical_stock(self):
        return self.stock_quantity <= self.low_stock_alert_at

    @property
    def is_expired(self):
        if self.expiry_date:
            return self.expiry_date < date.today()
        return False

    @property
    def days_remaining(self):
        if self.end_date:
            delta = (self.end_date - date.today()).days
            return max(0, delta)
        return None

    @property
    def completion_pct(self):
        if self.end_date and self.start_date:
            total = (self.end_date - self.start_date).days
            elapsed = (date.today() - self.start_date).days
            if total > 0:
                return min(100, int(elapsed / total * 100))
        return 0


class MedicineLog(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('taken', 'Taken'),
        ('missed', 'Missed'),
        ('skipped', 'Skipped'),
    ]
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='logs')
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='medicine_logs')
    marked_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='marked_logs')
    scheduled_time = models.DateTimeField()
    taken_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='scheduled')
    notes = models.TextField(blank=True)
    reminder_count = models.IntegerField(default=0)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    last_popup_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_time']
        unique_together = [['medicine', 'scheduled_time']]

    def __str__(self):
        return f"{self.medicine.name} - {self.status}"


class MedicineInventoryEvent(models.Model):
    EVENT_TYPES = [
        ('prescribed', 'Prescribed'),
        ('taken', 'Medicine Taken'),
        ('missed', 'Missed Medicine'),
        ('skipped', 'Skipped'),
        ('delayed', 'Delayed'),
        ('remind_later', 'Reminder Later'),
        ('refilled', 'Refilled'),
        ('low_stock_alert', 'Low Stock Alert'),
    ]
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='inventory_events')
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='medicine_inventory_events')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    quantity_delta = models.IntegerField(default=0)
    stock_after = models.IntegerField(default=0)
    medicine_log = models.ForeignKey(
        MedicineLog, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_events',
    )
    refill = models.ForeignKey(
        'MedicineRefill', on_delete=models.SET_NULL, null=True, blank=True, related_name='events',
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_actions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['patient', 'event_type', 'created_at']),
            models.Index(fields=['medicine', 'created_at']),
        ]

    def __str__(self):
        return f'{self.medicine.name} — {self.get_event_type_display()}'


class MedicineRefill(models.Model):
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='refills')
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='medicine_refills')
    quantity_purchased = models.PositiveIntegerField()
    purchase_date = models.DateField()
    pharmacy_name = models.CharField(max_length=200, blank=True)
    is_partial = models.BooleanField(default=False)
    stock_before = models.PositiveIntegerField(default=0)
    stock_after = models.PositiveIntegerField(default=0)
    recorded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_refills',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchase_date', '-created_at']

    def __str__(self):
        return f'{self.medicine.name} +{self.quantity_purchased} on {self.purchase_date}'


class MedicinePurchase(models.Model):
    """Permanent purchase history — stock exists only after patient confirms purchase."""
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='purchases')
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='medicine_purchases')
    purchase_quantity = models.PositiveIntegerField()
    purchase_date = models.DateField()
    previous_stock = models.PositiveIntegerField(default=0)
    updated_stock = models.PositiveIntegerField(default=0)
    pharmacy_name = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_purchases',
    )
    refill = models.ForeignKey(
        MedicineRefill, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_record',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchase_date', '-created_at']

    def __str__(self):
        return f'{self.medicine.name} +{self.purchase_quantity} on {self.purchase_date}'


class RiskScore(models.Model):
    RISK_LEVELS = [
        ('low', 'Low Risk'),
        ('medium', 'Medium Risk'),
        ('high', 'High Risk'),
        ('critical', 'Critical Risk'),
    ]
    patient = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name='risk_score',
    )
    score = models.IntegerField(default=0)
    level = models.CharField(max_length=10, choices=RISK_LEVELS, default='low')
    factors = models.JSONField(default=dict)
    risk_types = models.JSONField(default=list, blank=True)
    component_scores = models.JSONField(default=dict, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    health_impacts = models.JSONField(default=list, blank=True)
    recommended_actions = models.JSONField(default=list, blank=True)
    level_message = models.CharField(max_length=255, blank=True)
    disease_context = models.JSONField(default=dict, blank=True)
    dynamic_analysis = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    recorded_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['level', 'score']),
        ]

    def save(self, *args, **kwargs):
        if self.score <= 25:
            self.level = 'low'
        elif self.score <= 50:
            self.level = 'medium'
        elif self.score <= 75:
            self.level = 'high'
        else:
            self.level = 'critical'
        super().save(*args, **kwargs)

    @property
    def risk_type_labels(self):
        from apps.medicines.dynamic_risk_engine import RISK_TYPE_LABELS
        return [RISK_TYPE_LABELS.get(t, t.replace('_', ' ').title()) for t in (self.risk_types or [])]

    @property
    def predictions(self):
        return (self.dynamic_analysis or {}).get('predictions', self.health_impacts or [])

    @property
    def prediction_summary(self):
        return (self.dynamic_analysis or {}).get('prediction_summary', '')

    @property
    def patient_message(self):
        return (self.dynamic_analysis or {}).get('patient_message', '') or self.level_message

    @property
    def escalation_level(self):
        return (self.dynamic_analysis or {}).get('escalation_level', 1)

    @property
    def medicine_insights(self):
        return (self.dynamic_analysis or {}).get('medicine_insights', [])

    def __str__(self):
        return f'{self.patient.get_full_name()} — {self.level} ({self.score})'


class RiskScoreHistory(models.Model):
    """Daily/historical risk snapshots for trend graphs."""
    patient = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='risk_history',
    )
    score = models.IntegerField(default=0)
    level = models.CharField(max_length=10, default='low')
    risk_types = models.JSONField(default=list, blank=True)
    component_scores = models.JSONField(default=dict, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    dynamic_snapshot = models.JSONField(default=dict, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['patient', 'recorded_at']),
        ]


class Activity(models.Model):
    ACTIVITY_TYPES = [
        ('exercise', 'Exercise'),
        ('walking', 'Walking'),
        ('yoga', 'Yoga'),
        ('physiotherapy', 'Physiotherapy'),
        ('dialysis', 'Dialysis'),
        ('bp_check', 'Blood Pressure Check'),
        ('sugar_check', 'Blood Sugar Check'),
        ('breathing', 'Breathing Exercise'),
        ('diet', 'Diet'),
        ('meditation', 'Meditation'),
        ('sleep', 'Sleep'),
        ('doctor_recommended', 'Doctor Recommended'),
        ('vitals', 'Vitals Check'),
        ('symptom', 'Symptom Report'),
        ('other', 'Other'),
    ]
    SCHEDULE_TYPES = [
        ('one_time', 'One Time Activity'),
        ('daily', 'Daily Activity'),
        ('weekly', 'Weekly Activity'),
        ('custom', 'Custom Schedule'),
    ]
    SEVERITY_CHOICES = [
        ('low', 'Low Impact'),
        ('medium', 'Medium Impact'),
        ('high', 'High Impact'),
        ('critical', 'Critical Impact'),
    ]
    SEVERITY_RISK_POINTS = {'low': 1, 'medium': 5, 'high': 15, 'critical': 20}
    DOCTOR_PRIORITY_CHOICES = [
        ('', 'Auto (based on activity type)'),
        ('low', 'Low Priority'),
        ('medium', 'Medium Priority'),
        ('high', 'High Priority'),
        ('critical', 'Critical Priority'),
    ]
    WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='activities')
    prescribed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='prescribed_activities',
    )
    logged_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='logged_activities',
    )
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_TYPES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    duration_minutes = models.IntegerField(default=30)
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_TYPES, default='one_time')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    time_slots = models.JSONField(default=list, blank=True)
    repeat_days = models.JSONField(default=list, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='low')
    requires_proof = models.BooleanField(default=False)
    reminders_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    file_upload = models.FileField(upload_to='activities/', null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.title} ({self.get_schedule_type_display()})"

    @property
    def is_doctor_prescribed(self):
        return self.prescribed_by is not None and self.prescribed_by.role == 'doctor'

    @property
    def has_no_end_date(self):
        return self.end_date is None

    def is_scheduled_on(self, day):
        if not self.is_active:
            return False
        if self.start_date and day < self.start_date:
            return False
        if self.end_date and day > self.end_date:
            return False
        if self.schedule_type == 'one_time':
            return self.start_date == day
        if self.schedule_type == 'daily':
            return True
        if self.schedule_type in ('weekly', 'custom'):
            weekday = self.WEEKDAY_KEYS[day.weekday()]
            return weekday in (self.repeat_days or [])
        return False


class ActivityLog(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('missed', 'Missed'),
        ('skipped', 'Skipped'),
    ]
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='logs')
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='activity_logs')
    marked_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='marked_activity_logs',
    )
    scheduled_time = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='scheduled')
    start_proof_upload = models.FileField(upload_to='activities/start_proof/', null=True, blank=True)
    proof_upload = models.FileField(upload_to='activities/proof/', null=True, blank=True)
    notes = models.TextField(blank=True)
    reminder_count = models.IntegerField(default=0)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    last_popup_at = models.DateTimeField(null=True, blank=True)
    missed_reason = models.TextField(blank=True)
    missed_at = models.DateTimeField(null=True, blank=True)
    duration_completed_minutes = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_time']
        unique_together = [['activity', 'scheduled_time']]

    def __str__(self):
        return f"{self.activity.title} — {self.status} @ {self.scheduled_time}"

    @property
    def can_complete(self):
        if self.status != 'in_progress' or not self.started_at:
            return False
        elapsed = (timezone.now() - self.started_at).total_seconds() / 60
        return elapsed >= (self.activity.duration_minutes or 1)

    @property
    def remaining_seconds(self):
        if self.status != 'in_progress' or not self.started_at:
            return 0
        total = (self.activity.duration_minutes or 1) * 60
        elapsed = (timezone.now() - self.started_at).total_seconds()
        return max(0, int(total - elapsed))


class ActivityAuditLog(models.Model):
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('deleted', 'Deleted'),
    ]
    SCOPE_CHOICES = [
        ('occurrence', 'This occurrence only'),
        ('future', 'Future schedules'),
        ('entire', 'Entire schedule'),
    ]
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='audit_logs')
    user = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='activity_audit_actions',
    )
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    scope = models.CharField(max_length=15, choices=SCOPE_CHOICES, blank=True)
    reason = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True)
    effective_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_action_display()} — {self.activity.title}'


class DailyHealthCheck(models.Model):
    FEELING_CHOICES = [
        ('good', 'Good'),
        ('okay', 'Okay'),
        ('not_good', 'Not Good'),
        ('custom', 'Custom'),
    ]
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='health_checks')
    feeling = models.CharField(max_length=10, choices=FEELING_CHOICES)
    notes = models.TextField(blank=True)
    symptoms = models.JSONField(default=list, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-checked_at']

    def __str__(self):
        return f"{self.patient.get_full_name()} - {self.feeling} on {self.checked_at.date()}"


class FamilyContact(models.Model):
    RELATION_CHOICES = [
        ('spouse', 'Spouse'), ('parent', 'Parent'), ('child', 'Child'),
        ('sibling', 'Sibling'), ('friend', 'Friend'), ('caregiver', 'Caregiver'),
        ('other', 'Other'),
    ]
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='family_contacts')
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    relation = models.CharField(max_length=15, choices=RELATION_CHOICES, default='other')
    is_primary = models.BooleanField(default=False)
    notify_on_missed = models.BooleanField(default=True)
    missed_count_threshold = models.IntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f"{self.name} ({self.relation}) - {self.patient.get_full_name()}"


class MissedAlertLog(models.Model):
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='missed_alert_logs')
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='missed_alerts', null=True, blank=True)
    alert_type = models.CharField(max_length=30, default='missed_medicine')
    sent_to = models.JSONField(default=list)
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']


class HealthRiskAlert(models.Model):
    """Persistent log for automatic high-risk family/caregiver escalation alerts."""
    patient = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='health_risk_alerts',
    )
    trigger_medicine = models.ForeignKey(
        Medicine, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='risk_alerts',
    )
    risk_score = models.IntegerField(default=0)
    risk_level = models.CharField(max_length=10, default='high')
    escalation_level = models.IntegerField(default=3)
    medicines_missed_count = models.IntegerField(default=0)
    consecutive_misses = models.IntegerField(default=0)
    reason = models.TextField(blank=True)
    message = models.TextField()
    doctor_name = models.CharField(max_length=150, blank=True)
    recipients = models.JSONField(default=list)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f'L{self.escalation_level} {self.patient.get_full_name()} @ {self.sent_at}'

    @property
    def severity_label(self):
        if self.escalation_level >= 4:
            return 'CRITICAL'
        if self.escalation_level >= 3:
            return 'HIGH'
        return 'MEDIUM'

    @property
    def patient_phone(self):
        return getattr(self.patient, 'phone', '') or ''

    @property
    def emergency_phone(self):
        from apps.family.models import FamilyMember
        ec = FamilyMember.objects.filter(
            patient=self.patient, is_emergency_contact=True,
        ).first()
        if ec and ec.phone:
            return ec.phone
        contact = FamilyContact.objects.filter(patient=self.patient).exclude(phone='').first()
        return contact.phone if contact else ''


class ReminderTracking(models.Model):
    """Unified reminder state for medicine doses and scheduled activities."""
    REFERENCE_TYPES = (
        ('medicine', 'Medicine'),
        ('activity', 'Activity'),
    )
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('snoozed', 'Snoozed'),
        ('completed', 'Completed'),
        ('missed', 'Missed'),
    )

    patient = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='reminder_trackings',
    )
    reference_type = models.CharField(max_length=20, choices=REFERENCE_TYPES)
    reference_id = models.PositiveIntegerField(help_text='MedicineLog.id or ActivityLog.id')
    scheduled_datetime = models.DateTimeField()
    current_reminder_count = models.IntegerField(default=0)
    last_popup_at = models.DateTimeField(null=True, blank=True)
    next_popup_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    ignored_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reminder_tracking'
        unique_together = [['reference_type', 'reference_id']]
        indexes = [
            models.Index(fields=['patient', 'status', 'next_popup_at']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]

    def __str__(self):
        return f'{self.reference_type}#{self.reference_id} — {self.status}'
