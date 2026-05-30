from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta, date
from apps.accounts.models import CustomUser
from apps.medicines.models import Medicine, MedicineLog, RiskScore, Activity, DailyHealthCheck, FamilyContact
from apps.appointments.models import Appointment
from apps.notifications.models import Notification
from apps.connections.models import DoctorPatientConnection
from apps.profiles.models import PatientProfile, DoctorProfile
from apps.reports.models import Report
from apps.medicines.views import calculate_risk_score
from django.conf import settings 

@login_required
def dashboard_redirect(request):
    user = request.user
    if not user.profile_completed and user.role != 'admin':
        return redirect('/profile/complete/')
    return redirect(user.get_dashboard_url())


@login_required
def patient_dashboard(request):
    from apps.caregiver.access import resolve_patient_for_request, get_acting_patient
    caregiver_mode = False
    acting_patient = None

    if request.user.role == 'caregiver':
        patient_user, caregiver_mode = resolve_patient_for_request(request)
        if not patient_user:
            messages.info(request, 'Connect to a patient to access their dashboard.')
            return redirect('caregiver_my_patient')
        user = patient_user
        acting_patient = request.user
        caregiver_mode = get_acting_patient(request) is not None
    elif request.user.role == 'patient':
        user = request.user
        if not user.profile_completed:
            return redirect('/profile/patient/')
    else:
        return redirect(request.user.get_dashboard_url())

    today = date.today()
    now = timezone.localtime()
    medicines = Medicine.objects.filter(patient=user, is_active=True)

    from apps.medicines.medicine_schedule_utils import attach_medicine_dose_ui
    for m in medicines:
        attach_medicine_dose_ui(m, user, today, now)

    today_logs = MedicineLog.objects.filter(patient=user, scheduled_time__date=today)
    week_logs = MedicineLog.objects.filter(patient=user, scheduled_time__date__gte=today - timedelta(days=6))
    taken = week_logs.filter(status='taken').count()
    total = week_logs.count()
    compliance_pct = int((taken / total * 100) if total > 0 else 0)

    # Recalculate risk
    risk = calculate_risk_score(user)

    upcoming_apts = Appointment.objects.filter(
        patient=user, appointment_date__gte=today,
        status__in=[
            'pending', 'pending_confirmation', 'pending_doctor_confirmation',
            'doctor_confirmed', 'patient_confirmed', 'confirmed', 'ongoing'
        ]
    ).select_related('doctor', 'doctor__doctor_profile').order_by('appointment_date', 'appointment_time')[:5]

    from apps.medicines.activity_utils import categorize_activity_logs, get_active_schedule_summaries

    activities = Activity.objects.filter(patient=user, is_active=True)[:5]
    activity_sections = categorize_activity_logs(user, today)
    activity_schedules = get_active_schedule_summaries(user)[:4]
    dashboard_activities = (
        activity_sections['today']
        + activity_sections['upcoming']
    )
    dashboard_activities.sort(key=lambda x: x['log'].scheduled_time)
    from apps.notifications.notification_utils import today_notifications_for_user

    notifications = list(today_notifications_for_user(user, limit=5, unread_only=False))
    unread_count = Notification.objects.filter(user=user, is_read=False).count()

    chart_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        dl = MedicineLog.objects.filter(patient=user, scheduled_time__date=d)
        dt = dl.filter(status='taken').count()
        dn = dl.count()
        chart_data.append({'day': d.strftime('%a'), 'pct': int(dt/dn*100) if dn > 0 else 0, 'taken': dt, 'total': dn})

    try:
        profile = user.patient_profile
    except Exception:
        profile = None

    connected_doctors = DoctorPatientConnection.objects.filter(
        patient=user, status='accepted'
    ).select_related('doctor', 'doctor__doctor_profile')

    pending_requests = DoctorPatientConnection.objects.filter(
        patient=user, status='pending'
    ).exclude(requested_by=user)

    reports = Report.objects.filter(patient=user)[:3]

    from apps.medicines.inventory_service import get_patient_stock_alert_cards
    stock_alert_cards = get_patient_stock_alert_cards(user)

    # Legacy stock lists for widgets
    low_stock = [m for m in medicines if m.is_low_stock and not m.is_critical_stock]
    critical_stock = [m for m in medicines if m.is_critical_stock]

    # Today's health check
    health_checked_today = DailyHealthCheck.objects.filter(patient=user, checked_at__date=today).exists()

    hour = timezone.localtime().hour
    greeting = 'Good Morning' if hour < 12 else 'Good Afternoon' if hour < 17 else 'Good Evening'

    from apps.caregiver.models import CaregiverPatientAssignment
    pending_caregiver_requests = CaregiverPatientAssignment.objects.filter(
        patient=user, status='pending'
    ).select_related('caregiver')
    active_caregivers = CaregiverPatientAssignment.objects.filter(
        patient=user, status='active'
    ).select_related('caregiver')

    context = {
        'user': user, 'profile': profile,
        'medicines': medicines, 'today_logs': today_logs,
        'compliance_pct': compliance_pct,
        'risk': risk, 'upcoming_apts': upcoming_apts,
        'activities': activities, 'activity_sections': activity_sections,
        'dashboard_activities': dashboard_activities,
        'activity_schedules': activity_schedules,
        'unread_count': unread_count, 'chart_data': chart_data,
        'today': today, 'greeting': greeting,
        'connected_doctors': connected_doctors,
        'pending_requests': pending_requests,
        'reports': reports, 'low_stock': low_stock,
        'critical_stock': critical_stock,
        'stock_alert_cards': stock_alert_cards,
        'total_taken': taken, 'total_logs': total,
        'health_checked_today': health_checked_today,
        'pending_caregiver_requests': pending_caregiver_requests,
        'active_caregivers': active_caregivers,
        'caregiver_mode': caregiver_mode,
        'acting_caregiver': acting_patient,
    }
    return render(request, 'dashboard/patient/index.html', context)


@login_required
def doctor_dashboard(request):
    from apps.appointments.emergency_utils import expire_stale_emergencies_for_doctor

    user = request.user
    if user.role != 'doctor':
        return redirect(user.get_dashboard_url())
    if not user.profile_completed:
        return redirect('/profile/doctor/')

    expire_stale_emergencies_for_doctor(user)

    today = date.today()
    conns = DoctorPatientConnection.objects.filter(doctor=user, status='accepted')
    patients = [c.patient for c in conns]

    pending_requests = DoctorPatientConnection.objects.filter(
        doctor=user, status='pending'
    ).exclude(requested_by=user)

    today_apts = Appointment.objects.filter(
        doctor=user, appointment_date=today,
        status__in=[
            'pending', 'pending_confirmation', 'pending_doctor_confirmation',
            'doctor_confirmed', 'patient_confirmed', 'confirmed', 'ongoing'
        ],
    ).select_related('patient').order_by('appointment_time')

    for apt in today_apts:
        apt.role_status = apt.get_role_based_status(user)

    upcoming_apts = Appointment.objects.filter(
        doctor=user, appointment_date__gte=today,
        status__in=[
            'pending', 'pending_confirmation', 'pending_doctor_confirmation',
            'doctor_confirmed', 'patient_confirmed', 'confirmed', 'ongoing'
        ]
    ).select_related('patient')[:10]

    for apt in upcoming_apts:
        apt.role_status = apt.get_role_based_status(user)

    pending_apts = Appointment.objects.filter(
        doctor=user,
        status__in=['pending', 'pending_confirmation', 'pending_doctor_confirmation']
    ).count()
    from apps.notifications.notification_utils import today_notifications_for_user

    notifications = list(today_notifications_for_user(user, limit=5, unread_only=False))
    unread_count = Notification.objects.filter(user=user, is_read=False).count()

    from apps.messaging.models import Message
    unread_messages = Message.objects.filter(receiver=user, is_read=False).count()

    try:
        profile = user.doctor_profile
    except Exception:
        profile = None

    def _risk_badge(risk):
        types = risk.risk_types or []
        if 'medication' in types:
            return {'icon': '💊', 'label': 'Medication Risk', 'bg': 'bg-amber-100', 'text': 'text-amber-800'}
        if 'physical' in types:
            return {'icon': '🏃', 'label': 'Physical Health Risk', 'bg': 'bg-orange-100', 'text': 'text-orange-800'}
        if 'emergency' in types:
            return {'icon': '🚨', 'label': 'Emergency Risk', 'bg': 'bg-red-100', 'text': 'text-red-800'}
        if 'appointment' in types:
            return {'icon': '📅', 'label': 'Appointment Risk', 'bg': 'bg-violet-100', 'text': 'text-violet-800'}
        factors = risk.factors or {}
        if 'consecutive_misses' in factors or 'miss_rate' in factors:
            return {'icon': '💊', 'label': 'Medication Risk', 'bg': 'bg-amber-100', 'text': 'text-amber-800'}
        return {'icon': '⚠', 'label': 'Health Risk', 'bg': 'bg-red-100', 'text': 'text-red-800'}

    high_risk_patients = []
    for p in patients[:15]:
        try:
            risk = p.risk_score
        except RiskScore.DoesNotExist:
            risk = None
        if not risk:
            risk = RiskScore.objects.filter(patient=p).first()
        if risk and risk.level in ('high', 'critical'):
            dynamic = risk.dynamic_analysis or {}
            top_insight = (dynamic.get('medicine_insights') or [None])[0]
            high_risk_patients.append({
                'patient': p,
                'risk': risk,
                'badge': _risk_badge(risk),
                'type_labels': risk.risk_type_labels[:3],
                'top_reason': (dynamic.get('why_risk_increased') or risk.reasons or ['Repeated health compliance issues'])[0],
                'top_action': (risk.recommended_actions or ['Consult patient'])[0],
                'prediction': dynamic.get('prediction_summary') or (
                    (risk.health_impacts or ['Health deterioration risk'])[0]
                ),
                'medicine_insight': top_insight,
            })

    active_emergency_apts = Appointment.objects.filter(
        doctor=user,
        appointment_type='emergency_video',
        is_emergency=True,
        status='pending_doctor_confirmation',
    ).select_related('patient').order_by('-created_at')

    emergency_count = active_emergency_apts.count()

    from apps.appointments.emergency_utils import get_unseen_missed_emergencies_today

    unseen_missed_qs = get_unseen_missed_emergencies_today(user, today)
    missed_alert_apt = unseen_missed_qs.first()
    unseen_missed_count = unseen_missed_qs.count()

    pending_request_apts_qs = Appointment.objects.filter(
        doctor=user,
        status__in=['pending', 'pending_confirmation', 'pending_doctor_confirmation'],
    ).select_related('patient').order_by('appointment_date', 'appointment_time')

    pending_request_apts = pending_request_apts_qs[:25]

    for apt in pending_request_apts:
        apt.role_status = apt.get_role_based_status(user)

    pending_normal_count = pending_request_apts_qs.exclude(
        appointment_type='emergency_video',
        status='pending_doctor_confirmation',
    ).count()

    reports_generated = Report.objects.filter(doctor=user).count()

    from apps.medicines.activity_utils import get_doctor_activity_monitoring
    from apps.medicines.risk_alert_service import get_alerts_for_user
    from apps.payments.services import doctor_earnings_summary
    patient_activity_monitoring = get_doctor_activity_monitoring(user)
    earnings_summary = doctor_earnings_summary(user)

    # Emergency history lives on /appointments/history/ (not embedded on dashboard home).
    emergency_history_today = []

    context = {
        'user': user, 'profile': profile,
        'patients': patients[:8], 'total_patients': len(patients),
        'today_apts': today_apts, 'upcoming_apts': upcoming_apts,
        'pending_apts': pending_apts, 'pending_requests': pending_requests,
        'pending_request_apts': pending_request_apts,
        'notifications': notifications, 'unread_count': unread_count,
        'unread_messages': unread_messages,
        'today': today, 'high_risk_patients': high_risk_patients,
        'reports_generated': reports_generated,
        'emergency_count': emergency_count,
        'active_emergency_apts': active_emergency_apts,
        'missed_alert_apt': missed_alert_apt,
        'unseen_missed_count': unseen_missed_count,
        'pending_count': pending_normal_count,
        'patient_activity_monitoring': patient_activity_monitoring,
        'risk_alerts': get_alerts_for_user(user, limit=10),
        'earnings_summary': earnings_summary,
    }
    from apps.appointments.history_utils import DEFAULT_EMERGENCY_DRAFT

    context['default_emergency_draft'] = DEFAULT_EMERGENCY_DRAFT
    return render(request, 'dashboard/doctor/index.html', context)


@login_required
def admin_dashboard(request):
    if request.user.role != 'admin' and not request.user.is_superuser:
        return redirect(request.user.get_dashboard_url())

    from apps.messaging.models import Message
    today = date.today()

    context = {
        'total_patients': CustomUser.objects.filter(role='patient').count(),
        'total_doctors': CustomUser.objects.filter(role='doctor').count(),
        'total_caregivers': CustomUser.objects.filter(role='caregiver').count(),
        'total_appointments': Appointment.objects.count(),
        'total_medicines': Medicine.objects.count(),
        'total_reports': Report.objects.count(),
        'total_connections': DoctorPatientConnection.objects.filter(status='accepted').count(),
        'pending_connections': DoctorPatientConnection.objects.filter(status='pending').count(),
        'recent_users': CustomUser.objects.order_by('-date_joined')[:10],
        'recent_apts': Appointment.objects.order_by('-created_at').select_related('patient', 'doctor')[:10],
        'pending_apts': Appointment.objects.filter(status='pending').count(),
        'confirmed_apts': Appointment.objects.filter(status='confirmed').count(),
        'cancelled_apts': Appointment.objects.filter(status='cancelled').count(),
        'completed_apts': Appointment.objects.filter(status='completed').count(),
        'high_risk': RiskScore.objects.filter(level='high').select_related('patient')[:5],
        'recent_notifications': Notification.objects.filter(
            created_at__date=today,
        ).order_by('-created_at')[:10],
        'low_stock_count': sum(1 for m in Medicine.objects.filter(is_active=True) if m.is_low_stock),
        'active_medicines': Medicine.objects.filter(is_active=True).count(),
        'today': today,
        'today_apts': Appointment.objects.filter(appointment_date=today).count(),
        'today_new_users': CustomUser.objects.filter(date_joined__date=today).count(),
        'all_patients': CustomUser.objects.filter(role='patient').select_related('patient_profile')[:20],
        'all_doctors': CustomUser.objects.filter(role='doctor').select_related('doctor_profile')[:20],
        'all_caregivers': CustomUser.objects.filter(role='caregiver')[:20],
    }
    return render(request, 'dashboard/admin/index.html', context)


@login_required
def patient_detail(request, patient_id):
    if request.user.role != 'doctor':
        return redirect('/dashboard/')

    patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
    conn = DoctorPatientConnection.objects.filter(
        doctor=request.user, patient=patient, status='accepted'
    ).first()
    if not conn:
        from django.contrib import messages
        messages.error(request, 'You are not connected with this patient.')
        return redirect('/dashboard/doctor/')

    today = date.today()
    medicines = Medicine.objects.filter(patient=patient, is_active=True)
    logs = MedicineLog.objects.filter(patient=patient).order_by('-scheduled_time')[:20]
    week_logs = MedicineLog.objects.filter(patient=patient, scheduled_time__date__gte=today - timedelta(days=6))
    taken = week_logs.filter(status='taken').count()
    total_logs = week_logs.count()
    adherence = int(taken / total_logs * 100) if total_logs > 0 else 0

    from apps.medicines.activity_utils import get_patient_activities_for_doctor_view

    risk = calculate_risk_score(patient)
    apts = Appointment.objects.filter(patient=patient, doctor=request.user).order_by('-appointment_date')[:5]
    patient_activities = get_patient_activities_for_doctor_view(patient, doctor_user=request.user)
    missed_count = patient_activities['counts']['missed']
    missed_activity_alert = None
    if missed_count:
        if missed_count == 1:
            missed_activity_alert = (
                f'{missed_count} missed activity — review patient adherence and adjust care plan if needed.'
            )
        else:
            missed_activity_alert = (
                f'{missed_count} missed activities — review patient adherence and adjust care plan if needed.'
            )
    reports = Report.objects.filter(patient=patient, doctor=request.user)[:3]
    health_checks = DailyHealthCheck.objects.filter(patient=patient).order_by('-checked_at')[:7]

    try:
        profile = patient.patient_profile
    except Exception:
        profile = None

    chart_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        dl = MedicineLog.objects.filter(patient=patient, scheduled_time__date=d)
        dt_c = dl.filter(status='taken').count()
        dn_c = dl.count()
        chart_data.append({'day': d.strftime('%a'), 'pct': int(dt_c/dn_c*100) if dn_c > 0 else 0})

    from apps.medicines.inventory_service import get_medicine_inventory_summary

    medicine_inventory = [
        get_medicine_inventory_summary(m) for m in medicines
    ]

    context = {
        'patient': patient, 'profile': profile, 'conn': conn,
        'medicines': medicines, 'logs': logs, 'risk': risk,
        'medicine_inventory': medicine_inventory,
        'appointments': apts,
        'patient_activities': patient_activities,
        'missed_activity_alert': missed_activity_alert,
        'reports': reports, 'adherence': adherence,
        'chart_data': chart_data, 'today': today,
        'health_checks': health_checks,
    }
    from apps.caregiver.models import get_hospital_caregiver_for_patient
    context['caregiver'] = get_hospital_caregiver_for_patient(patient, doctor=request.user)
    return render(request, 'dashboard/doctor/patient_detail.html', context)
