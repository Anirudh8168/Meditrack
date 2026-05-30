"""
Management command to seed realistic demo data for SmartTrack.
Usage: python manage.py seed_demo_data
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta, datetime
import random


class Command(BaseCommand):
    help = 'Seeds demo data: patients, doctors, caregivers, medicines, appointments'

    def handle(self, *args, **kwargs):
        from apps.accounts.models import CustomUser
        from apps.profiles.models import PatientProfile, DoctorProfile
        from apps.medicines.models import Medicine, MedicineLog, RiskScore, FamilyContact, Activity
        from apps.appointments.models import Appointment
        from apps.connections.models import DoctorPatientConnection
        from apps.caregiver.models import CaregiverProfile, CaregiverPatientAssignment
        from apps.notifications.models import Notification

        self.stdout.write("🌱 Seeding SmartTrack demo data...")

        # Create 3 doctors
        doctors_data = [
            {'username': 'dr_sharma', 'first': 'Rajesh', 'last': 'Sharma', 'email': 'dr.sharma@smarttrack.com',
             'specialty': 'cardiology', 'hospital': 'Apollo Hospital', 'exp': 15, 'fee': 800},
            {'username': 'dr_patel', 'first': 'Priya', 'last': 'Patel', 'email': 'dr.patel@smarttrack.com',
             'specialty': 'general', 'hospital': 'City Medical Center', 'exp': 10, 'fee': 500},
            {'username': 'dr_mehta', 'first': 'Amit', 'last': 'Mehta', 'email': 'dr.mehta@smarttrack.com',
             'specialty': 'neurology', 'hospital': 'Fortis Hospital', 'exp': 12, 'fee': 1000},
        ]
        doctors = []
        for d in doctors_data:
            user, created = CustomUser.objects.get_or_create(
                username=d['username'],
                defaults={
                    'first_name': d['first'], 'last_name': d['last'],
                    'email': d['email'], 'role': 'doctor',
                    'profile_completed': True, 'phone': f'+91 98765{random.randint(10000,99999)}'
                }
            )
            if created:
                user.set_password('demo@1234')
                user.save()
            DoctorProfile.objects.update_or_create(
                user=user,
                defaults={
                    'specialty': d['specialty'], 'hospital_name': d['hospital'],
                    'years_of_experience': d['exp'], 'consultation_fee': d['fee'],
                    'bio': f'Experienced {d["specialty"]} specialist with {d["exp"]} years of practice.',
                    'license_number': f'MCI{random.randint(100000,999999)}',
                    'available_for_consultation': True, 'step_completed': 3,
                    'max_patients_per_day': 20, 'consultation_mode': 'both',
                }
            )
            doctors.append(user)
            if created:
                self.stdout.write(f"  ✅ Doctor: Dr. {d['first']} {d['last']} | login: {d['username']} / demo@1234")

        # Create 5 patients
        patients_data = [
            {'username': 'patient_raj', 'first': 'Rahul', 'last': 'Verma', 'email': 'rahul@demo.com',
             'dob': '1985-03-15', 'blood': 'B+', 'diagnosis': 'Hypertension', 'gender': 'male'},
            {'username': 'patient_priya', 'first': 'Priya', 'last': 'Singh', 'email': 'priya@demo.com',
             'dob': '1990-07-22', 'blood': 'A+', 'diagnosis': 'Type 2 Diabetes', 'gender': 'female'},
            {'username': 'patient_arun', 'first': 'Arun', 'last': 'Kumar', 'email': 'arun@demo.com',
             'dob': '1975-11-08', 'blood': 'O+', 'diagnosis': 'Chronic Back Pain', 'gender': 'male'},
            {'username': 'patient_sunita', 'first': 'Sunita', 'last': 'Rao', 'email': 'sunita@demo.com',
             'dob': '1968-05-30', 'blood': 'AB+', 'diagnosis': 'Thyroid Disorder', 'gender': 'female'},
            {'username': 'patient_vikram', 'first': 'Vikram', 'last': 'Joshi', 'email': 'vikram@demo.com',
             'dob': '1992-09-14', 'blood': 'O-', 'diagnosis': 'Asthma', 'gender': 'male'},
        ]
        patients = []
        for p in patients_data:
            user, created = CustomUser.objects.get_or_create(
                username=p['username'],
                defaults={
                    'first_name': p['first'], 'last_name': p['last'],
                    'email': p['email'], 'role': 'patient',
                    'profile_completed': True, 'phone': f'+91 99876{random.randint(10000,99999)}'
                }
            )
            if created:
                user.set_password('demo@1234')
                user.save()
            PatientProfile.objects.update_or_create(
                user=user,
                defaults={
                    'date_of_birth': p['dob'], 'blood_group': p['blood'],
                    'primary_diagnosis': p['diagnosis'], 'gender': p['gender'],
                    'height': random.randint(155, 185), 'weight': random.randint(55, 90),
                    'emergency_contact_name': 'Family Contact',
                    'emergency_contact_phone': '+91 9876500001',
                    'emergency_contact_relation': 'spouse',
                    'notification_alerts': True, 'step_completed': 3,
                    'allergies': 'Penicillin', 'city': 'Mumbai', 'state': 'Maharashtra',
                    'country': 'India',
                }
            )
            patients.append(user)
            if created:
                self.stdout.write(f"  ✅ Patient: {p['first']} {p['last']} | login: {p['username']} / demo@1234")

        # Create 1 caregiver
        cg_user, created = CustomUser.objects.get_or_create(
            username='caregiver_demo',
            defaults={
                'first_name': 'Meena', 'last_name': 'Nair', 'email': 'meena@demo.com',
                'role': 'caregiver', 'profile_completed': True, 'phone': '+91 88765 43210'
            }
        )
        if created:
            cg_user.set_password('demo@1234')
            cg_user.save()
        CaregiverProfile.objects.update_or_create(
            user=cg_user,
            defaults={
                'caregiver_type': 'personal', 'relation': 'family_member',
                'bio': 'Experienced family caregiver for elderly patients.',
            }
        )
        if created:
            self.stdout.write(f"  ✅ Caregiver: Meena Nair | login: caregiver_demo / demo@1234")

        # Connect doctors to patients
        for i, patient in enumerate(patients):
            doctor = doctors[i % len(doctors)]
            DoctorPatientConnection.objects.get_or_create(
                patient=patient, doctor=doctor,
                defaults={'status': 'accepted', 'requested_by': patient}
            )

        # Connect caregiver to first 2 patients
        for patient in patients[:2]:
            CaregiverPatientAssignment.objects.get_or_create(
                caregiver=cg_user, patient=patient,
                defaults={
                    'status': 'active', 'assigned_by': cg_user,
                    'can_mark_medicines': True, 'can_manage_appointments': True,
                    'can_log_activities': True,
                }
            )

        # Add Family Contacts
        for patient in patients:
            FamilyContact.objects.get_or_create(
                patient=patient, name='Emergency Contact',
                defaults={
                    'phone': '+91 9876500001', 'email': 'emergency@demo.com',
                    'relation': 'spouse', 'is_primary': True, 'notify_on_missed': True,
                    'missed_count_threshold': 3,
                }
            )

        # Add medicines for each patient
        today = date.today()
        meds_config = [
            {'name': 'Amlodipine 5mg', 'dosage': '5mg', 'freq': 'once_daily', 'slots': ['08:00'], 'color': 'blue'},
            {'name': 'Metformin 500mg', 'dosage': '500mg', 'freq': 'twice_daily', 'slots': ['08:00', '20:00'], 'color': 'green'},
            {'name': 'Atorvastatin 10mg', 'dosage': '10mg', 'freq': 'once_daily', 'slots': ['21:00'], 'color': 'red'},
            {'name': 'Aspirin 75mg', 'dosage': '75mg', 'freq': 'once_daily', 'slots': ['09:00'], 'color': 'orange'},
            {'name': 'Pantoprazole 40mg', 'dosage': '40mg', 'freq': 'twice_daily', 'slots': ['07:30', '19:30'], 'color': 'purple'},
            {'name': 'Salbutamol Inhaler', 'dosage': '100mcg', 'freq': 'as_needed', 'slots': ['08:00', '20:00'], 'color': 'blue'},
        ]

        for i, patient in enumerate(patients):
            doctor = doctors[i % len(doctors)]
            meds_to_add = random.sample(meds_config, random.randint(2, 4))
            for mc in meds_to_add:
                med, _ = Medicine.objects.get_or_create(
                    patient=patient, name=mc['name'],
                    defaults={
                        'prescribed_by': doctor,
                        'dosage': mc['dosage'],
                        'frequency': mc['freq'],
                        'time_slots': mc['slots'],
                        'start_date': today - timedelta(days=random.randint(5, 30)),
                        'end_date': today + timedelta(days=random.randint(10, 90)),
                        'stock_quantity': random.randint(5, 30),
                        'low_stock_threshold': 7,
                        'critical_stock_threshold': 3,
                        'color': mc['color'],
                        'is_active': True,
                        'instructions': 'Take with food and water.',
                    }
                )
                # Add past medicine logs (7 days)
                for day_offset in range(7, 0, -1):
                    d = today - timedelta(days=day_offset)
                    for slot in mc['slots']:
                        h, m_ = map(int, slot.split(':'))
                        slot_dt = timezone.make_aware(datetime(d.year, d.month, d.day, h, m_))
                        # 80% compliance rate
                        status = 'taken' if random.random() < 0.80 else 'missed'
                        MedicineLog.objects.get_or_create(
                            medicine=med, patient=patient, scheduled_time=slot_dt,
                            defaults={
                                'marked_by': patient, 'status': status,
                                'taken_at': slot_dt if status == 'taken' else None,
                            }
                        )

        # Add Appointments
        apt_statuses = ['confirmed', 'confirmed', 'pending', 'completed', 'completed']
        for i, patient in enumerate(patients):
            doctor = doctors[i % len(doctors)]
            # Upcoming
            Appointment.objects.get_or_create(
                patient=patient, doctor=doctor,
                appointment_date=today + timedelta(days=random.randint(1, 14)),
                defaults={
                    'appointment_time': '10:30',
                    'status': random.choice(['pending', 'confirmed']),
                    'reason': 'Regular checkup',
                    'appointment_type': 'in_person',
                    'notes': 'Monthly follow-up',
                }
            )
            # Past
            Appointment.objects.get_or_create(
                patient=patient, doctor=doctor,
                appointment_date=today - timedelta(days=random.randint(5, 30)),
                defaults={
                    'appointment_time': '11:00',
                    'status': 'completed',
                    'reason': 'Follow-up consultation',
                    'appointment_type': 'in_person',
                }
            )

        # Add notifications
        for patient in patients:
            Notification.objects.get_or_create(
                user=patient,
                title='🎉 Welcome to SmartTrack!',
                defaults={
                    'message': 'Your health journey starts here. Keep tracking your medicines and appointments.',
                    'notification_type': 'info',
                }
            )
            Notification.objects.get_or_create(
                user=patient,
                title='💊 Medicine Reminder Set',
                defaults={
                    'message': 'Your doctor has set up your medicine reminders. Check your medicine schedule.',
                    'notification_type': 'medicine',
                }
            )

        # Add activities
        activity_types = ['exercise', 'vitals', 'symptom', 'diet']
        for patient in patients:
            for i in range(3):
                Activity.objects.create(
                    patient=patient, logged_by=patient,
                    activity_type=random.choice(activity_types),
                    title=f'Daily health log #{i+1}',
                    description='Logged by patient',
                    duration_minutes=random.randint(15, 60)
                )

        # Calculate risk scores
        from apps.medicines.views import calculate_risk_score
        for patient in patients:
            calculate_risk_score(patient)

        self.stdout.write(self.style.SUCCESS("\n✅ Demo data seeded successfully!"))
        self.stdout.write("\n📋 Login Credentials:")
        self.stdout.write("  Doctors: dr_sharma, dr_patel, dr_mehta / demo@1234")
        self.stdout.write("  Patients: patient_raj, patient_priya, patient_arun, patient_sunita, patient_vikram / demo@1234")
        self.stdout.write("  Caregiver: caregiver_demo / demo@1234")
        self.stdout.write("  Admin: python manage.py createsuperuser")
