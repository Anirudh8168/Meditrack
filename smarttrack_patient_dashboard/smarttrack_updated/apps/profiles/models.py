from django.db import models
from apps.accounts.models import CustomUser


class PatientProfile(models.Model):
    BLOOD_GROUP_CHOICES = [
        ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
        ('O+', 'O+'), ('O-', 'O-'), ('AB+', 'AB+'), ('AB-', 'AB-'),
    ]
    GENDER_CHOICES = [('male', 'Male'), ('female', 'Female'), ('other', 'Other')]
    ACTIVITY_CHOICES = [('sedentary', 'Sedentary'), ('moderate', 'Moderate'), ('active', 'Active')]
    DIABETES_CHOICES = [('no', 'No'), ('type1', 'Type 1'), ('type2', 'Type 2'), ('pre', 'Pre-diabetic')]
    SMOKING_CHOICES = [('no', 'Non-smoker'), ('occasional', 'Occasional'), ('regular', 'Regular'), ('ex', 'Ex-smoker')]
    ALCOHOL_CHOICES = [('no', 'None'), ('occasional', 'Occasional'), ('moderate', 'Moderate'), ('heavy', 'Heavy')]
    EXERCISE_CHOICES = [('never', 'Never'), ('rarely', 'Rarely'), ('sometimes', 'Sometimes'), ('daily', 'Daily')]
    RISK_LEVEL_CHOICES = [
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='patient_profile')
    patient_id = models.CharField(max_length=20, unique=True, blank=True)

    first_name = models.CharField(max_length=100, blank=True)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    profile_photo = models.ImageField(upload_to='profiles/patients/', null=True, blank=True)

    phone_number = models.CharField(max_length=20, blank=True)
    alternate_number = models.CharField(max_length=20, blank=True)

    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    age_cached = models.PositiveSmallIntegerField(null=True, blank=True)
    blood_group = models.CharField(max_length=5, choices=BLOOD_GROUP_CHOICES, blank=True)

    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='India', blank=True)
    pincode = models.CharField(max_length=20, blank=True)

    height = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    bmi = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    allergies = models.TextField(blank=True)
    medical_conditions = models.TextField(blank=True, help_text='Primary / secondary conditions summary')
    chronic_diseases = models.TextField(blank=True)
    primary_diagnosis = models.TextField(blank=True)
    secondary_conditions = models.TextField(blank=True)
    current_medications = models.TextField(blank=True)
    blood_pressure = models.CharField(max_length=20, blank=True)
    diabetes = models.CharField(max_length=10, choices=DIABETES_CHOICES, blank=True)
    medical_history = models.TextField(blank=True)

    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_number = models.CharField(max_length=20, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    emergency_contact_relation = models.CharField(max_length=50, blank=True)
    blood_donor_contact = models.CharField(max_length=20, blank=True)

    preferred_hospital = models.CharField(max_length=200, blank=True)
    hospital_name = models.CharField(max_length=200, blank=True)
    primary_doctor_name = models.CharField(max_length=200, blank=True)
    doctor_contact = models.CharField(max_length=20, blank=True)
    assigned_doctor = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_patients', limit_choices_to={'role': 'doctor'},
    )

    risk_level = models.CharField(max_length=10, choices=RISK_LEVEL_CHOICES, default='low', blank=True)
    risk_score = models.PositiveSmallIntegerField(default=0)

    notification_alerts = models.BooleanField(default=True)
    enable_sos = models.BooleanField(default=False)
    privacy_mode = models.BooleanField(default=False)
    activity_level = models.CharField(max_length=20, choices=ACTIVITY_CHOICES, blank=True)
    sleep_hours = models.IntegerField(null=True, blank=True)
    smoking_habit = models.CharField(max_length=20, choices=SMOKING_CHOICES, blank=True)
    alcohol_consumption = models.CharField(max_length=20, choices=ALCOHOL_CHOICES, blank=True)
    exercise_frequency = models.CharField(max_length=20, choices=EXERCISE_CHOICES, blank=True)
    preferred_language = models.CharField(max_length=50, default='English')
    onboarding_completed = models.BooleanField(default=False)
    step_completed = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'patient_profile'

    def __str__(self):
        return f'Patient: {self.full_name or self.user.username}'

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        name = ' '.join(p for p in parts if p).strip()
        return name or self.user.get_full_name()

    @property
    def age(self):
        if self.date_of_birth:
            from apps.profiles.profile_bridge import compute_age
            return compute_age(self.date_of_birth)
        return self.age_cached

    def save(self, *args, **kwargs):
        if self.date_of_birth:
            from apps.profiles.profile_bridge import compute_age
            self.age_cached = compute_age(self.date_of_birth)
        if not self.patient_id:
            from apps.profiles.profile_bridge import generate_public_id
            pid = generate_public_id('patient')
            while PatientProfile.objects.filter(patient_id=pid).exists():
                pid = generate_public_id('patient')
            self.patient_id = pid
        if not self.medical_conditions and self.primary_diagnosis:
            self.medical_conditions = self.primary_diagnosis
        if not self.emergency_contact_number and self.emergency_contact_phone:
            self.emergency_contact_number = self.emergency_contact_phone
        if not self.preferred_hospital and self.hospital_name:
            self.preferred_hospital = self.hospital_name
        super().save(*args, **kwargs)
        from apps.profiles.profile_bridge import sync_user_name_cache
        sync_user_name_cache(self.user)


class DoctorProfile(models.Model):
    GENDER_CHOICES = [('male', 'Male'), ('female', 'Female'), ('other', 'Other')]
    SPECIALIZATION_CHOICES = [
        ('general', 'General Physician'), ('cardiology', 'Cardiology'),
        ('neurology', 'Neurology'), ('orthopedics', 'Orthopedics'),
        ('pediatrics', 'Pediatrics'), ('dermatology', 'Dermatology'),
        ('psychiatry', 'Psychiatry'), ('oncology', 'Oncology'),
        ('gynecology', 'Gynecology'), ('ophthalmology', 'Ophthalmology'),
        ('ent', 'ENT'), ('urology', 'Urology'), ('endocrinology', 'Endocrinology'),
        ('gastroenterology', 'Gastroenterology'), ('pulmonology', 'Pulmonology'),
        ('nephrology', 'Nephrology'), ('other', 'Other'),
    ]
    CONSULTATION_MODE_CHOICES = [
        ('in_person', 'In-Person'),
        ('video', 'Video Consultation'),
        ('both', 'Both'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='doctor_profile')
    doctor_id = models.CharField(max_length=20, unique=True, blank=True)

    full_name = models.CharField(max_length=200, blank=True)
    profile_photo = models.ImageField(upload_to='profiles/doctors/', null=True, blank=True)

    specialization = models.CharField(max_length=100, choices=SPECIALIZATION_CHOICES, blank=True)
    specialty = models.CharField(max_length=100, choices=SPECIALIZATION_CHOICES, blank=True)
    qualification = models.CharField(max_length=200, blank=True)
    years_of_experience = models.IntegerField(null=True, blank=True)

    hospital_name = models.CharField(max_length=200, blank=True)
    hospital_address = models.TextField(blank=True)
    hospital_phone = models.CharField(max_length=20, blank=True)
    clinic_address = models.TextField(blank=True)

    license_number = models.CharField(max_length=50, blank=True)
    registration_number = models.CharField(max_length=50, blank=True)
    license_document = models.FileField(upload_to='licenses/', null=True, blank=True)

    consultation_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    video_consultation_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    emergency_video_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    emergency_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    phone = models.CharField(max_length=20, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default='India', blank=True)

    availability_schedule = models.TextField(blank=True)
    consultation_hours = models.CharField(max_length=100, blank=True)
    consultation_mode = models.CharField(max_length=20, choices=CONSULTATION_MODE_CHOICES, default='both')
    available_for_consultation = models.BooleanField(default=True)
    max_patients_per_day = models.IntegerField(default=20)
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)

    bio = models.TextField(blank=True)
    notification_alerts = models.BooleanField(default=True)
    real_time_alerts = models.BooleanField(default=True)
    preferred_language = models.CharField(max_length=50, default='English')
    linkedin = models.URLField(blank=True)
    twitter = models.URLField(blank=True)
    onboarding_completed = models.BooleanField(default=False)
    step_completed = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'doctor_profile'

    def __str__(self):
        return f'Dr. {self.full_name or self.user.get_full_name()}'

    def save(self, *args, **kwargs):
        if not self.doctor_id:
            from apps.profiles.profile_bridge import generate_public_id
            did = generate_public_id('doctor')
            while DoctorProfile.objects.filter(doctor_id=did).exists():
                did = generate_public_id('doctor')
            self.doctor_id = did
        if not self.specialty and self.specialization:
            self.specialty = self.specialization
        if not self.specialization and self.specialty:
            self.specialization = self.specialty
        if not self.clinic_address and self.hospital_address:
            self.clinic_address = self.hospital_address
        if not self.availability_schedule and self.consultation_hours:
            self.availability_schedule = self.consultation_hours
        if self.emergency_fee is None and self.emergency_video_fee is not None:
            self.emergency_fee = self.emergency_video_fee
        if self.emergency_video_fee is None and self.emergency_fee is not None:
            self.emergency_video_fee = self.emergency_fee
        super().save(*args, **kwargs)
        from apps.profiles.profile_bridge import sync_user_name_cache
        if self.full_name:
            parts = self.full_name.split(' ', 1)
            self.user.first_name = parts[0]
            self.user.last_name = parts[1] if len(parts) > 1 else ''
            self.user.save(update_fields=['first_name', 'last_name'])
