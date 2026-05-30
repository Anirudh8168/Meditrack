from django.db import models
from apps.accounts.models import CustomUser


CAREGIVER_TYPE_CHOICES = [
    ('family', 'Family Caregiver'),
    ('personal', 'Personal Caregiver'),
    ('hospital', 'Hospital Caregiver'),
    ('private_center', 'Private Care Center'),
    ('nursing', 'Nursing Caregiver'),
    ('home_nurse', 'Home Nurse'),
    ('elderly', 'Elderly Caregiver'),
    ('other', 'Other'),
]

HOSPITAL_ROLE_CHOICES = [
    ('hospital_caregiver', 'Hospital Caregiver'),
    ('clinical_assistant', 'Clinical Assistant'),
    ('nurse', 'Nurse'),
    ('emergency_support', 'Emergency Support'),
    ('elderly_support', 'Elderly Support'),
    ('monitoring_staff', 'Monitoring Staff'),
    ('recovery_assistant', 'Recovery Assistant'),
]

HOSPITAL_DEPARTMENT_CHOICES = [
    ('icu', 'ICU'),
    ('dermatology', 'Dermatology'),
    ('cardiology', 'Cardiology'),
    ('general_care', 'General Care'),
    ('emergency', 'Emergency'),
    ('other', 'Other'),
]

HOSPITAL_DURATION_CHOICES = [
    ('permanent', 'Permanent'),
    ('temporary', 'Temporary'),
]


class CaregiverProfile(models.Model):
    CAREGIVER_TYPE_CHOICES = CAREGIVER_TYPE_CHOICES
    RELATION_CHOICES = [
        ('nurse', 'Nurse'),
        ('hospital_staff', 'Hospital Staff'),
        ('family_member', 'Family Member'),
        ('friend', 'Friend'),
        ('hired', 'Hired Caregiver'),
        ('other', 'Other'),
    ]
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='caregiver_profile')
    cg_id = models.CharField(max_length=20, unique=True, blank=True)
    full_name = models.CharField(max_length=200, blank=True)

    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, blank=True)
    receive_emergency_alerts = models.BooleanField(default=True)
    priority_contact = models.BooleanField(default=False)
    caregiver_type = models.CharField(max_length=20, choices=CAREGIVER_TYPE_CHOICES, default='personal')
    relation = models.CharField(max_length=30, choices=RELATION_CHOICES, default='family_member')
    license_number = models.CharField(max_length=50, blank=True)
    hospital_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    bio = models.TextField(blank=True)
    profile_photo = models.ImageField(upload_to='profiles/caregivers/', null=True, blank=True)
    organization = models.CharField(max_length=200, blank=True)
    organization_name = models.CharField(max_length=200, blank=True)
    specialization = models.CharField(max_length=200, blank=True)
    assigned_patient = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='primary_caregiver_profile_link', limit_choices_to={'role': 'patient'},
    )
    access_level = models.CharField(max_length=30, default='standard', blank=True)
    assignment_start_date = models.DateField(null=True, blank=True)
    assignment_end_date = models.DateField(null=True, blank=True)
    assignment_status = models.CharField(max_length=15, default='active', blank=True)
    onboarding_completed = models.BooleanField(default=False)
    shift_start = models.TimeField(null=True, blank=True)
    shift_end = models.TimeField(null=True, blank=True)
    emergency_contact = models.CharField(max_length=100, blank=True)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'caregiver_profile'

    def save(self, *args, **kwargs):
        if not self.cg_id:
            from apps.profiles.profile_bridge import generate_public_id
            cid = generate_public_id('caregiver')
            while CaregiverProfile.objects.filter(cg_id=cid).exists():
                cid = generate_public_id('caregiver')
            self.cg_id = cid
        if not self.organization_name and self.organization:
            self.organization_name = self.organization
        if not self.full_name:
            self.full_name = self.user.get_full_name()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Caregiver: {self.full_name or self.user.get_full_name()} ({self.caregiver_type})"


class CaregiverPatientAssignment(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('pending', 'Pending'),
        ('rejected', 'Rejected'),
    ]
    caregiver = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='caregiver_assignments')
    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='caregiver_patient_assignments')
    assigned_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='caregiver_assigned_by')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)
    can_mark_medicines = models.BooleanField(default=True)
    can_manage_appointments = models.BooleanField(default=True)
    can_upload_reports = models.BooleanField(default=True)
    can_log_activities = models.BooleanField(default=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    disconnected_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='caregiver_disconnections',
    )
    disconnect_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('caregiver', 'patient')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.caregiver.get_full_name()} cares for {self.patient.get_full_name()}"


class PatientCaregiverRecord(models.Model):
    """Caregiver information linked to a patient (display + optional system user access)."""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ]
    ASSIGNED_BY_CHOICES = [
        ('family', 'Family'),
        ('doctor', 'Doctor'),
        ('patient', 'Patient'),
        ('caregiver', 'Caregiver'),
    ]

    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='caregiver_records')
    caregiver_user = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='patient_caregiver_records',
    )
    caregiver_name = models.CharField(max_length=200)
    organization = models.CharField(max_length=200, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    caregiver_type = models.CharField(max_length=30, choices=CAREGIVER_TYPE_CHOICES, default='personal')
    emergency_contact = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    assigned_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='caregiver_records_assigned',
    )
    assigned_by_label = models.CharField(max_length=20, choices=ASSIGNED_BY_CHOICES, default='doctor')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    assignment = models.OneToOneField(
        CaregiverPatientAssignment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='caregiver_record',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.caregiver_name} → {self.patient.get_full_name()}"

    @property
    def type_display(self):
        return dict(CAREGIVER_TYPE_CHOICES).get(self.caregiver_type, self.caregiver_type)

    @property
    def assigned_by_display(self):
        return dict(self.ASSIGNED_BY_CHOICES).get(self.assigned_by_label, self.assigned_by_label)


class HospitalCaregiverAssignment(models.Model):
    """Hospital/clinical caregiver assigned by a doctor — separate from patient profile caregivers."""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('removed', 'Removed'),
        ('replaced', 'Replaced'),
    ]
    ROLE_CHOICES = HOSPITAL_ROLE_CHOICES
    DEPARTMENT_CHOICES = HOSPITAL_DEPARTMENT_CHOICES
    DURATION_CHOICES = HOSPITAL_DURATION_CHOICES

    patient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='hospital_caregiver_assignments')
    assigned_by_doctor = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='hospital_caregivers_assigned',
    )
    caregiver_name = models.CharField(max_length=200)
    caregiver_role = models.CharField(max_length=30, choices=ROLE_CHOICES, default='hospital_caregiver')
    department = models.CharField(max_length=30, choices=DEPARTMENT_CHOICES, default='general_care')
    contact_number = models.CharField(max_length=20, blank=True)
    responsibilities = models.TextField(blank=True)
    duration_type = models.CharField(max_length=15, choices=DURATION_CHOICES, default='permanent')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='active')
    caregiver_user = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hospital_caregiver_roles',
    )
    system_assignment = models.OneToOneField(
        CaregiverPatientAssignment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hospital_assignment',
    )
    deactivated_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hospital_caregivers_removed',
    )
    removal_reason = models.TextField(blank=True)
    replaced_by = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='replaced_assignment',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.caregiver_name} → {self.patient.get_full_name()} ({self.get_status_display()})"

    @property
    def role_display(self):
        return dict(self.ROLE_CHOICES).get(self.caregiver_role, self.caregiver_role)

    @property
    def department_display(self):
        return dict(self.DEPARTMENT_CHOICES).get(self.department, self.department)

    @property
    def duration_display(self):
        if self.duration_type == 'permanent':
            return 'Ongoing support'
        if self.start_date and self.end_date:
            return f"{self.start_date.strftime('%b %d')} – {self.end_date.strftime('%b %d, %Y')}"
        if self.start_date:
            return f"From {self.start_date.strftime('%b %d, %Y')}"
        return 'Temporary'

    @property
    def is_operational(self):
        return self.status == 'active' and self.system_assignment is not None


def get_hospital_caregiver_for_patient(patient, doctor=None):
    """Active or inactive hospital caregiver assigned by doctor."""
    qs = HospitalCaregiverAssignment.objects.filter(
        patient=patient,
        status__in=('active', 'inactive'),
    ).select_related('assigned_by_doctor', 'caregiver_user', 'system_assignment')
    if doctor:
        qs = qs.filter(assigned_by_doctor=doctor)
    return qs.order_by('-created_at').first()


def get_doctor_hospital_assignments(doctor):
    """All current hospital caregiver assignments for a doctor's patients."""
    return HospitalCaregiverAssignment.objects.filter(
        assigned_by_doctor=doctor,
        status__in=('active', 'inactive'),
    ).select_related(
        'patient', 'patient__patient_profile', 'caregiver_user', 'system_assignment',
    ).order_by('-created_at')


def get_patient_profile_caregiver(patient):
    """Patient-side family/private caregiver — NOT doctor hospital assignments."""
    record = PatientCaregiverRecord.objects.filter(
        patient=patient, status='active',
    ).exclude(assigned_by_label='doctor').select_related('caregiver_user', 'assigned_by').first()
    if record:
        return record
    assignment = CaregiverPatientAssignment.objects.filter(
        patient=patient, status='active',
    ).exclude(
        assigned_by__role='doctor',
    ).select_related('caregiver', 'caregiver__caregiver_profile', 'assigned_by').first()
    if not assignment:
        return None
    try:
        profile = assignment.caregiver.caregiver_profile
        cg_type = profile.caregiver_type
        org = profile.hospital_name
        phone = profile.phone
    except Exception:
        cg_type = 'personal'
        org = ''
        phone = assignment.caregiver.phone or ''
    assigned_label = 'patient'
    if assignment.assigned_by:
        if assignment.assigned_by.role == 'patient':
            assigned_label = 'patient'
        elif assignment.assigned_by == assignment.patient:
            assigned_label = 'family'
        else:
            assigned_label = 'caregiver'
    return type('CaregiverInfo', (), {
        'caregiver_name': assignment.caregiver.get_full_name(),
        'organization': org,
        'contact_number': phone or assignment.caregiver.phone,
        'caregiver_type': cg_type,
        'type_display': dict(CAREGIVER_TYPE_CHOICES).get(cg_type, cg_type),
        'emergency_contact': '',
        'notes': assignment.notes,
        'assigned_by_display': dict(PatientCaregiverRecord.ASSIGNED_BY_CHOICES).get(assigned_label, assigned_label),
        'status': 'active',
        'caregiver_user': assignment.caregiver,
        'is_patient_side': True,
    })()


def get_active_caregiver_for_patient(patient, doctor=None):
    """For doctor views: hospital caregiver. For others: patient profile caregiver."""
    if doctor:
        return get_hospital_caregiver_for_patient(patient, doctor=doctor)
    record = PatientCaregiverRecord.objects.filter(
        patient=patient, status='active',
    ).exclude(assigned_by_label='doctor').select_related('caregiver_user', 'assigned_by', 'assignment').first()
    if record:
        return record
    return get_patient_profile_caregiver(patient)


def get_any_active_caregiver_for_patient(patient):
    """
    Unified check: does the patient have ANY active caregiver (hospital, family, personal, etc.)?
    Returns a normalized dict for doctor assignment conflict UI, or None.
    """
    hospital = HospitalCaregiverAssignment.objects.filter(
        patient=patient, status='active',
    ).select_related('assigned_by_doctor').order_by('-created_at').first()
    if hospital:
        return {
            'source': 'hospital',
            'source_id': hospital.id,
            'caregiver_name': hospital.caregiver_name,
            'type_display': hospital.role_display,
            'role_display': hospital.role_display,
            'department_display': hospital.department_display,
            'organization': hospital.department_display,
            'contact_number': hospital.contact_number,
            'assigned_on': hospital.created_at,
            'status': 'active',
            'status_display': 'Active',
            'assigned_by_display': f"Dr. {hospital.assigned_by_doctor.get_full_name()}",
            'is_hospital': True,
            'hospital_assignment': hospital,
        }

    record = PatientCaregiverRecord.objects.filter(
        patient=patient, status='active',
    ).select_related('assigned_by', 'caregiver_user').order_by('-created_at').first()
    if record:
        return {
            'source': 'profile_record',
            'source_id': record.id,
            'caregiver_name': record.caregiver_name,
            'type_display': record.type_display,
            'organization': record.organization or '—',
            'contact_number': record.contact_number,
            'assigned_on': record.created_at,
            'status': 'active',
            'status_display': 'Active',
            'assigned_by_display': record.assigned_by_display,
            'is_hospital': False,
            'hospital_assignment': None,
        }

    assignment = CaregiverPatientAssignment.objects.filter(
        patient=patient, status='active',
    ).select_related('caregiver', 'caregiver__caregiver_profile', 'assigned_by').order_by('-created_at').first()
    if assignment:
        try:
            profile = assignment.caregiver.caregiver_profile
            cg_type = profile.caregiver_type
            org = profile.hospital_name or '—'
            phone = profile.phone
        except Exception:
            cg_type = 'personal'
            org = '—'
            phone = assignment.caregiver.phone or ''
        assigned_label = 'patient'
        if assignment.assigned_by:
            if assignment.assigned_by.role == 'patient':
                assigned_label = 'patient'
            elif assignment.assigned_by == assignment.patient:
                assigned_label = 'family'
            else:
                assigned_label = 'caregiver'
        return {
            'source': 'system_assignment',
            'source_id': assignment.id,
            'caregiver_name': assignment.caregiver.get_full_name(),
            'type_display': dict(CAREGIVER_TYPE_CHOICES).get(cg_type, cg_type),
            'organization': org,
            'contact_number': phone or assignment.caregiver.phone or '',
            'assigned_on': assignment.created_at,
            'status': 'active',
            'status_display': 'Active',
            'assigned_by_display': dict(PatientCaregiverRecord.ASSIGNED_BY_CHOICES).get(
                assigned_label, assigned_label,
            ),
            'is_hospital': False,
            'hospital_assignment': None,
        }

    return None


def patient_has_active_caregiver(patient):
    return get_any_active_caregiver_for_patient(patient) is not None


def get_active_assignment_for_caregiver(caregiver):
    """One caregiver → one active patient."""
    return CaregiverPatientAssignment.objects.filter(
        caregiver=caregiver, status='active',
    ).select_related('patient', 'patient__patient_profile').first()


def get_pending_assignment_for_caregiver(caregiver):
    return CaregiverPatientAssignment.objects.filter(
        caregiver=caregiver, status='pending',
    ).select_related('patient').first()


class CaregiverCareNote(models.Model):
    assignment = models.ForeignKey(
        CaregiverPatientAssignment, on_delete=models.CASCADE, related_name='care_notes',
    )
    caregiver = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='care_notes_written')
    note = models.TextField()
    is_private = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note by {self.caregiver.get_full_name()} ({self.created_at:%Y-%m-%d})"


class CaregiverDailyLog(models.Model):
    LOG_TYPES = [
        ('medicine', 'Medicine Given'),
        ('vitals', 'Vitals Checked'),
        ('doctor_contact', 'Doctor Contacted'),
        ('appointment', 'Appointment Booked'),
        ('meals', 'Meals Completed'),
        ('other', 'Other'),
    ]
    assignment = models.ForeignKey(
        CaregiverPatientAssignment, on_delete=models.CASCADE, related_name='daily_logs',
    )
    caregiver = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='daily_care_logs')
    log_type = models.CharField(max_length=20, choices=LOG_TYPES, default='other')
    entry = models.CharField(max_length=500)
    log_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-log_date', '-created_at']

    def __str__(self):
        return f"{self.get_log_type_display()}: {self.entry[:40]}"


class CaregiverActivityTimeline(models.Model):
    ACTION_TYPES = [
        ('medicine_taken', 'Medicine Marked Taken'),
        ('medicine_skipped', 'Medicine Skipped'),
        ('medicine_missed', 'Medicine Missed'),
        ('appointment_booked', 'Appointment Booked'),
        ('appointment_cancelled', 'Appointment Cancelled'),
        ('emergency_requested', 'Emergency Consultation Requested'),
        ('message_sent', 'Doctor Messaged'),
        ('health_question', 'Health Question Completed'),
        ('activity_logged', 'Activity Logged'),
        ('connection_sent', 'Connection Request Sent'),
        ('connection_accepted', 'Connection Accepted'),
        ('disconnected', 'Patient Disconnected'),
        ('other', 'Other'),
    ]
    assignment = models.ForeignKey(
        CaregiverPatientAssignment, on_delete=models.CASCADE, related_name='timeline_entries',
    )
    caregiver = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='caregiver_timeline')
    action_type = models.CharField(max_length=30, choices=ACTION_TYPES, default='other')
    description = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_action_type_display()} — {self.created_at:%Y-%m-%d %H:%M}"
