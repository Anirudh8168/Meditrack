from datetime import date, timedelta
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.appointments.models import Appointment
from apps.connections.models import DoctorPatientConnection
from apps.medicines.models import Medicine, MedicineLog, RiskScore, Activity, MissedAlertLog
from apps.reports.models import Report
from apps.caregiver.models import CaregiverPatientAssignment
from apps.family.models import FamilyMember


def paginate(request, queryset, per_page=20):
    paginator = Paginator(queryset, per_page)
    page_num = request.GET.get('page', 1)
    return paginator.get_page(page_num)


def log_admin_action(request, action, description, target_model='', target_id=''):
    from .models import AdminActionLog
    AdminActionLog.objects.create(
        admin_user=request.user if request.user.is_authenticated else None,
        action=action,
        target_model=target_model,
        target_id=str(target_id) if target_id else '',
        description=description,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


def _week_count(model_qs, date_field='date_joined'):
    today = date.today()
    week_start = today - timedelta(days=6)
    prev_start = today - timedelta(days=13)
    prev_end = today - timedelta(days=7)
    filter_kw = {f'{date_field}__date__gte': week_start}
    prev_kw_start = {f'{date_field}__date__gte': prev_start}
    prev_kw_end = {f'{date_field}__date__lte': prev_end}
    current = model_qs.filter(**filter_kw).count()
    previous = model_qs.filter(**prev_kw_start, **prev_kw_end).count()
    return current, previous


def _trend_text(current, previous, label='this week'):
    diff = current - previous
    if diff > 0:
        return f'+{diff} {label}', 'up'
    if diff < 0:
        return f'{diff} {label}', 'down'
    return f'No change {label}', 'neutral'


def get_recent_activity(limit=12):
    """Build a unified activity feed from system events."""
    from .models import AdminActionLog
    activities = []

    for log in AdminActionLog.objects.select_related('admin_user').order_by('-created_at')[:6]:
        activities.append({
            'time': log.created_at,
            'user': log.admin_user.get_full_name() if log.admin_user else 'System',
            'event': log.description,
            'icon': 'fa-shield-halved',
            'color': 'bg-indigo-100 text-indigo-600',
        })

    for user in CustomUser.objects.exclude(role='admin').order_by('-date_joined')[:4]:
        role_label = user.get_role_display() if hasattr(user, 'get_role_display') else user.role.title()
        activities.append({
            'time': user.date_joined,
            'user': user.get_full_name(),
            'event': f'{role_label} registered on SmartTrack',
            'icon': 'fa-user-plus',
            'color': 'bg-emerald-100 text-emerald-600',
        })

    for apt in Appointment.objects.filter(
        Q(is_emergency=True) | Q(status='cancelled'),
    ).select_related('patient', 'doctor').order_by('-created_at')[:4]:
        if apt.is_emergency:
            event = 'Emergency consultation requested'
            icon, color = 'fa-truck-medical', 'bg-red-100 text-red-600'
        else:
            event = 'Appointment cancelled'
            icon, color = 'fa-calendar-xmark', 'bg-amber-100 text-amber-600'
        activities.append({
            'time': apt.created_at,
            'user': apt.patient.get_full_name(),
            'event': event,
            'icon': icon,
            'color': color,
        })

    for assign in CaregiverPatientAssignment.objects.filter(
        status='active',
    ).select_related('caregiver', 'patient', 'assigned_by').order_by('-created_at')[:3]:
        assigner = assign.assigned_by.get_full_name() if assign.assigned_by else 'System'
        activities.append({
            'time': assign.created_at,
            'user': assigner,
            'event': f'Caregiver assigned to {assign.patient.get_full_name()}',
            'icon': 'fa-hand-holding-heart',
            'color': 'bg-violet-100 text-violet-600',
        })

    activities.sort(key=lambda x: x['time'], reverse=True)
    return activities[:limit]


def get_dashboard_analytics():
    today = date.today()
    week_ago = today - timedelta(days=6)
    month_ago = today - timedelta(days=29)

    missed_today = MedicineLog.objects.filter(
        scheduled_time__date=today, status='missed',
    ).count()

    adherence_qs = MedicineLog.objects.filter(scheduled_time__date__gte=week_ago)
    taken = adherence_qs.filter(status='taken').count()
    total_logs = adherence_qs.count()
    adherence_pct = int(taken / total_logs * 100) if total_logs else 0

    emergency_today = Appointment.objects.filter(
        is_emergency=True, appointment_date=today,
    ).count()

    pt_week, pt_prev = _week_count(CustomUser.objects.filter(role='patient'))
    dr_week, dr_prev = _week_count(CustomUser.objects.filter(role='doctor'))
    cg_week, cg_prev = _week_count(CustomUser.objects.filter(role='caregiver'))
    fm_week, fm_prev = _week_count(CustomUser.objects.filter(role='family'))
    apt_week, apt_prev = _week_count(Appointment.objects, 'created_at')
    em_week, em_prev = _week_count(Appointment.objects.filter(is_emergency=True), 'created_at')

    pt_trend, pt_trend_class = _trend_text(pt_week, pt_prev)
    dr_trend, dr_trend_class = _trend_text(dr_week, dr_prev)
    cg_trend, cg_trend_class = _trend_text(cg_week, cg_prev)
    fm_trend, fm_trend_class = _trend_text(fm_week, fm_prev)
    apt_trend, apt_trend_class = _trend_text(apt_week, apt_prev)
    em_trend, em_trend_class = _trend_text(em_week, em_prev)

    active_users = CustomUser.objects.filter(is_active=True).exclude(role='admin').count()

    weekly_appointments = list(
        Appointment.objects.filter(appointment_date__gte=week_ago)
        .values('appointment_date')
        .annotate(count=Count('id'))
        .order_by('appointment_date')
    )

    user_growth = {
        'patients': list(
            CustomUser.objects.filter(role='patient', date_joined__date__gte=month_ago)
            .annotate(day=TruncDate('date_joined'))
            .values('day').annotate(count=Count('id')).order_by('day')
        ),
        'doctors': list(
            CustomUser.objects.filter(role='doctor', date_joined__date__gte=month_ago)
            .annotate(day=TruncDate('date_joined'))
            .values('day').annotate(count=Count('id')).order_by('day')
        ),
        'caregivers': list(
            CustomUser.objects.filter(role='caregiver', date_joined__date__gte=month_ago)
            .annotate(day=TruncDate('date_joined'))
            .values('day').annotate(count=Count('id')).order_by('day')
        ),
    }

    emergency_analytics = list(
        Appointment.objects.filter(is_emergency=True, created_at__date__gte=month_ago)
        .annotate(day=TruncDate('created_at'))
        .values('day').annotate(count=Count('id')).order_by('day')
    )

    adherence_daily = list(
        MedicineLog.objects.filter(scheduled_time__date__gte=week_ago)
        .annotate(day=TruncDate('scheduled_time'))
        .values('day')
        .annotate(
            taken=Count('id', filter=Q(status='taken')),
            total=Count('id'),
        )
        .order_by('day')
    )

    return {
        'today': today,
        'total_patients': CustomUser.objects.filter(role='patient').count(),
        'total_doctors': CustomUser.objects.filter(role='doctor').count(),
        'total_caregivers': CustomUser.objects.filter(role='caregiver').count(),
        'total_family': CustomUser.objects.filter(role='family').count(),
        'emergency_today': emergency_today,
        'today_appointments': Appointment.objects.filter(appointment_date=today).count(),
        'active_users': active_users,
        'pending_apts': Appointment.objects.filter(status='pending').count(),
        'pending_emergency': Appointment.objects.filter(
            is_emergency=True, status__in=('pending', 'confirmed'),
        ).count(),
        'active_video': Appointment.objects.filter(
            appointment_type__in=('video', 'emergency_video'),
            status__in=('pending', 'confirmed'),
        ).count(),
        'total_reports': Report.objects.count(),
        'adherence_pct': adherence_pct,
        'adherence_taken': taken,
        'adherence_total': total_logs,
        'pt_trend': pt_trend, 'pt_trend_class': pt_trend_class,
        'dr_trend': dr_trend, 'dr_trend_class': dr_trend_class,
        'cg_trend': cg_trend, 'cg_trend_class': cg_trend_class,
        'fm_trend': fm_trend, 'fm_trend_class': fm_trend_class,
        'apt_trend': apt_trend, 'apt_trend_class': apt_trend_class,
        'em_trend': em_trend, 'em_trend_class': em_trend_class,
        'active_appointments': Appointment.objects.filter(
            status__in=('pending', 'confirmed'),
            appointment_date__gte=today,
        ).count(),
        'emergency_cases': Appointment.objects.filter(is_emergency=True).count(),
        'high_risk_patients': RiskScore.objects.filter(level__in=('high', 'critical')).count(),
        'missed_medicines': missed_today,
        'patient_growth': list(
            CustomUser.objects.filter(role='patient', date_joined__date__gte=month_ago)
            .annotate(day=TruncDate('date_joined'))
            .values('day').annotate(count=Count('id')).order_by('day')
        ),
        'appointment_trends': list(
            Appointment.objects.filter(appointment_date__gte=month_ago)
            .values('appointment_date')
            .annotate(count=Count('id'))
            .order_by('appointment_date')
        ),
        'weekly_appointments': weekly_appointments,
        'user_growth': user_growth,
        'emergency_analytics': emergency_analytics,
        'adherence_daily': adherence_daily,
        'risk_breakdown': list(
            RiskScore.objects.values('level').annotate(count=Count('id')).order_by('level')
        ),
        'recent_emergencies': Appointment.objects.filter(is_emergency=True).select_related(
            'patient', 'doctor',
        ).order_by('-created_at')[:8],
        'high_risk_list': RiskScore.objects.filter(
            level__in=('high', 'critical'),
        ).select_related('patient').order_by('-score')[:8],
        'recent_users': CustomUser.objects.order_by('-date_joined')[:8],
        'recent_activity': get_recent_activity(),
    }


def get_patient_relationships(patient):
    """Return relationship cards for a patient profile."""
    doctor_conn = DoctorPatientConnection.objects.filter(
        patient=patient, status='accepted',
    ).select_related('doctor').first()
    caregiver_assign = CaregiverPatientAssignment.objects.filter(
        patient=patient, status='active',
    ).select_related('caregiver').first()
    family = FamilyMember.objects.filter(patient=patient).first()

    cards = [
        {
            'role': 'Patient',
            'name': patient.get_full_name(),
            'subtitle': patient.unique_id,
        },
    ]
    if doctor_conn:
        cards.append({
            'role': 'Doctor',
            'name': f'Dr. {doctor_conn.doctor.get_full_name()}',
            'subtitle': doctor_conn.doctor.unique_id,
            'url': f'/system-admin/doctors/{doctor_conn.doctor.id}/',
        })
    else:
        cards.append({'role': 'Doctor', 'name': None})

    if caregiver_assign:
        cards.append({
            'role': 'Caregiver',
            'name': caregiver_assign.caregiver.get_full_name(),
            'subtitle': caregiver_assign.caregiver.unique_id,
            'url': f'/system-admin/caregivers/{caregiver_assign.caregiver.id}/',
        })
    else:
        cards.append({'role': 'Caregiver', 'name': None})

    if family:
        cards.append({
            'role': 'Family Member',
            'name': family.name,
            'subtitle': family.relation,
        })
    else:
        cards.append({'role': 'Family Member', 'name': None})

    return cards


def get_database_health():
    issues = []
    patients_no_profile = CustomUser.objects.filter(role='patient').filter(
        patient_profile__isnull=True,
    ).count()
    if patients_no_profile:
        issues.append({
            'type': 'warning',
            'label': 'Patients without profile',
            'count': patients_no_profile,
        })
    doctors_no_profile = CustomUser.objects.filter(role='doctor').filter(
        doctor_profile__isnull=True,
    ).count()
    if doctors_no_profile:
        issues.append({
            'type': 'warning',
            'label': 'Doctors without profile',
            'count': doctors_no_profile,
        })
    inactive_with_active_meds = Medicine.objects.filter(
        is_active=True, patient__is_active=False,
    ).count()
    if inactive_with_active_meds:
        issues.append({
            'type': 'error',
            'label': 'Active medicines for suspended patients',
            'count': inactive_with_active_meds,
        })
    orphan_logs = MedicineLog.objects.filter(patient__isnull=True).count()
    if orphan_logs:
        issues.append({'type': 'error', 'label': 'Orphan medicine logs', 'count': orphan_logs})
    return {
        'issues': issues,
        'total_users': CustomUser.objects.count(),
        'total_appointments': Appointment.objects.count(),
        'total_medicines': Medicine.objects.count(),
        'total_reports': Report.objects.count(),
        'caregiver_links': CaregiverPatientAssignment.objects.filter(status='active').count(),
        'family_links': FamilyMember.objects.count(),
    }


def enrich_patient_list(page):
    """Attach assigned doctor/caregiver to patient page objects."""
    patient_ids = [p.id for p in page]
    doctors = {
        c.patient_id: c.doctor
        for c in DoctorPatientConnection.objects.filter(
            patient_id__in=patient_ids, status='accepted',
        ).select_related('doctor')
    }
    caregivers = {
        a.patient_id: a.caregiver
        for a in CaregiverPatientAssignment.objects.filter(
            patient_id__in=patient_ids, status='active',
        ).select_related('caregiver')
    }
    for p in page:
        p.assigned_doctor = doctors.get(p.id)
        p.assigned_caregiver = caregivers.get(p.id)
    return page


def enrich_doctor_list(page):
    """Attach patient count to doctor page objects."""
    doctor_ids = [d.id for d in page]
    counts = dict(
        DoctorPatientConnection.objects.filter(
            doctor_id__in=doctor_ids, status='accepted',
        ).values('doctor_id').annotate(c=Count('id')).values_list('doctor_id', 'c')
    )
    for d in page:
        d.patients_count = counts.get(d.id, 0)
    return page


def enrich_caregiver_list(page):
    """Attach assigned patient/doctor to caregiver page objects."""
    cg_ids = [c.id for c in page]
    assignments = CaregiverPatientAssignment.objects.filter(
        caregiver_id__in=cg_ids, status='active',
    ).select_related('patient')
    assign_map = {}
    for a in assignments:
        if a.caregiver_id not in assign_map:
            assign_map[a.caregiver_id] = a
    patient_ids = [a.patient_id for a in assign_map.values()]
    doctors = {
        c.patient_id: c.doctor
        for c in DoctorPatientConnection.objects.filter(
            patient_id__in=patient_ids, status='accepted',
        ).select_related('doctor')
    }
    for c in page:
        assign = assign_map.get(c.id)
        c.assigned_patient = assign.patient if assign else None
        c.assigned_doctor = doctors.get(assign.patient_id) if assign else None
        c.has_active_patient = assign is not None
    return page
