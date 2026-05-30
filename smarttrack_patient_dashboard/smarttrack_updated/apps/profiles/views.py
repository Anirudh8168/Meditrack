from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import PatientProfile, DoctorProfile
from apps.accounts.models import CustomUser


@login_required
def complete_profile(request):
    user = request.user
    if user.role == 'patient':
        return redirect('/profile/patient/')
    elif user.role == 'doctor':
        return redirect('/profile/doctor/')
    elif user.role == 'caregiver':
        return redirect('/profile/caregiver/')
    else:
        user.profile_completed = True
        user.save()
        return redirect(user.get_dashboard_url())


@login_required
def patient_profile(request):
    user = request.user
    profile, _ = PatientProfile.objects.get_or_create(user=user)
    if request.method == 'POST':
        # Step 1: Personal
        full_name = request.POST.get('full_name', '').strip()
        if full_name:
            parts = full_name.split(' ', 2)
            profile.first_name = parts[0]
            profile.middle_name = parts[1] if len(parts) > 2 else ''
            profile.last_name = parts[-1] if len(parts) > 1 else ''
        profile.phone_number = request.POST.get('phone', profile.phone_number)
        profile.alternate_number = request.POST.get('alternate_number', profile.alternate_number)

        profile.date_of_birth = request.POST.get('date_of_birth') or None
        profile.gender = request.POST.get('gender', '')
        profile.blood_group = request.POST.get('blood_group', '')
        profile.address = request.POST.get('address', '')
        profile.city = request.POST.get('city', '')
        profile.state = request.POST.get('state', '')
        profile.pincode = request.POST.get('pincode', '')
        profile.country = request.POST.get('country', 'India')

        if request.FILES.get('profile_photo'):
            profile.profile_photo = request.FILES['profile_photo']

        # Step 2: Medical
        profile.primary_diagnosis = request.POST.get('primary_diagnosis', '')
        profile.medical_conditions = profile.primary_diagnosis or profile.medical_conditions
        profile.secondary_conditions = request.POST.get('secondary_conditions', '')
        profile.allergies = request.POST.get('allergies', '')
        profile.chronic_diseases = request.POST.get('chronic_diseases', '')
        profile.current_medications = request.POST.get('current_medications', '')
        profile.blood_pressure = request.POST.get('blood_pressure', '')
        profile.diabetes = request.POST.get('diabetes', '')
        profile.medical_history = request.POST.get('medical_history', '')
        profile.primary_doctor_name = request.POST.get('primary_doctor_name', '')
        profile.hospital_name = request.POST.get('hospital_name', '')
        profile.doctor_contact = request.POST.get('doctor_contact', '')
        profile.sleep_hours = request.POST.get('sleep_hours') or None

        h = request.POST.get('height')
        w = request.POST.get('weight')
        if h:
            profile.height = float(h)
        if w:
            profile.weight = float(w)
        if h and w:
            hm = float(h) / 100
            profile.bmi = round(float(w) / (hm * hm), 2)

        # Step 3: Emergency & Lifestyle
        profile.emergency_contact_name = request.POST.get('emergency_contact_name', '')
        profile.emergency_contact_phone = request.POST.get('emergency_contact_phone', '')
        profile.emergency_contact_number = profile.emergency_contact_phone
        profile.emergency_contact_relation = request.POST.get('emergency_contact_relation', '')
        profile.blood_donor_contact = request.POST.get('blood_donor_contact', '')
        profile.notification_alerts = bool(request.POST.get('notification_alerts'))
        profile.enable_sos = bool(request.POST.get('enable_sos'))
        profile.activity_level = request.POST.get('activity_level', '')
        profile.exercise_frequency = request.POST.get('exercise_frequency', '')
        profile.smoking_habit = request.POST.get('smoking_habit', '')
        profile.alcohol_consumption = request.POST.get('alcohol_consumption', '')

        profile.step_completed = 3
        profile.onboarding_completed = True
        profile.save()
        from apps.profiles.profile_bridge import sync_user_name_cache
        sync_user_name_cache(user)
        messages.success(request, '✅ Profile saved successfully! Welcome to SmartTrack.')
        return redirect('/dashboard/patient/')

    return render(request, 'profile/patient_profile.html', {
        'profile': profile,
        'user': user,
        'blood_groups': 'A+,A-,B+,B-,O+,O-,AB+,AB-'.split(','),
        'emergency_relations': 'spouse,parent,child,sibling,friend,caregiver,other'.split(','),
        'activity_levels': 'Sedentary,Moderate,Active'.split(','),
    })


@login_required
def doctor_profile(request):
    user = request.user
    profile, _ = DoctorProfile.objects.get_or_create(user=user)
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        if full_name:
            profile.full_name = full_name
            parts = full_name.split(' ', 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ''

        profile.phone = request.POST.get('phone', profile.phone)

        profile.date_of_birth = request.POST.get('date_of_birth') or None
        profile.gender = request.POST.get('gender', '')
        profile.address = request.POST.get('address', '')
        profile.city = request.POST.get('city', '')
        profile.state = request.POST.get('state', '')
        profile.pincode = request.POST.get('pincode', '')
        profile.country = request.POST.get('country', 'India')
        profile.license_number = request.POST.get('license_number', '')
        profile.specialty = request.POST.get('specialty', '')
        profile.years_of_experience = request.POST.get('years_of_experience') or None
        profile.hospital_name = request.POST.get('hospital_name', '')
        profile.hospital_address = request.POST.get('hospital_address', '')
        profile.hospital_phone = request.POST.get('hospital_phone', '')
        profile.consultation_fee = request.POST.get('consultation_fee') or None
        profile.video_consultation_fee = request.POST.get('video_consultation_fee') or None
        profile.emergency_video_fee = request.POST.get('emergency_video_fee') or None
        profile.emergency_fee = profile.emergency_video_fee
        profile.consultation_hours = request.POST.get('consultation_hours', '')
        profile.availability_schedule = profile.consultation_hours
        profile.clinic_address = profile.hospital_address or profile.clinic_address
        profile.bio = request.POST.get('bio', '')
        profile.linkedin = request.POST.get('linkedin', '')
        profile.max_patients_per_day = int(request.POST.get('max_patients_per_day', 20))
        profile.notification_alerts = bool(request.POST.get('notification_alerts'))
        profile.consultation_mode = request.POST.get('consultation_mode', 'both')

        if request.FILES.get('profile_photo'):
            profile.profile_photo = request.FILES['profile_photo']
        if request.FILES.get('license_document'):
            profile.license_document = request.FILES['license_document']

        profile.step_completed = 3
        profile.onboarding_completed = True
        profile.save()
        from apps.profiles.profile_bridge import sync_user_name_cache
        sync_user_name_cache(user)
        messages.success(request, '✅ Doctor profile saved successfully!')
        return redirect('/dashboard/doctor/')

    return render(request, 'profile/doctor_profile.html', {'profile': profile, 'user': user})


@login_required
def caregiver_profile(request):
    from apps.caregiver.models import CaregiverProfile
    user = request.user
    profile, _ = CaregiverProfile.objects.get_or_create(user=user)
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        if full_name:
            parts = full_name.split(' ', 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ''

        profile.date_of_birth = request.POST.get('date_of_birth') or None
        profile.gender = request.POST.get('gender', '')
        profile.caregiver_type = request.POST.get('caregiver_type', 'personal')
        profile.relation = request.POST.get('relation', 'family_member')
        profile.license_number = request.POST.get('license_number', '')
        profile.hospital_name = request.POST.get('hospital_name', '')
        profile.phone = request.POST.get('phone', '')
        profile.address = request.POST.get('address', '')
        profile.bio = request.POST.get('bio', '')
        profile.receive_emergency_alerts = bool(request.POST.get('receive_emergency_alerts'))
        profile.priority_contact = bool(request.POST.get('priority_contact'))
        if request.FILES.get('profile_photo'):
            profile.profile_photo = request.FILES['profile_photo']
        profile.save()
        user.profile_completed = True
        user.phone = request.POST.get('phone', user.phone)
        user.save()
        messages.success(request, '✅ Caregiver profile saved!')
        return redirect('/dashboard/caregiver/')

    return render(request, 'profile/caregiver_profile.html', {'profile': profile, 'user': user})


@login_required
def caregiver_settings(request):
    """Ongoing profile management for caregivers."""
    from apps.caregiver.models import CaregiverProfile
    user = request.user
    if user.role != 'caregiver':
        return redirect(user.get_dashboard_url())

    profile, _ = CaregiverProfile.objects.get_or_create(user=user)
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_profile':
            full_name = request.POST.get('full_name', '').strip()
            if full_name:
                parts = full_name.split(' ', 1)
                user.first_name = parts[0]
                user.last_name = parts[1] if len(parts) > 1 else ''
            user.phone = request.POST.get('phone', user.phone)
            user.save()

            profile.caregiver_type = request.POST.get('caregiver_type', profile.caregiver_type)
            profile.relation = request.POST.get('relation', profile.relation)
            profile.license_number = request.POST.get('license_number', profile.license_number)
            profile.hospital_name = request.POST.get('hospital_name', profile.hospital_name)
            profile.organization = request.POST.get('organization', profile.organization)
            profile.specialization = request.POST.get('specialization', profile.specialization)
            profile.phone = request.POST.get('phone', profile.phone)
            profile.address = request.POST.get('address', profile.address)
            profile.bio = request.POST.get('bio', profile.bio)
            profile.emergency_contact = request.POST.get('emergency_contact', profile.emergency_contact)
            shift_start = request.POST.get('shift_start')
            shift_end = request.POST.get('shift_end')
            if shift_start:
                from datetime import datetime
                try:
                    profile.shift_start = datetime.strptime(shift_start, '%H:%M').time()
                except ValueError:
                    pass
            if shift_end:
                from datetime import datetime
                try:
                    profile.shift_end = datetime.strptime(shift_end, '%H:%M').time()
                except ValueError:
                    pass
            profile.is_available = bool(request.POST.get('is_available'))
            if request.FILES.get('profile_photo'):
                profile.profile_photo = request.FILES['profile_photo']
            profile.save()
            messages.success(request, 'Profile updated successfully!')

        elif action == 'change_password':
            old_pw = request.POST.get('old_password')
            new_pw = request.POST.get('new_password')
            confirm_pw = request.POST.get('confirm_password')

            if old_pw and user.check_password(old_pw):
                if new_pw == confirm_pw:
                    user.set_password(new_pw)
                    user.save()
                    messages.success(request, 'Password changed successfully!')
                else:
                    messages.error(request, 'New passwords do not match.')
            else:
                messages.error(request, 'Incorrect current password.')

        return redirect('caregiver_settings')

    return render(request, 'profile/caregiver_settings.html', {
        'profile': profile,
        'user': user,
        'caregiver_type_choices': CaregiverProfile.CAREGIVER_TYPE_CHOICES,
        'relation_choices': CaregiverProfile.RELATION_CHOICES,
    })
