import csv
import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import CustomUser
from apps.appointments.models import Appointment
from apps.connections.models import DoctorPatientConnection
from apps.medicines.models import Medicine, MedicineLog, RiskScore, Activity, MissedAlertLog
from apps.reports.models import Report
from apps.profiles.models import PatientProfile, DoctorProfile
from apps.caregiver.models import CaregiverProfile, CaregiverPatientAssignment
from apps.family.models import FamilyMember

from .decorators import admin_required
from .services import (
    paginate, log_admin_action, get_dashboard_analytics, get_database_health,
    get_patient_relationships, enrich_patient_list, enrich_doctor_list, enrich_caregiver_list,
)


def _client_ip(request):
    return request.META.get('REMOTE_ADDR')


def _search_users(qs, q):
    if not q:
        return qs
    return qs.filter(
        Q(first_name__icontains=q) | Q(last_name__icontains=q) |
        Q(email__icontains=q) | Q(username__icontains=q) |
        Q(patient_profile__patient_id__icontains=q) |
        Q(patient_profile__phone_number__icontains=q) |
        Q(doctor_profile__doctor_id__icontains=q) |
        Q(doctor_profile__phone__icontains=q) |
        Q(caregiver_profile__cg_id__icontains=q) |
        Q(caregiver_profile__phone__icontains=q)
    )


def admin_login(request):
    if request.user.is_authenticated and (request.user.role == 'admin' or request.user.is_superuser):
        return redirect('system_admin_dashboard')
    error = None
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        user_obj = CustomUser.objects.filter(email__iexact=email).first()
        if user_obj and user_obj.role not in ('admin',) and not user_obj.is_superuser:
            error = 'This login is for system administrators only.'
        elif user_obj:
            user = authenticate(request, username=user_obj.username, password=password)
            if user and user.is_active and (user.role == 'admin' or user.is_superuser):
                login(request, user)
                log_admin_action(request, 'login', f'Admin login: {user.email}')
                return redirect('system_admin_dashboard')
            error = 'Invalid email or password.'
        else:
            error = 'Invalid email or password.'
    return render(request, 'system_admin/login.html', {'error': error})


@admin_required
def admin_logout_view(request):
    log_admin_action(request, 'logout', f'Admin logout: {request.user.email}')
    logout(request)
    return redirect('system_admin_login')


@admin_required
def dashboard(request):
    stats = get_dashboard_analytics()
    stats['weekly_appointments_json'] = json.dumps([
        {'day': str(r['appointment_date']), 'count': r['count']} for r in stats['weekly_appointments']
    ])

    all_days = sorted(set(
        [str(r['day']) for r in stats['user_growth']['patients']] +
        [str(r['day']) for r in stats['user_growth']['doctors']] +
        [str(r['day']) for r in stats['user_growth']['caregivers']]
    ))
    pt_map = {str(r['day']): r['count'] for r in stats['user_growth']['patients']}
    dr_map = {str(r['day']): r['count'] for r in stats['user_growth']['doctors']}
    cg_map = {str(r['day']): r['count'] for r in stats['user_growth']['caregivers']}
    stats['user_growth_json'] = json.dumps({
        'labels': all_days,
        'patients': [pt_map.get(d, 0) for d in all_days],
        'doctors': [dr_map.get(d, 0) for d in all_days],
        'caregivers': [cg_map.get(d, 0) for d in all_days],
    })

    stats['emergency_analytics_json'] = json.dumps([
        {'day': str(r['day']), 'count': r['count']} for r in stats['emergency_analytics']
    ])
    stats['adherence_daily_json'] = json.dumps([
        {'day': str(r['day']), 'pct': int(r['taken'] / r['total'] * 100) if r['total'] else 0}
        for r in stats['adherence_daily']
    ])
    return render(request, 'system_admin/dashboard.html', stats)


@admin_required
def patients_list(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    qs = CustomUser.objects.filter(role='patient').select_related('patient_profile').order_by('-date_joined')
    from apps.profiles.profile_bridge import profile_completed_q
    if status == 'active':
        qs = qs.filter(is_active=True).filter(profile_completed_q())
    elif status == 'inactive':
        qs = qs.filter(is_active=True).exclude(profile_completed_q())
    elif status == 'suspended':
        qs = qs.filter(is_active=False)
    qs = _search_users(qs, q)
    page = paginate(request, qs)
    enrich_patient_list(page)
    return render(request, 'system_admin/patients/list.html', {
        'page': page, 'q': q, 'status': status, 'page_title': 'Patient Management',
        'page_subtitle': 'Manage registered patients',
    })


@admin_required
def patient_detail(request, user_id):
    patient = get_object_or_404(CustomUser, id=user_id, role='patient')
    profile = getattr(patient, 'patient_profile', None)
    medicines = Medicine.objects.filter(patient=patient).order_by('-created_at')[:10]
    activities = Activity.objects.filter(patient=patient).order_by('-recorded_at')[:10]
    appointments = Appointment.objects.filter(patient=patient).select_related('doctor').order_by('-appointment_date')[:10]
    risk = RiskScore.objects.filter(patient=patient).first()
    connections = DoctorPatientConnection.objects.filter(patient=patient).select_related('doctor')
    family = FamilyMember.objects.filter(patient=patient)
    missed = MissedAlertLog.objects.filter(patient=patient).order_by('-sent_at')[:5]
    emergencies = Appointment.objects.filter(patient=patient, is_emergency=True).order_by('-created_at')[:5]
    apt_completed = Appointment.objects.filter(patient=patient, status='completed').count()
    apt_pending = Appointment.objects.filter(patient=patient, status__in=('pending', 'confirmed')).count()
    apt_emergency = Appointment.objects.filter(patient=patient, is_emergency=True).count()
    week_ago = date.today() - timedelta(days=6)
    logs = MedicineLog.objects.filter(patient=patient, scheduled_time__date__gte=week_ago)
    taken = logs.filter(status='taken').count()
    total_logs = logs.count()
    adherence_pct = int(taken / total_logs * 100) if total_logs else 0
    assigned_doctor = connections.filter(status='accepted').first()
    assigned_caregiver = CaregiverPatientAssignment.objects.filter(
        patient=patient, status='active',
    ).select_related('caregiver').first()
    relationships = get_patient_relationships(patient)
    return render(request, 'system_admin/patients/detail.html', {
        'patient': patient, 'profile': profile, 'medicines': medicines,
        'activities': activities, 'appointments': appointments, 'risk': risk,
        'connections': connections, 'family': family, 'missed': missed,
        'emergencies': emergencies, 'page_title': patient.get_full_name(),
        'page_subtitle': f'Patient ID: {patient.unique_id}',
        'apt_completed': apt_completed, 'apt_pending': apt_pending, 'apt_emergency': apt_emergency,
        'adherence_pct': adherence_pct,
        'assigned_doctor': assigned_doctor.doctor if assigned_doctor else None,
        'assigned_caregiver': assigned_caregiver.caregiver if assigned_caregiver else None,
        'relationships': relationships,
    })


@admin_required
def patient_edit(request, user_id):
    patient = get_object_or_404(CustomUser, id=user_id, role='patient')
    profile, _ = PatientProfile.objects.get_or_create(user=patient)
    doctors = CustomUser.objects.filter(role='doctor', is_active=True).order_by('first_name')
    caregivers = CustomUser.objects.filter(role='caregiver', is_active=True).order_by('first_name')
    current_doctor = DoctorPatientConnection.objects.filter(
        patient=patient, status='accepted',
    ).values_list('doctor_id', flat=True).first()
    current_caregiver = CaregiverPatientAssignment.objects.filter(
        patient=patient, status='active',
    ).values_list('caregiver_id', flat=True).first()

    if request.method == 'POST':
        patient.first_name = request.POST.get('first_name', '').strip()
        patient.last_name = request.POST.get('last_name', '').strip()
        patient.email = request.POST.get('email', '').strip()
        patient.phone = request.POST.get('phone', '').strip()
        patient.is_active = request.POST.get('is_active') == 'on'
        patient.save()

        profile.address = request.POST.get('address', '').strip()
        profile.city = request.POST.get('city', '').strip()
        profile.primary_diagnosis = request.POST.get('primary_diagnosis', '').strip()
        profile.allergies = request.POST.get('allergies', '').strip()
        profile.emergency_contact_name = request.POST.get('emergency_contact_name', '').strip()
        profile.emergency_contact_phone = request.POST.get('emergency_contact_phone', '').strip()
        profile.emergency_contact_relation = request.POST.get('emergency_contact_relation', '').strip()
        if request.FILES.get('profile_photo'):
            profile.profile_photo = request.FILES['profile_photo']
        profile.save()

        doctor_id = request.POST.get('assigned_doctor', '')
        if doctor_id:
            DoctorPatientConnection.objects.filter(
                patient=patient, status='accepted',
            ).exclude(doctor_id=doctor_id).update(status='rejected')
            DoctorPatientConnection.objects.update_or_create(
                patient=patient, doctor_id=doctor_id,
                defaults={'status': 'accepted', 'requested_by': request.user},
            )
        else:
            DoctorPatientConnection.objects.filter(
                patient=patient, status='accepted',
            ).update(status='rejected')

        caregiver_id = request.POST.get('assigned_caregiver', '')
        if caregiver_id:
            CaregiverPatientAssignment.objects.filter(
                patient=patient, status='active',
            ).exclude(caregiver_id=caregiver_id).update(status='inactive')
            CaregiverPatientAssignment.objects.update_or_create(
                patient=patient, caregiver_id=caregiver_id,
                defaults={'status': 'active', 'assigned_by': request.user},
            )
        else:
            CaregiverPatientAssignment.objects.filter(
                patient=patient, status='active',
            ).update(status='inactive')

        log_admin_action(request, 'update', f'Updated patient {patient.unique_id}', 'CustomUser', patient.id)
        messages.success(request, 'Patient updated successfully.')
        return redirect('system_admin_patient_detail', user_id=patient.id)

    return render(request, 'system_admin/patients/edit.html', {
        'patient': patient, 'profile': profile,
        'doctors': doctors, 'caregivers': caregivers,
        'current_doctor': current_doctor, 'current_caregiver': current_caregiver,
        'page_title': 'Edit Patient',
        'page_subtitle': f'Update details for {patient.get_full_name()}',
    })


@admin_required
@require_POST
def patient_suspend(request, user_id):
    patient = get_object_or_404(CustomUser, id=user_id, role='patient')
    patient.is_active = not patient.is_active
    patient.save(update_fields=['is_active'])
    action = 'activate' if patient.is_active else 'suspend'
    log_admin_action(request, action, f'{action.title()} patient {patient.unique_id}', 'CustomUser', patient.id)
    messages.info(request, f'Patient {"activated" if patient.is_active else "suspended"}.')
    return redirect('system_admin_patient_detail', user_id=patient.id)


@admin_required
@require_POST
def patient_delete(request, user_id):
    patient = get_object_or_404(CustomUser, id=user_id, role='patient')
    uid = patient.unique_id
    log_admin_action(request, 'delete', f'Deleted patient {uid}', 'CustomUser', patient.id)
    patient.delete()
    messages.success(request, f'Patient {uid} deleted.')
    return redirect('system_admin_patients')


@admin_required
def doctors_list(request):
    q = request.GET.get('q', '').strip()
    qs = CustomUser.objects.filter(role='doctor').select_related('doctor_profile').order_by('-date_joined')
    status = request.GET.get('status', '')
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'suspended':
        qs = qs.filter(is_active=False)
    qs = _search_users(qs, q)
    page = paginate(request, qs)
    enrich_doctor_list(page)
    return render(request, 'system_admin/doctors/list.html', {
        'page': page, 'q': q, 'status': status,
        'page_title': 'Doctor Management',
        'page_subtitle': 'Manage registered doctors',
    })


@admin_required
def doctor_detail(request, user_id):
    doctor = get_object_or_404(CustomUser, id=user_id, role='doctor')
    profile = getattr(doctor, 'doctor_profile', None)
    appointments = Appointment.objects.filter(doctor=doctor).select_related('patient').order_by('-appointment_date')[:15]
    connections = DoctorPatientConnection.objects.filter(doctor=doctor, status='accepted').select_related('patient')
    apt_completed = Appointment.objects.filter(doctor=doctor, status='completed').count()
    apt_pending = Appointment.objects.filter(doctor=doctor, status__in=('pending', 'confirmed')).count()
    return render(request, 'system_admin/doctors/detail.html', {
        'doctor': doctor, 'profile': profile, 'appointments': appointments,
        'connections': connections, 'page_title': f'Dr. {doctor.get_full_name()}',
        'page_subtitle': f'Doctor ID: {doctor.unique_id}',
        'patients_count': connections.count(),
        'apt_completed': apt_completed, 'apt_pending': apt_pending,
    })


@admin_required
def doctor_form(request, user_id=None):
    doctor = get_object_or_404(CustomUser, id=user_id, role='doctor') if user_id else None
    profile = DoctorProfile.objects.filter(user=doctor).first() if doctor else None
    editing = doctor is not None
    if request.method == 'POST':
        if not editing:
            doctor = CustomUser(role='doctor', username=request.POST.get('email', '').strip())
            doctor.set_password(request.POST.get('password', 'SmartTrack@123'))
        doctor.first_name = request.POST.get('first_name', '').strip()
        doctor.last_name = request.POST.get('last_name', '').strip()
        doctor.email = request.POST.get('email', '').strip()
        doctor.phone = request.POST.get('phone', '').strip()
        doctor.is_active = request.POST.get('is_active', 'on') == 'on'
        doctor.profile_completed = True
        doctor.save()
        profile, _ = DoctorProfile.objects.get_or_create(user=doctor)
        profile.specialty = request.POST.get('specialization', '').strip() or profile.specialty
        profile.hospital_name = request.POST.get('hospital', '').strip()
        profile.license_number = request.POST.get('license_number', '').strip()
        profile.available_for_consultation = request.POST.get('is_verified') == 'on'
        profile.consultation_mode = request.POST.get('consultation_mode', profile.consultation_mode or 'both')
        profile.bio = request.POST.get('bio', '').strip()
        if request.FILES.get('profile_photo'):
            profile.profile_photo = request.FILES['profile_photo']
        profile.save()
        log_admin_action(
            request, 'create' if not editing else 'update',
            f'{"Created" if not editing else "Updated"} doctor {doctor.unique_id}',
            'CustomUser', doctor.id,
        )
        messages.success(request, f'Doctor {"created" if not editing else "updated"}.')
        return redirect('system_admin_doctor_detail', user_id=doctor.id)
    return render(request, 'system_admin/doctors/form.html', {
        'doctor': doctor, 'profile': profile, 'editing': editing,
        'page_title': 'Edit Doctor' if editing else 'Add Doctor',
    })


@admin_required
@require_POST
def doctor_verify(request, user_id):
    doctor = get_object_or_404(CustomUser, id=user_id, role='doctor')
    profile, _ = DoctorProfile.objects.get_or_create(user=doctor)
    profile.available_for_consultation = not profile.available_for_consultation
    profile.save(update_fields=['available_for_consultation'])
    log_admin_action(request, 'verify', f'Updated doctor availability {doctor.unique_id}', 'DoctorProfile', doctor.id)
    messages.success(request, f'Doctor is {"available" if profile.available_for_consultation else "unavailable"} for consultation.')
    return redirect('system_admin_doctor_detail', user_id=doctor.id)


@admin_required
@require_POST
def doctor_remove(request, user_id):
    doctor = get_object_or_404(CustomUser, id=user_id, role='doctor')
    uid = doctor.unique_id
    log_admin_action(request, 'delete', f'Removed doctor {uid}', 'CustomUser', doctor.id)
    doctor.delete()
    messages.success(request, f'Doctor {uid} removed.')
    return redirect('system_admin_doctors')


@admin_required
def caregivers_list(request):
    q = request.GET.get('q', '').strip()
    qs = CustomUser.objects.filter(role='caregiver').select_related('caregiver_profile').order_by('-date_joined')
    qs = _search_users(qs, q)
    page = paginate(request, qs)
    enrich_caregiver_list(page)
    return render(request, 'system_admin/caregivers/list.html', {
        'page': page, 'q': q,
        'page_title': 'Caregiver Management',
        'page_subtitle': 'Manage registered caregivers',
    })


@admin_required
def caregiver_detail(request, user_id):
    caregiver = get_object_or_404(CustomUser, id=user_id, role='caregiver')
    profile = getattr(caregiver, 'caregiver_profile', None)
    links = CaregiverPatientAssignment.objects.filter(caregiver=caregiver).select_related('patient')
    active_link = links.filter(status='active').first()
    has_active_patient = active_link is not None
    assigned_doctor = None
    if active_link:
        conn = DoctorPatientConnection.objects.filter(
            patient=active_link.patient, status='accepted',
        ).select_related('doctor').first()
        assigned_doctor = conn.doctor if conn else None
    return render(request, 'system_admin/caregivers/detail.html', {
        'caregiver': caregiver, 'profile': profile, 'links': links,
        'page_title': caregiver.get_full_name(),
        'page_subtitle': f'Caregiver ID: {caregiver.unique_id}',
        'assigned_patient': active_link.patient if active_link else None,
        'assigned_doctor': assigned_doctor,
        'has_active_patient': has_active_patient,
    })


@admin_required
def caregiver_form(request, user_id=None):
    caregiver = get_object_or_404(CustomUser, id=user_id, role='caregiver') if user_id else None
    profile = CaregiverProfile.objects.filter(user=caregiver).first() if caregiver else None
    editing = caregiver is not None
    patients = CustomUser.objects.filter(role='patient', is_active=True).order_by('first_name')
    current_patient = None
    if editing:
        assign = CaregiverPatientAssignment.objects.filter(
            caregiver=caregiver, status='active',
        ).values_list('patient_id', flat=True).first()
        current_patient = assign

    if request.method == 'POST':
        if not editing:
            caregiver = CustomUser(role='caregiver', username=request.POST.get('email', '').strip())
            caregiver.set_password(request.POST.get('password', 'SmartTrack@123'))
        caregiver.first_name = request.POST.get('first_name', '').strip()
        caregiver.last_name = request.POST.get('last_name', '').strip()
        caregiver.email = request.POST.get('email', '').strip()
        caregiver.phone = request.POST.get('phone', '').strip()
        caregiver.is_active = request.POST.get('is_active', 'on') == 'on'
        caregiver.profile_completed = True
        caregiver.save()
        profile, _ = CaregiverProfile.objects.get_or_create(user=caregiver)
        profile.caregiver_type = request.POST.get('caregiver_type', profile.caregiver_type or 'personal')
        profile.hospital_name = request.POST.get('hospital_name', '').strip()
        profile.phone = request.POST.get('phone', '').strip()
        if request.FILES.get('profile_photo'):
            profile.profile_photo = request.FILES['profile_photo']
        profile.save()

        patient_id = request.POST.get('assigned_patient', '')
        if patient_id:
            CaregiverPatientAssignment.objects.filter(
                caregiver=caregiver, status='active',
            ).exclude(patient_id=patient_id).update(status='inactive')
            CaregiverPatientAssignment.objects.update_or_create(
                caregiver=caregiver, patient_id=patient_id,
                defaults={'status': 'active', 'assigned_by': request.user},
            )
        else:
            CaregiverPatientAssignment.objects.filter(
                caregiver=caregiver, status='active',
            ).update(status='inactive')

        log_admin_action(
            request, 'create' if not editing else 'update',
            f'{"Created" if not editing else "Updated"} caregiver {caregiver.unique_id}',
            'CustomUser', caregiver.id,
        )
        messages.success(request, f'Caregiver {"created" if not editing else "updated"}.')
        return redirect('system_admin_caregiver_detail', user_id=caregiver.id)

    return render(request, 'system_admin/caregivers/form.html', {
        'caregiver': caregiver, 'profile': profile, 'editing': editing,
        'patients': patients, 'current_patient': current_patient,
        'page_title': 'Edit Caregiver' if editing else 'Add Caregiver',
        'page_subtitle': f'Update {caregiver.get_full_name()}' if editing else 'Register a new caregiver',
    })


@admin_required
@require_POST
def caregiver_remove(request, user_id):
    cg = get_object_or_404(CustomUser, id=user_id, role='caregiver')
    uid = cg.unique_id
    log_admin_action(request, 'delete', f'Removed caregiver {uid}', 'CustomUser', cg.id)
    cg.delete()
    messages.success(request, f'Caregiver {uid} removed.')
    return redirect('system_admin_caregivers')


@admin_required
def family_list(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    qs = FamilyMember.objects.select_related('patient', 'user').order_by('-created_at')
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(relation__icontains=q) | Q(phone__icontains=q) |
            Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q) |
            Q(email__icontains=q)
        )
    if status == 'active':
        qs = qs.filter(user__is_active=True)
    elif status == 'inactive':
        qs = qs.filter(user__isnull=True)
    page = paginate(request, qs)
    return render(request, 'system_admin/family/list.html', {
        'page': page, 'q': q, 'status': status,
        'page_title': 'Family Member Management',
        'page_subtitle': 'View family contacts linked to patients',
    })


@admin_required
def family_detail(request, member_id):
    member = get_object_or_404(FamilyMember.objects.select_related('patient', 'user'), id=member_id)
    patient = member.patient
    doctor_conn = DoctorPatientConnection.objects.filter(
        patient=patient, status='accepted',
    ).select_related('doctor').first()
    caregiver_assign = CaregiverPatientAssignment.objects.filter(
        patient=patient, status='active',
    ).select_related('caregiver').first()
    relationships = [
        {'role': 'Family Member', 'name': member.name, 'subtitle': member.relation},
        {'role': 'Patient', 'name': patient.get_full_name(), 'subtitle': patient.unique_id,
         'url': f'/system-admin/patients/{patient.id}/'},
    ]
    if doctor_conn:
        relationships.append({
            'role': 'Doctor', 'name': f'Dr. {doctor_conn.doctor.get_full_name()}',
            'url': f'/system-admin/doctors/{doctor_conn.doctor.id}/',
        })
    if caregiver_assign:
        relationships.append({
            'role': 'Caregiver', 'name': caregiver_assign.caregiver.get_full_name(),
            'url': f'/system-admin/caregivers/{caregiver_assign.caregiver.id}/',
        })
    return render(request, 'system_admin/family/detail.html', {
        'member': member, 'patient': patient,
        'page_title': member.name,
        'page_subtitle': f'{member.relation} of {patient.get_full_name()}',
        'relationships': relationships,
    })


@admin_required
def family_edit(request, member_id):
    member = get_object_or_404(FamilyMember.objects.select_related('patient', 'user'), id=member_id)
    if request.method == 'POST':
        member.name = request.POST.get('name', '').strip()
        member.relation = request.POST.get('relation', '').strip()
        member.phone = request.POST.get('phone', '').strip()
        member.email = request.POST.get('email', '').strip() or None
        member.is_emergency_contact = request.POST.get('is_emergency_contact') == 'on'
        member.save()

        if member.user:
            member.user.is_active = request.POST.get('access_active') == 'on'
            member.user.save(update_fields=['is_active'])

        log_admin_action(request, 'update', f'Updated family member {member.name}', 'FamilyMember', member.id)
        messages.success(request, 'Family member updated successfully.')
        return redirect('system_admin_family_detail', member_id=member.id)

    return render(request, 'system_admin/family/edit.html', {
        'member': member,
        'page_title': 'Edit Family Member',
        'page_subtitle': f'Update {member.name}',
    })


@admin_required
@require_POST
def family_delete(request, member_id):
    member = get_object_or_404(FamilyMember, id=member_id)
    name = member.name
    log_admin_action(request, 'delete', f'Deleted family member {name}', 'FamilyMember', member.id)
    member.delete()
    messages.success(request, f'Family member {name} removed.')
    return redirect('system_admin_family')


@admin_required
def appointments_list(request):
    q = request.GET.get('q', '').strip()
    view = request.GET.get('view', 'scheduled')
    qs = Appointment.objects.select_related('patient', 'doctor').order_by('-appointment_date', '-created_at')
    view_titles = {
        'scheduled': ('Scheduled Appointments', 'Pending and confirmed appointments'),
        'completed': ('Completed Appointments', 'Successfully completed consultations'),
        'cancelled': ('Cancelled Appointments', 'Cancelled or missed appointments'),
        'emergency': ('Emergency Cases', 'Emergency consultation requests'),
    }
    if view == 'scheduled':
        qs = qs.filter(status__in=('pending', 'confirmed'), is_emergency=False)
    elif view == 'completed':
        qs = qs.filter(status='completed')
    elif view == 'cancelled':
        qs = qs.filter(status='cancelled')
    elif view == 'emergency':
        qs = qs.filter(is_emergency=True)
    if q:
        qs = qs.filter(
            Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q) |
            Q(doctor__first_name__icontains=q) | Q(doctor__last_name__icontains=q)
        )
    page = paginate(request, qs)
    title, subtitle = view_titles.get(view, view_titles['scheduled'])
    return render(request, 'system_admin/appointments/list.html', {
        'page': page, 'q': q, 'view': view,
        'page_title': title, 'page_subtitle': subtitle,
    })


@admin_required
def emergency_list(request):
    qs = Appointment.objects.filter(is_emergency=True).select_related('patient', 'doctor').order_by('-created_at')
    page = paginate(request, qs)
    return render(request, 'system_admin/emergency/list.html', {'page': page, 'page_title': 'Emergency Requests'})


@admin_required
def video_list(request):
    qs = Appointment.objects.filter(
        appointment_type__in=('video', 'emergency_video'),
    ).select_related('patient', 'doctor').order_by('-appointment_date')
    page = paginate(request, qs)
    return render(request, 'system_admin/video/list.html', {'page': page, 'page_title': 'Video Consultations'})


@admin_required
def medicines_list(request):
    q = request.GET.get('q', '').strip()
    qs = Medicine.objects.select_related('patient').order_by('-created_at')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(patient__first_name__icontains=q))
    page = paginate(request, qs)
    return render(request, 'system_admin/medicines/list.html', {'page': page, 'q': q, 'page_title': 'Medicines'})


@admin_required
def activities_list(request):
    qs = Activity.objects.select_related('patient').order_by('-recorded_at')
    page = paginate(request, qs)
    return render(request, 'system_admin/activities/list.html', {'page': page, 'page_title': 'Activities'})


@admin_required
def health_analytics(request):
    week_ago = date.today() - timedelta(days=6)
    adherence = MedicineLog.objects.filter(scheduled_time__date__gte=week_ago)
    taken = adherence.filter(status='taken').count()
    total = adherence.count()
    pct = int(taken / total * 100) if total else 0
    return render(request, 'system_admin/analytics/health.html', {
        'adherence_pct': pct, 'taken': taken, 'total': total,
        'page_title': 'Health Analytics',
    })


@admin_required
def risk_monitoring(request):
    level = request.GET.get('level', '')
    qs = RiskScore.objects.select_related('patient').order_by('-score')
    if level:
        qs = qs.filter(level=level)
    page = paginate(request, qs)
    missed = MissedAlertLog.objects.select_related('patient', 'medicine').order_by('-sent_at')[:15]
    return render(request, 'system_admin/risk/list.html', {
        'page': page, 'level': level, 'missed': missed, 'page_title': 'Risk Monitoring',
    })


@admin_required
def reports_list(request):
    qs = Report.objects.select_related('patient', 'doctor').order_by('-created_at')
    page = paginate(request, qs)
    stats = get_dashboard_analytics()
    return render(request, 'system_admin/reports/list.html', {
        'page': page,
        'page_title': 'Reports & Analytics',
        'total_reports': stats['total_reports'],
        'total_patients': stats['total_patients'],
        'high_risk_count': stats['high_risk_patients'],
        'adherence_pct': stats['adherence_pct'],
    })


@admin_required
def reports_export(request):
    fmt = request.GET.get('format', 'csv')
    report_type = request.GET.get('type', 'patients')
    log_admin_action(request, 'export', f'Export {report_type} as {fmt}')
    if report_type == 'appointments':
        rows = Appointment.objects.select_related('patient', 'doctor').order_by('-appointment_date')[:500]
        if fmt == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="appointments.csv"'
            writer = csv.writer(response)
            writer.writerow(['Patient', 'Doctor', 'Date', 'Status', 'Type'])
            for a in rows:
                writer.writerow([a.patient.get_full_name(), a.doctor.get_full_name(), a.appointment_date, a.status, a.appointment_type])
            return response
    elif report_type == 'risk':
        rows = RiskScore.objects.select_related('patient').order_by('-score')
        if fmt == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="risk_report.csv"'
            writer = csv.writer(response)
            writer.writerow(['Patient', 'Score', 'Level'])
            for r in rows:
                writer.writerow([r.patient.get_full_name(), r.score, r.level])
            return response
    rows = CustomUser.objects.filter(role='patient').order_by('-date_joined')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="patients.csv"'
    writer = csv.writer(response)
    writer.writerow(['Name', 'ID', 'Email', 'Phone', 'Active', 'Joined'])
    for p in rows:
        writer.writerow([p.get_full_name(), p.unique_id, p.email, p.phone, p.is_active, p.date_joined.date()])
    return response


@admin_required
def payments_page(request):
    from django.db.models import Sum, Count
    from apps.payments.models import ConsultationPayment

    qs = ConsultationPayment.objects.select_related(
        'patient', 'doctor', 'appointment', 'paid_by',
    ).order_by('-created_at')

    status_filter = request.GET.get('status', '')
    valid = ('pending', 'processing', 'paid', 'failed', 'refunded', 'cancelled')
    if status_filter in valid:
        qs = qs.filter(payment_status=status_filter)

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(payment_id__icontains=q) | Q(transaction_id__icontains=q) |
            Q(patient__first_name__icontains=q) | Q(patient__last_name__icontains=q) |
            Q(doctor__first_name__icontains=q) | Q(doctor__last_name__icontains=q)
        )

    stats = {
        'total': ConsultationPayment.objects.count(),
        'paid': ConsultationPayment.objects.filter(payment_status='paid').count(),
        'pending': ConsultationPayment.objects.filter(payment_status='pending').count(),
        'failed': ConsultationPayment.objects.filter(payment_status='failed').count(),
        'refunded': ConsultationPayment.objects.filter(payment_status='refunded').count(),
        'processing': ConsultationPayment.objects.filter(payment_status='processing').count(),
        'cancelled': ConsultationPayment.objects.filter(payment_status='cancelled').count(),
        'paid_amount': ConsultationPayment.objects.filter(
            payment_status='paid',
        ).aggregate(t=Sum('amount'))['t'] or 0,
        'pending_amount': ConsultationPayment.objects.filter(
            payment_status__in=('pending', 'processing'),
        ).aggregate(t=Sum('amount'))['t'] or 0,
    }

    page = paginate(request, qs, per_page=25)
    return render(request, 'system_admin/payments/index.html', {
        'page': page,
        'page_title': 'Payments',
        'status_filter': status_filter,
        'q': q,
        'stats': stats,
    })


@admin_required
def database_monitor(request):
    health = get_database_health()
    return render(request, 'system_admin/database/monitor.html', {
        **health, 'page_title': 'Database Monitoring',
    })


@admin_required
def system_logs(request):
    from .models import AdminActionLog
    qs = AdminActionLog.objects.select_related('admin_user').order_by('-created_at')
    page = paginate(request, qs, per_page=30)
    return render(request, 'system_admin/logs/list.html', {'page': page, 'page_title': 'System Logs'})


@admin_required
def settings_page(request):
    if request.method == 'POST':
        log_admin_action(request, 'update', 'Updated system settings')
        messages.success(request, 'Settings saved.')
        return redirect('system_admin_settings')
    return render(request, 'system_admin/settings/index.html', {'page_title': 'Settings'})


@admin_required
def profile_page(request):
    user = request.user
    if request.method == 'POST':
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name = request.POST.get('last_name', '').strip()
        user.phone = request.POST.get('phone', '').strip()
        new_pass = request.POST.get('password', '')
        if new_pass:
            user.set_password(new_pass)
        user.save()
        if new_pass:
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, user)
        log_admin_action(request, 'update', 'Updated admin profile')
        messages.success(request, 'Profile updated.')
        return redirect('system_admin_profile')
    return render(request, 'system_admin/profile.html', {'page_title': 'Admin Profile'})
