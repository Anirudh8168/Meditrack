from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from datetime import date, timedelta
from apps.accounts.models import CustomUser
from apps.medicines.models import Medicine, MedicineLog, Activity, RiskScore
from apps.appointments.models import Appointment
from apps.notifications.models import Notification
from apps.notifications.utils import notify_user
from apps.reports.models import Report
from apps.caregiver.models import (
    CaregiverPatientAssignment, CaregiverProfile, PatientCaregiverRecord,
    HospitalCaregiverAssignment, CaregiverCareNote, CaregiverDailyLog,
    CaregiverActivityTimeline,
    get_hospital_caregiver_for_patient, get_doctor_hospital_assignments,
    get_any_active_caregiver_for_patient, patient_has_active_caregiver,
    get_active_assignment_for_caregiver, get_pending_assignment_for_caregiver,
    HOSPITAL_ROLE_CHOICES, HOSPITAL_DEPARTMENT_CHOICES, HOSPITAL_DURATION_CHOICES,
)
from apps.caregiver.access import (
    enter_caregiver_mode, exit_caregiver_mode, log_caregiver_action,
    patient_age, patient_assigned_doctor, caregiver_has_active_patient,
)
from apps.connections.models import DoctorPatientConnection


def caregiver_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/auth/login/')
        if request.user.role != 'caregiver':
            return redirect(request.user.get_dashboard_url())
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


@login_required
@caregiver_required
def caregiver_patients(request):
    """My Patient — search, connect, manage single patient assignment."""
    return redirect('caregiver_my_patient')


@login_required
@caregiver_required
def caregiver_my_patient(request):
    """Unified My Patient page with search-based connection."""
    user = request.user
    active_assignment = get_active_assignment_for_caregiver(user)
    pending_assignment = get_pending_assignment_for_caregiver(user)
    connection_history = CaregiverPatientAssignment.objects.filter(
        caregiver=user,
    ).exclude(status='pending').select_related('patient', 'disconnected_by').order_by('-updated_at')[:10]

    care_notes = []
    daily_logs = []
    timeline = []
    assigned_doctor = None
    patient_profile = None
    age = None

    if active_assignment:
        care_notes = CaregiverCareNote.objects.filter(
            assignment=active_assignment,
        ).order_by('-created_at')[:20]
        daily_logs = CaregiverDailyLog.objects.filter(
            assignment=active_assignment,
        ).order_by('-log_date', '-created_at')[:20]
        timeline = CaregiverActivityTimeline.objects.filter(
            assignment=active_assignment,
        ).order_by('-created_at')[:30]
        assigned_doctor = patient_assigned_doctor(active_assignment.patient)
        age = patient_age(active_assignment.patient)
        try:
            patient_profile = active_assignment.patient.patient_profile
        except Exception:
            patient_profile = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_note' and active_assignment:
            note_text = request.POST.get('note', '').strip()
            if note_text:
                CaregiverCareNote.objects.create(
                    assignment=active_assignment, caregiver=user, note=note_text,
                )
                log_caregiver_action(active_assignment, user, 'other', f'Care note added: {note_text[:80]}')
                messages.success(request, 'Care note saved.')
            return redirect('caregiver_my_patient')

        if action == 'add_log' and active_assignment:
            entry = request.POST.get('entry', '').strip()
            log_type = request.POST.get('log_type', 'other')
            if entry:
                CaregiverDailyLog.objects.create(
                    assignment=active_assignment,
                    caregiver=user,
                    log_type=log_type,
                    entry=entry,
                    log_date=date.today(),
                )
                log_caregiver_action(active_assignment, user, 'activity_logged', entry)
                messages.success(request, 'Daily care log entry saved.')
            return redirect('caregiver_my_patient')

        if action == 'cancel_pending' and pending_assignment:
            pending_assignment.delete()
            messages.info(request, 'Connection request cancelled.')
            return redirect('caregiver_my_patient')

    return render(request, 'dashboard/caregiver/my_patient.html', {
        'active_assignment': active_assignment,
        'pending_assignment': pending_assignment,
        'connection_history': connection_history,
        'care_notes': care_notes,
        'daily_logs': daily_logs,
        'timeline': timeline,
        'assigned_doctor': assigned_doctor,
        'patient_profile': patient_profile,
        'patient_age': age,
        'disconnect_reasons': [
            'Treatment completed',
            'Caregiver unavailable',
            'Shift transferred',
            'Hospital reassignment',
            'Patient moved',
            'Other',
        ],
    })

@login_required
@caregiver_required
def caregiver_dashboard(request):
    user = request.user
    today = date.today()

    assignments = CaregiverPatientAssignment.objects.filter(
        caregiver=user, status='active'
    ).select_related('patient')

    patients = [a.patient for a in assignments]

    total_medicines_today = 0
    total_taken_today = 0
    missed_today = 0
    high_risk_count = 0

    patient_summaries = []
    for patient in patients:
        meds = Medicine.objects.filter(patient=patient, is_active=True)
        today_logs = MedicineLog.objects.filter(patient=patient, scheduled_time__date=today)
        taken = today_logs.filter(status='taken').count()
        total = today_logs.count()
        missed = today_logs.filter(status='missed').count()
        risk = RiskScore.objects.filter(patient=patient).first()
        low_stock = [m for m in meds if m.is_low_stock]

        total_medicines_today += total
        total_taken_today += taken
        missed_today += missed
        if risk and risk.level in ('high', 'critical'):
            high_risk_count += 1

        try:
            profile = patient.patient_profile
        except Exception:
            profile = None

        patient_summaries.append({
            'patient': patient,
            'profile': profile,
            'medicines': meds,
            'taken': taken,
            'total': total,
            'missed': missed,
            'risk': risk,
            'low_stock': low_stock,
            'compliance_pct': int(taken / total * 100) if total > 0 else 0,
        })

    pending_assignments = CaregiverPatientAssignment.objects.filter(
        caregiver=user, status='pending'
    ).select_related('patient')

    active_assignment = get_active_assignment_for_caregiver(user)
    pending_assignment = get_pending_assignment_for_caregiver(user)

    upcoming_apts = Appointment.objects.filter(
        patient__in=patients,
        appointment_date__gte=today,
        status__in=['pending', 'confirmed']
    ).select_related('patient', 'doctor').order_by('appointment_date', 'appointment_time')[:10]

    from apps.notifications.notification_utils import today_notifications_for_user
    from apps.medicines.risk_alert_service import get_alerts_for_user

    notifications = list(today_notifications_for_user(user, limit=5, unread_only=False))
    unread_count = Notification.objects.filter(user=user, is_read=False).count()

    try:
        profile = user.caregiver_profile
    except Exception:
        profile = None

    hour = timezone.localtime().hour
    greeting = 'Good Morning' if hour < 12 else 'Good Afternoon' if hour < 17 else 'Good Evening'

    context = {
        'user': user,
        'profile': profile,
        'assignments': assignments,
        'patients': patients,
        'patient_summaries': patient_summaries,
        'pending_assignments': pending_assignments,
        'active_assignment': active_assignment,
        'pending_assignment': pending_assignment,
        'has_patient': active_assignment is not None,
        'total_patients': len(patients),
        'total_medicines_today': total_medicines_today,
        'total_taken_today': total_taken_today,
        'missed_today': missed_today,
        'high_risk_count': high_risk_count,
        'upcoming_apts': upcoming_apts,
        'notifications': notifications,
        'risk_alerts': get_alerts_for_user(user, limit=10),
        'unread_count': unread_count,
        'today': today,
        'greeting': greeting,
    }
    return render(request, 'dashboard/caregiver/index.html', context)


@login_required
@caregiver_required
def search_patients(request):
    """AJAX search for patients — consistent with doctor/patient global search."""
    from django.db.models import Q
    query = request.GET.get('q', '').strip()
    results = []
    user = request.user

    if query and len(query) >= 2:
        if caregiver_has_active_patient(user):
            return JsonResponse({
                'results': [],
                'blocked': True,
                'message': 'You are already connected to a patient. Disconnect before searching.',
            })

        qs = CustomUser.objects.filter(
            role='patient', is_active=True,
        ).filter(
            Q(patient_profile__patient_id__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(patient_profile__first_name__icontains=query) |
            Q(patient_profile__last_name__icontains=query) |
            Q(patient_profile__phone_number__icontains=query)
        ).distinct()[:10]

        for pat in qs:
            existing = CaregiverPatientAssignment.objects.filter(caregiver=user, patient=pat).first()
            if existing and existing.status in ('active', 'pending'):
                conn_status = existing.status
            elif existing and existing.status == 'rejected':
                conn_status = None
            else:
                conn_status = None

            try:
                prof = pat.patient_profile
                gender = prof.gender or ''
                age = patient_age(pat)
                diagnosis = prof.primary_diagnosis or ''
            except Exception:
                gender = ''
                age = None
                diagnosis = ''

            doctor = patient_assigned_doctor(pat)
            results.append({
                'id': pat.id,
                'name': pat.get_full_name(),
                'unique_id': pat.unique_id,
                'gender': gender,
                'age': age,
                'diagnosis': diagnosis,
                'doctor_name': f"Dr. {doctor.get_full_name()}" if doctor else None,
                'connection_status': conn_status,
                'assignment_id': existing.id if existing else None,
            })

    return JsonResponse({'results': results, 'blocked': False})


@login_required
@caregiver_required
@require_POST
def send_connection_request(request):
    """Send caregiver connection request to patient — full access, patient must approve."""
    user = request.user
    patient_id = request.POST.get('patient_id')

    if caregiver_has_active_patient(user):
        active = get_active_assignment_for_caregiver(user)
        return JsonResponse({
            'success': False,
            'error': 'already_connected',
            'patient_name': active.patient.get_full_name(),
            'patient_id': active.patient.id,
        })

    pending = get_pending_assignment_for_caregiver(user)
    if pending:
        return JsonResponse({
            'success': False,
            'error': 'pending_exists',
            'message': f'A connection request to {pending.patient.get_full_name()} is already pending.',
        })

    patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
    existing = CaregiverPatientAssignment.objects.filter(caregiver=user, patient=patient).first()

    if existing:
        if existing.status == 'active':
            return JsonResponse({'success': False, 'error': 'Already connected to this patient.'})
        if existing.status == 'pending':
            return JsonResponse({'success': False, 'error': 'Request already pending for this patient.'})
        existing.status = 'pending'
        existing.can_mark_medicines = True
        existing.can_manage_appointments = True
        existing.can_upload_reports = True
        existing.can_log_activities = True
        existing.rejected_at = None
        existing.rejection_reason = ''
        existing.save()
        assignment = existing
    else:
        assignment = CaregiverPatientAssignment.objects.create(
            caregiver=user,
            patient=patient,
            assigned_by=user,
            status='pending',
            can_mark_medicines=True,
            can_manage_appointments=True,
            can_upload_reports=True,
            can_log_activities=True,
        )

    try:
        cg_profile = user.caregiver_profile
        relation = cg_profile.get_relation_display() if cg_profile else 'Caregiver'
    except Exception:
        relation = 'Caregiver'

    notify_user(
        user=patient,
        title='Caregiver Connection Request',
        message=(
            f'{user.get_full_name()} wants caregiver access to help manage your healthcare activities. '
            f'Relationship: {relation}. Requested Access: Patient Assistance.'
        ),
        notification_type='connection',
        priority='high',
        category=f'caregiver_req_{assignment.id}',
        related_id=assignment.id,
    )

    return JsonResponse({
        'success': True,
        'message': f'Connection request sent to {patient.get_full_name()}. Awaiting patient approval.',
    })


@login_required
@caregiver_required
def connect_to_patient(request):
    """Legacy route — redirect to My Patient."""
    return redirect('caregiver_my_patient')


@login_required
def patient_accept_caregiver(request, assignment_id):
    """Patient accepts or rejects caregiver connection request."""
    if request.user.role != 'patient':
        return redirect(request.user.get_dashboard_url())

    assignment = get_object_or_404(CaregiverPatientAssignment, id=assignment_id, patient=request.user)
    action = request.POST.get('action') or request.GET.get('action', 'accept')
    rejection_reason = request.POST.get('rejection_reason', '').strip()

    if action == 'accept':
        assignment.status = 'active'
        assignment.approved_at = timezone.now()
        assignment.save()
        log_caregiver_action(
            assignment, assignment.caregiver, 'connection_accepted',
            f'{request.user.get_full_name()} accepted the connection.',
        )
        notify_user(
            user=assignment.caregiver,
            title='Patient Connected Successfully',
            message=f'{request.user.get_full_name()} accepted your connection request. You can now assist the patient.',
            notification_type='connection',
            priority='high',
            category=f'caregiver_accept_{assignment.id}'
        )
        messages.success(request, f'{assignment.caregiver.get_full_name()} is now your caregiver.')
    else:
        assignment.status = 'rejected'
        assignment.rejected_at = timezone.now()
        assignment.rejection_reason = rejection_reason
        assignment.save()
        notify_user(
            user=assignment.caregiver,
            title='Connection Request Rejected',
            message=(
                f'{request.user.get_full_name()} rejected your caregiver connection request.'
                + (f' Reason: {rejection_reason}' if rejection_reason else '')
            ),
            notification_type='connection',
            priority='medium',
            category=f'caregiver_reject_{assignment.id}'
        )
        messages.info(request, 'Caregiver request rejected.')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'action': action})
    return redirect('/dashboard/patient/')


@login_required
@caregiver_required
def caregiver_patient_detail(request, patient_id):
    user = request.user
    patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
    assignment = get_object_or_404(CaregiverPatientAssignment, caregiver=user, patient=patient, status='active')

    today = date.today()
    now = timezone.localtime()
    medicines = Medicine.objects.filter(patient=patient, is_active=True)

    # Annotate medicine status for today
    for m in medicines:
        today_taken = m.logs.filter(scheduled_time__date=today, status='taken').count()
        m.today_taken_count = today_taken
        m.today_taken = today_taken >= m.max_daily_doses
        m.can_take_more = today_taken < m.max_daily_doses

    today_logs = MedicineLog.objects.filter(patient=patient, scheduled_time__date=today).select_related('medicine')
    activities = Activity.objects.filter(patient=patient).order_by('-recorded_at')[:10]
    appointments = Appointment.objects.filter(
        patient=patient, appointment_date__gte=today, status__in=['pending', 'confirmed']
    ).select_related('doctor').order_by('appointment_date')[:5]
    reports = Report.objects.filter(patient=patient).order_by('-created_at')[:5]
    risk = RiskScore.objects.filter(patient=patient).first()

    week_logs = MedicineLog.objects.filter(patient=patient, scheduled_time__date__gte=today - timedelta(days=6))
    taken = week_logs.filter(status='taken').count()
    total_logs = week_logs.count()
    adherence = int(taken / total_logs * 100) if total_logs > 0 else 0

    try:
        profile = patient.patient_profile
    except Exception:
        profile = None

    chart_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        dl = MedicineLog.objects.filter(patient=patient, scheduled_time__date=d)
        dt = dl.filter(status='taken').count()
        dn = dl.count()
        chart_data.append({'day': d.strftime('%a'), 'pct': int(dt / dn * 100) if dn > 0 else 0, 'taken': dt, 'total': dn})

    context = {
        'patient': patient,
        'profile': profile,
        'assignment': assignment,
        'medicines': medicines,
        'today_logs': today_logs,
        'activities': activities,
        'appointments': appointments,
        'reports': reports,
        'risk': risk,
        'adherence': adherence,
        'chart_data': chart_data,
        'today': today,
        'now': now,
    }
    return render(request, 'dashboard/caregiver/patient_detail.html', context)


@login_required
@caregiver_required
@require_POST
def caregiver_mark_medicine(request, med_id):
    """Caregiver marks medicine as taken on behalf of patient."""
    user = request.user
    med = get_object_or_404(Medicine, id=med_id)
    action = request.POST.get('action', 'taken')

    assignment = CaregiverPatientAssignment.objects.filter(
        caregiver=user, patient=med.patient, status='active', can_mark_medicines=True
    ).first()
    if not assignment:
        return JsonResponse({'success': False, 'error': 'Not authorized to mark medicines for this patient'})

    today = date.today()
    now = timezone.now()

    if action == 'taken':
        today_taken = med.logs.filter(scheduled_time__date=today, status='taken').count()
        if today_taken >= med.max_daily_doses:
            return JsonResponse({
                'success': False,
                'error': 'overdose',
                'message': f'⚠️ {med.patient.get_full_name()} has already taken the maximum dose of {med.name} today.',
            })

    MedicineLog.objects.create(
        medicine=med, patient=med.patient,
        marked_by=user, scheduled_time=now,
        taken_at=now if action == 'taken' else None,
        status=action,
    )

    if action == 'taken' and med.stock_quantity > 0:
        med.stock_quantity -= 1
        med.save()

    notify_user(
        user=med.patient,
        title='💊 Medicine Marked by Caregiver',
        message=f'Your caregiver {user.get_full_name()} marked {med.name} as {action}.',
        notification_type='medicine',
        priority='low',
        category=f'caregiver_mark_{med.id}_{action}'
    )

    action_map = {'taken': 'medicine_taken', 'skipped': 'medicine_skipped', 'missed': 'medicine_missed'}
    log_caregiver_action(
        assignment, user, action_map.get(action, 'other'),
        f'Marked {med.name} as {action}',
    )

    return JsonResponse({
        'success': True,
        'message': f'{med.name} marked as {action}',
        'taken_today': med.logs.filter(scheduled_time__date=today, status='taken').count(),
        'max_doses': med.max_daily_doses,
        'stock': med.stock_quantity,
    })


@login_required
@caregiver_required
def caregiver_log_activity(request, patient_id):
    patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
    assignment = get_object_or_404(CaregiverPatientAssignment, caregiver=request.user, patient=patient, status='active', can_log_activities=True)

    if request.method == 'POST':
        activity_type = request.POST.get('activity_type')
        title = request.POST.get('title')
        description = request.POST.get('description', '')
        duration = request.POST.get('duration_minutes')
        file_upload = request.FILES.get('file_upload')

        Activity.objects.create(
            patient=patient,
            logged_by=request.user,
            activity_type=activity_type,
            title=title,
            description=description,
            duration_minutes=duration if duration else None,
            file_upload=file_upload,
        )
        messages.success(request, 'Activity logged successfully.')
        return redirect('caregiver_patient_detail', patient_id=patient.id)

    return render(request, 'dashboard/caregiver/log_activity.html', {'patient': patient, 'assignment': assignment})


def _doctor_connected_patients(doctor):
    conns = DoctorPatientConnection.objects.filter(
        doctor=doctor, status='accepted',
    ).select_related('patient', 'patient__patient_profile')
    return [c.patient for c in conns]


def _patient_info_bundle(patient, doctor):
    try:
        profile = patient.patient_profile
    except Exception:
        profile = None
    address_parts = []
    if profile:
        if profile.address:
            address_parts.append(profile.address)
        city_line = ', '.join(filter(None, [profile.city, profile.state, profile.pincode]))
        if city_line:
            address_parts.append(city_line)
    return {
        'patient': patient,
        'profile': profile,
        'address': ' · '.join(address_parts) if address_parts else '—',
        'condition': profile.primary_diagnosis if profile and profile.primary_diagnosis else '—',
        'emergency_contact': (
            f"{profile.emergency_contact_name} ({profile.emergency_contact_phone})"
            if profile and profile.emergency_contact_name else '—'
        ),
        'assigned_doctor': doctor,
    }


def _deactivate_system_assignment(hospital_assignment):
    if hospital_assignment.system_assignment_id:
        sa = hospital_assignment.system_assignment
        sa.status = 'inactive'
        sa.save(update_fields=['status', 'updated_at'])


def _deactivate_caregiver_by_source(patient, source, source_id, doctor):
    """Deactivate a hospital caregiver assigned by this doctor only."""
    if source != 'hospital':
        raise ValueError('Doctors may only deactivate hospital caregivers they assigned.')
    assignment = get_object_or_404(
        HospitalCaregiverAssignment,
        id=source_id,
        patient=patient,
        assigned_by_doctor=doctor,
        status='active',
    )
    assignment.status = 'inactive'
    assignment.deactivated_at = timezone.now()
    assignment.save(update_fields=['status', 'deactivated_at', 'updated_at'])
    _deactivate_system_assignment(assignment)
    if assignment.caregiver_user:
        notify_user(
            user=assignment.caregiver_user,
            title='Caregiver Access Deactivated',
            message=f'Your hospital caregiver access for {patient.get_full_name()} has been deactivated by Dr. {doctor.get_full_name()}.',
            notification_type='general',
            priority='medium',
            category=f'hospital_cg_off_{assignment.id}',
        )
    return assignment.caregiver_name


def _replace_hospital_caregiver(patient, doctor):
    """Mark the active hospital caregiver as replaced before assigning a new one."""
    active = get_any_active_caregiver_for_patient(patient)
    if not active or not active['is_hospital']:
        raise ValueError('Only an active hospital caregiver can be replaced.')
    assignment = get_object_or_404(
        HospitalCaregiverAssignment,
        id=active['source_id'],
        patient=patient,
        assigned_by_doctor=doctor,
        status='active',
    )
    assignment.status = 'replaced'
    assignment.deactivated_at = timezone.now()
    assignment.save(update_fields=['status', 'deactivated_at', 'updated_at'])
    _deactivate_system_assignment(assignment)
    return assignment


def _deactivate_all_active_caregivers(patient, doctor, replace_hospital=False):
    """Legacy helper — replace flow now uses _replace_hospital_caregiver only."""
    if replace_hospital:
        _replace_hospital_caregiver(patient, doctor)
        return
    active = get_any_active_caregiver_for_patient(patient)
    if active and active['is_hospital']:
        _deactivate_caregiver_by_source(patient, active['source'], active['source_id'], doctor)


def _activate_system_assignment(hospital_assignment, doctor, caregiver_user):
    if not caregiver_user:
        _deactivate_system_assignment(hospital_assignment)
        hospital_assignment.system_assignment = None
        hospital_assignment.caregiver_user = None
        hospital_assignment.save(update_fields=['system_assignment', 'caregiver_user', 'updated_at'])
        return

    other = HospitalCaregiverAssignment.objects.filter(
        caregiver_user=caregiver_user, status='active',
    ).exclude(pk=hospital_assignment.pk).first()
    if other:
        raise ValueError(
            f'{caregiver_user.get_full_name()} is already assigned to {other.patient.get_full_name()}.'
        )

    existing_active = CaregiverPatientAssignment.objects.filter(
        patient=hospital_assignment.patient, status='active',
    ).exclude(pk=hospital_assignment.system_assignment_id or 0)
    existing_active.update(status='inactive')

    assignment, _ = CaregiverPatientAssignment.objects.update_or_create(
        caregiver=caregiver_user,
        patient=hospital_assignment.patient,
        defaults={
            'assigned_by': doctor,
            'status': 'active',
            'can_mark_medicines': True,
            'can_manage_appointments': True,
            'can_upload_reports': True,
            'can_log_activities': True,
            'notes': hospital_assignment.responsibilities,
            'approved_at': timezone.now(),
        },
    )
    CaregiverPatientAssignment.objects.filter(
        caregiver=caregiver_user, status='active',
    ).exclude(pk=assignment.pk).update(status='inactive')

    hospital_assignment.caregiver_user = caregiver_user
    hospital_assignment.system_assignment = assignment
    hospital_assignment.save(update_fields=['caregiver_user', 'system_assignment', 'updated_at'])

    notify_user(
        user=caregiver_user,
        title='Hospital Caregiver Assignment',
        message=(
            f'Dr. {doctor.get_full_name()} assigned you as hospital caregiver for '
            f'{hospital_assignment.patient.get_full_name()}. You have access to their patient dashboard.'
        ),
        notification_type='general',
        priority='medium',
        category=f'hospital_cg_{hospital_assignment.id}',
        related_id=hospital_assignment.id,
    )


def _parse_hospital_form(request):
    start_raw = request.POST.get('start_date') or None
    end_raw = request.POST.get('end_date') or None
    duration_type = request.POST.get('duration_type', 'permanent')
    start_date = None
    end_date = None
    if start_raw:
        try:
            start_date = date.fromisoformat(start_raw)
        except ValueError:
            pass
    if end_raw and duration_type == 'temporary':
        try:
            end_date = date.fromisoformat(end_raw)
        except ValueError:
            pass
    return {
        'caregiver_name': request.POST.get('caregiver_name', '').strip(),
        'caregiver_role': request.POST.get('caregiver_role', 'hospital_caregiver'),
        'department': request.POST.get('department', 'general_care'),
        'contact_number': request.POST.get('contact_number', '').strip(),
        'responsibilities': request.POST.get('responsibilities', '').strip(),
        'duration_type': duration_type,
        'start_date': start_date,
        'end_date': end_date,
        'caregiver_user_id': request.POST.get('caregiver_user_id', '').strip(),
    }


@login_required
def doctor_assign_caregiver(request):
    """Hospital caregiver management — list all assignments for doctor's patients."""
    user = request.user
    if user.role != 'doctor':
        return redirect(user.get_dashboard_url())

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'deactivate_caregiver':
            patient_id = request.POST.get('patient_id')
            patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
            if not DoctorPatientConnection.objects.filter(doctor=user, patient=patient, status='accepted').exists():
                messages.error(request, 'You are not connected to this patient.')
                return redirect('doctor_assign_caregiver')
            source = request.POST.get('caregiver_source')
            source_id = request.POST.get('caregiver_source_id')
            if source != 'hospital':
                messages.error(request, 'This caregiver is managed outside hospital care and cannot be modified.')
                return redirect(f"{reverse('doctor_hospital_caregiver_new')}?patient_id={patient.id}")
            try:
                name = _deactivate_caregiver_by_source(patient, source, source_id, user)
                messages.info(
                    request,
                    f'Hospital caregiver {name} has been deactivated. You may assign a new hospital caregiver.',
                )
            except Exception:
                messages.error(request, 'Unable to deactivate hospital caregiver. Please try again.')
            return redirect(f"{reverse('doctor_hospital_caregiver_new')}?patient_id={patient.id}")

        assignment_id = request.POST.get('assignment_id')
        assignment = get_object_or_404(
            HospitalCaregiverAssignment, id=assignment_id, assigned_by_doctor=user,
        )

        if action == 'deactivate':
            assignment.status = 'inactive'
            assignment.deactivated_at = timezone.now()
            assignment.save(update_fields=['status', 'deactivated_at', 'updated_at'])
            _deactivate_system_assignment(assignment)
            if assignment.caregiver_user:
                notify_user(
                    user=assignment.caregiver_user,
                    title='Caregiver Access Deactivated',
                    message=f'Your hospital caregiver access for {assignment.patient.get_full_name()} has been deactivated.',
                    notification_type='general',
                    priority='medium',
                    category=f'hospital_cg_off_{assignment.id}',
                )
            messages.info(request, f'Hospital caregiver deactivated for {assignment.patient.get_full_name()}. You may assign a new hospital caregiver.')

        elif action == 'reactivate':
            if patient_has_active_caregiver(assignment.patient):
                messages.error(request, 'This patient already has an active caregiver. Replace or deactivate first.')
                return redirect('doctor_assign_caregiver')
            assignment.status = 'active'
            assignment.deactivated_at = None
            assignment.save(update_fields=['status', 'deactivated_at', 'updated_at'])
            if assignment.caregiver_user:
                try:
                    _activate_system_assignment(assignment, user, assignment.caregiver_user)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    assignment.status = 'inactive'
                    assignment.save(update_fields=['status', 'updated_at'])
                    return redirect('doctor_assign_caregiver')
            messages.success(request, f'Caregiver reactivated for {assignment.patient.get_full_name()}.')

        elif action == 'remove':
            reason = request.POST.get('removal_reason', '').strip()
            assignment.status = 'removed'
            assignment.removed_at = timezone.now()
            assignment.removed_by = user
            assignment.removal_reason = reason
            assignment.save(update_fields=['status', 'removed_at', 'removed_by', 'removal_reason', 'updated_at'])
            _deactivate_system_assignment(assignment)
            messages.success(request, f'Hospital caregiver removed for {assignment.patient.get_full_name()}.')

        redirect_patient_id = request.POST.get('redirect_patient_id')
        if redirect_patient_id and action in ('deactivate', 'remove'):
            return redirect(f"{reverse('doctor_hospital_caregiver_new')}?patient_id={redirect_patient_id}")
        return redirect('doctor_assign_caregiver')

    assignments = get_doctor_hospital_assignments(user)
    active_count = assignments.filter(status='active').count()
    inactive_count = assignments.filter(status='inactive').count()

    return render(request, 'dashboard/doctor/assign_caregiver.html', {
        'assignments': assignments,
        'active_count': active_count,
        'inactive_count': inactive_count,
        'role_choices': HOSPITAL_ROLE_CHOICES,
    })


@login_required
def doctor_hospital_caregiver_form(request, assignment_id=None):
    """Create or edit a hospital caregiver assignment."""
    user = request.user
    if user.role != 'doctor':
        return redirect(user.get_dashboard_url())

    patients = _doctor_connected_patients(user)
    editing = assignment_id is not None
    assignment = None
    if editing:
        assignment = get_object_or_404(
            HospitalCaregiverAssignment, id=assignment_id, assigned_by_doctor=user,
        )
        if assignment.status in ('removed', 'replaced'):
            messages.error(request, 'This assignment is archived and cannot be edited.')
            return redirect('doctor_assign_caregiver')

    hospital_staff = CustomUser.objects.filter(
        role='caregiver', is_active=True,
    ).select_related('caregiver_profile').order_by('first_name')

    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
        if not DoctorPatientConnection.objects.filter(doctor=user, patient=patient, status='accepted').exists():
            messages.error(request, 'You are not connected to this patient.')
            return redirect('doctor_assign_caregiver')

        data = _parse_hospital_form(request)
        if not data['caregiver_name']:
            messages.error(request, 'Caregiver name is required.')
            return redirect(request.path)

        action = request.POST.get('action', 'assign')
        caregiver_user = None
        if data['caregiver_user_id']:
            caregiver_user = get_object_or_404(CustomUser, id=data['caregiver_user_id'], role='caregiver')

        if action == 'replace':
            try:
                _replace_hospital_caregiver(patient, user)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect(f"{reverse('doctor_hospital_caregiver_new')}?patient_id={patient.id}")
        elif not editing and action != 'replace':
            active = get_any_active_caregiver_for_patient(patient)
            if active:
                if active['is_hospital'] and active['hospital_assignment'].assigned_by_doctor_id == user.id:
                    msg = 'This patient already has an active hospital caregiver. Replace or deactivate it first.'
                else:
                    msg = 'This patient already has an active caregiver managed outside hospital care.'
                messages.info(request, msg)
                return redirect(f"{reverse('doctor_hospital_caregiver_new')}?patient_id={patient.id}")

        if editing and action == 'update':
            target = assignment
        else:
            target = HospitalCaregiverAssignment(assigned_by_doctor=user, patient=patient, status='active')

        target.caregiver_name = data['caregiver_name']
        target.caregiver_role = data['caregiver_role']
        target.department = data['department']
        target.contact_number = data['contact_number']
        target.responsibilities = data['responsibilities']
        target.duration_type = data['duration_type']
        target.start_date = data['start_date']
        target.end_date = data['end_date']
        target.status = 'active'
        target.deactivated_at = None
        target.save()

        if action == 'replace':
            replaced = HospitalCaregiverAssignment.objects.filter(
                patient=patient, assigned_by_doctor=user, status__in=('replaced', 'inactive'),
            ).order_by('-updated_at').first()
            if replaced:
                replaced.replaced_by = target
                replaced.status = 'replaced'
                replaced.save(update_fields=['replaced_by', 'status', 'updated_at'])

        try:
            _activate_system_assignment(target, user, caregiver_user)
        except ValueError as exc:
            messages.error(request, str(exc))
            if not editing:
                target.delete()
            return redirect('doctor_hospital_caregiver_edit' if editing else 'doctor_hospital_caregiver_new')

        notify_user(
            user=patient,
            title='Hospital Caregiver Assigned',
            message=f'Dr. {user.get_full_name()} assigned {target.caregiver_name} ({target.role_display}) as your hospital caregiver.',
            notification_type='general',
            priority='medium',
            category=f'hospital_cg_{target.id}',
            related_id=target.id,
        )

        verb = 'updated' if editing and action == 'update' else 'assigned'
        messages.success(request, f'Hospital caregiver {verb} for {patient.get_full_name()}.')
        return redirect('doctor_hospital_caregiver_detail', assignment_id=target.id)

    selected_patient = assignment.patient if assignment else None
    patient_id = request.GET.get('patient_id')
    if patient_id and not selected_patient:
        selected_patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
        if not DoctorPatientConnection.objects.filter(doctor=user, patient=selected_patient, status='accepted').exists():
            messages.error(request, 'You are not connected to this patient.')
            return redirect('doctor_hospital_caregiver_new')

    replace_mode = request.GET.get('replace') == '1'
    existing_active_caregiver = None
    can_manage_hospital_caregiver = False
    caregiver_conflict_type = None
    if selected_patient and not editing:
        existing_active_caregiver = get_any_active_caregiver_for_patient(selected_patient)
        if existing_active_caregiver:
            if existing_active_caregiver['is_hospital']:
                can_manage_hospital_caregiver = (
                    existing_active_caregiver['hospital_assignment'].assigned_by_doctor_id == user.id
                )
                caregiver_conflict_type = (
                    'hospital_manageable' if can_manage_hospital_caregiver else 'hospital_readonly'
                )
            else:
                caregiver_conflict_type = 'external'
        if replace_mode:
            if not can_manage_hospital_caregiver:
                messages.error(
                    request,
                    'Hospital caregiver replacement is unavailable while a non-hospital caregiver is active.',
                )
                return redirect(f"{reverse('doctor_hospital_caregiver_new')}?patient_id={selected_patient.id}")

    patient_info = _patient_info_bundle(selected_patient, user) if selected_patient else None
    show_assignment_form = bool(
        editing or replace_mode or (patient_info and not existing_active_caregiver)
    )

    return render(request, 'dashboard/doctor/hospital_caregiver_form.html', {
        'patients': patients,
        'assignment': assignment,
        'selected_patient': selected_patient,
        'patient_info': patient_info,
        'existing_active_caregiver': existing_active_caregiver,
        'can_manage_hospital_caregiver': can_manage_hospital_caregiver,
        'caregiver_conflict_type': caregiver_conflict_type,
        'show_assignment_form': show_assignment_form,
        'hospital_staff': hospital_staff,
        'role_choices': HOSPITAL_ROLE_CHOICES,
        'department_choices': HOSPITAL_DEPARTMENT_CHOICES,
        'duration_choices': HOSPITAL_DURATION_CHOICES,
        'editing': editing,
        'replace_mode': replace_mode,
        'multiple_patients': len(patients) > 1,
    })


@login_required
def doctor_hospital_caregiver_detail(request, assignment_id):
    user = request.user
    if user.role != 'doctor':
        return redirect(user.get_dashboard_url())

    assignment = get_object_or_404(
        HospitalCaregiverAssignment, id=assignment_id, assigned_by_doctor=user,
    )
    patient_info = _patient_info_bundle(assignment.patient, user)

    return render(request, 'dashboard/doctor/hospital_caregiver_detail.html', {
        'assignment': assignment,
        'patient_info': patient_info,
    })


@login_required
def caregiver_profile_detail(request, caregiver_id):
    """View a caregiver's profile. Accessible to connected patients or any caregiver/admin."""
    caregiver = get_object_or_404(CustomUser, id=caregiver_id, role='caregiver')

    # Authorization:
    # 1. User is the caregiver themselves
    # 2. User is an admin
    # 3. User is a patient connected to this caregiver
    if request.user.id == caregiver.id or request.user.role == 'admin':
        authorized = True
    elif request.user.role == 'patient':
        authorized = CaregiverPatientAssignment.objects.filter(
            caregiver=caregiver, patient=request.user, status='active'
        ).exists()
    else:
        authorized = False

    if not authorized:
        messages.error(request, 'You are not authorized to view this profile.')
        return redirect(request.user.get_dashboard_url())

    try:
        profile = caregiver.caregiver_profile
    except Exception:
        profile = None

    # If accessed by a patient, we can show the "Connected Since" date
    assignment = None
    if request.user.role == 'patient':
        assignment = CaregiverPatientAssignment.objects.filter(
            caregiver=caregiver, patient=request.user, status='active'
        ).first()

    context = {
        'caregiver': caregiver,
        'profile': profile,
        'assignment': assignment,
    }
    return render(request, 'dashboard/caregiver/profile.html', context)


@login_required
def disconnect_caregiver(request, assignment_id):
    """Caregiver or doctor (hospital-assigned) disconnects with reason. Patients cannot disconnect."""
    user = request.user
    assignment = get_object_or_404(CaregiverPatientAssignment, id=assignment_id)

    authorized = False
    disconnected_by_role = ''

    if user.role == 'caregiver' and assignment.caregiver == user:
        authorized = True
        disconnected_by_role = 'Caregiver'
    elif user.role == 'admin':
        authorized = True
        disconnected_by_role = 'Admin'
    elif user.role == 'doctor':
        hospital = HospitalCaregiverAssignment.objects.filter(
            system_assignment=assignment, assigned_by_doctor=user, status='active',
        ).first()
        if hospital:
            authorized = True
            disconnected_by_role = 'Doctor'
            hospital.status = 'inactive'
            hospital.deactivated_at = timezone.now()
            hospital.removed_by = user
            hospital.removal_reason = request.POST.get('reason', '')
            hospital.save()

    if not authorized:
        messages.error(request, 'You are not authorized to end this connection.')
        return redirect(user.get_dashboard_url())

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, 'Please provide a reason for disconnecting.')
            return redirect(request.META.get('HTTP_REFERER', 'caregiver_my_patient'))

        assignment.status = 'inactive'
        assignment.disconnected_at = timezone.now()
        assignment.disconnected_by = user
        assignment.disconnect_reason = reason
        assignment.save()

        log_caregiver_action(
            assignment, assignment.caregiver, 'disconnected',
            f'Disconnected by {disconnected_by_role}: {reason}',
        )

        if user.role == 'caregiver':
            exit_caregiver_mode(request)
            notify_user(
                user=assignment.patient,
                title='Caregiver Disconnected',
                message=f'Your caregiver {assignment.caregiver.get_full_name()} has ended the care relationship. Reason: {reason}',
                notification_type='general',
                priority='medium',
                category=f'caregiver_disconnect_{assignment.id}',
            )
            messages.success(request, 'Patient disconnected successfully.')
            return redirect('caregiver_my_patient')

        notify_user(
            user=assignment.caregiver,
            title='Caregiver Access Removed',
            message=f'Dr. {user.get_full_name()} removed your caregiver access for {assignment.patient.get_full_name()}. Reason: {reason}',
            notification_type='general',
            priority='medium',
            category=f'caregiver_disconnect_{assignment.id}',
        )
        messages.success(request, 'Caregiver disconnected successfully.')
        return redirect('doctor_assign_caregiver')

    return redirect(user.get_dashboard_url())


@login_required
@caregiver_required
def caregiver_enter_patient_mode(request, patient_id):
    """Enter caregiver mode — act on behalf of patient with full dashboard access."""
    patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
    if not enter_caregiver_mode(request, patient):
        messages.error(request, 'You are not connected to this patient.')
        return redirect('caregiver_my_patient')
    messages.info(request, f'Caregiver Mode: Acting for {patient.get_full_name()}')
    return redirect('/dashboard/patient/')


@login_required
@caregiver_required
def caregiver_exit_patient_mode(request):
    exit_caregiver_mode(request)
    messages.info(request, 'Exited caregiver mode.')
    return redirect('caregiver_dashboard')


@login_required
@caregiver_required
def caregiver_book_appointment(request):
    """Allows caregivers to book appointments for their assigned patients."""
    user = request.user
    patient_id = request.GET.get('patient_id')

    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        doctor_id = request.POST.get('doctor_id')
        apt_date = request.POST.get('appointment_date')
        apt_time = request.POST.get('appointment_time')
        apt_type = request.POST.get('appointment_type', 'in_person')
        reason = request.POST.get('reason', '')
        is_emergency = request.POST.get('is_emergency') == '1'

        if not all([patient_id, doctor_id, apt_date, apt_time]):
            messages.error(request, 'Please fill all required fields.')
            return redirect('caregiver_book_appointment')

        patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
        assignment = CaregiverPatientAssignment.objects.filter(caregiver=user, patient=patient, status='active').first()

        if not assignment or not assignment.can_manage_appointments:
            messages.error(request, 'You do not have permission to book appointments for this patient.')
            return redirect('caregiver_dashboard')

        doctor = get_object_or_404(CustomUser, id=doctor_id, role='doctor')

        apt = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            appointment_date=apt_date,
            appointment_time=apt_time,
            appointment_type=apt_type,
            reason=reason,
            is_emergency=is_emergency,
        )

        if apt_type in ('video', 'emergency_video'):
            apt.generate_video_link()

        notify_user(
            user=doctor,
            title='🗓 Appointment Booked by Caregiver' + (' [EMERGENCY]' if is_emergency else ''),
            message=f'Caregiver {user.get_full_name()} booked a {apt.get_appointment_type_display()} appointment for {patient.get_full_name()} on {apt_date} at {apt_time}.',
            notification_type='appointment',
            priority='high' if is_emergency else 'medium',
            category=f'apt_req_{apt.id}',
            related_id=apt.id
        )

        notify_user(
            user=patient,
            title='🗓 New Appointment Scheduled',
            message=f'Your caregiver {user.get_full_name()} has scheduled an appointment for you with Dr. {doctor.get_full_name()} on {apt_date} at {apt_time}.',
            notification_type='appointment',
            priority='medium',
            category=f'apt_req_{apt.id}',
            related_id=apt.id
        )
        messages.success(request, 'Appointment booked successfully!')
        return redirect('caregiver_patient_detail', patient_id=patient.id)

    # GET Request
    patients = CaregiverPatientAssignment.objects.filter(caregiver=user, status='active').select_related('patient')
    doctors = []
    selected_patient = None

    if patient_id:
        selected_patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
        conns = DoctorPatientConnection.objects.filter(patient=selected_patient, status='accepted')
        doctors = [c.doctor for c in conns]

    context = {
        'patients': patients,
        'doctors': doctors,
        'selected_patient': selected_patient,
    }
    return render(request, 'dashboard/caregiver/book_appointment.html', context)
