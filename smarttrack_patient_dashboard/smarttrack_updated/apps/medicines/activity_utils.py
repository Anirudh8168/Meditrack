"""Scheduled activity helpers — slots, logs, compliance."""
from datetime import date, timedelta

from django.utils import timezone

from apps.medicines.models import Activity, ActivityLog
from apps.medicines.reminder_engine import (
    is_popup_due,
    parse_slot_datetime,
    seconds_until_slot,
    should_auto_mark_missed,
    REMINDER_WINDOW_SECONDS,
)


def auto_severity_for_type(activity_type):
    """Automatic severity from activity type — not shown to patients/caregivers."""
    high = {'dialysis', 'doctor_recommended'}
    medium = {
        'bp_check', 'sugar_check', 'physiotherapy', 'breathing',
        'vitals', 'symptom',
    }
    if activity_type in high:
        return 'high'
    if activity_type in medium:
        return 'medium'
    return 'low'


def resolve_activity_severity(activity_type, doctor_priority=None):
    priority_map = {
        'low': 'low', 'medium': 'medium', 'high': 'high', 'critical': 'critical',
    }
    if doctor_priority and doctor_priority in priority_map:
        return priority_map[doctor_priority]
    return auto_severity_for_type(activity_type)


def default_severity_for_type(activity_type):
    return auto_severity_for_type(activity_type)


def get_today_slots(activity, day=None):
    day = day or date.today()
    if not activity.is_scheduled_on(day):
        return []
    slots = []
    for slot_str in activity.time_slots or []:
        try:
            slots.append(parse_slot_datetime(day, slot_str))
        except (ValueError, TypeError):
            continue
    return sorted(slots)


def find_next_slot(activity, from_day=None, max_days=14):
    """Next scheduled slot on or after from_day."""
    from_day = from_day or date.today()
    now = timezone.localtime()
    for offset in range(max_days):
        day = from_day + timedelta(days=offset)
        slots = get_today_slots(activity, day)
        for slot_dt in slots:
            if slot_dt >= now:
                return slot_dt, day
    return None, None


def schedule_frequency_label(activity):
    slots = activity.time_slots or []
    if activity.schedule_type == 'one_time':
        return 'One Time'
    if activity.schedule_type == 'daily':
        if len(slots) >= 2:
            return f'{len(slots)}x Daily'
        return 'Daily'
    if activity.schedule_type == 'weekly':
        days = activity.repeat_days or []
        abbr = '/'.join(d.upper()[:3] for d in days[:3])
        if len(days) > 3:
            abbr += '…'
        return f'Weekly · {abbr}' if abbr else 'Weekly'
    if activity.schedule_type == 'custom':
        return 'Custom Schedule'
    return activity.get_schedule_type_display()


def schedule_times_label(activity):
    slots = activity.time_slots or []
    if not slots:
        return '—'
    formatted = []
    for s in slots[:3]:
        try:
            t = parse_slot_datetime(date.today(), s)
            formatted.append(t.strftime('%I:%M %p').lstrip('0'))
        except ValueError:
            formatted.append(s)
    if len(slots) > 3:
        formatted.append(f'+{len(slots) - 3} more')
    return ' · '.join(formatted)


def prescribed_by_label(activity):
    if activity.prescribed_by_id:
        if activity.prescribed_by.role == 'doctor':
            return f'Dr. {activity.prescribed_by.get_full_name()}'
        return activity.prescribed_by.get_full_name()
    if activity.logged_by_id:
        role = activity.logged_by.role
        if role == 'caregiver':
            return f'Caregiver · {activity.logged_by.get_full_name()}'
        if role == 'patient':
            return 'Patient'
        return activity.logged_by.get_full_name()
    return 'Patient'


def created_by_role_badge(activity):
    """Compact creator badge for doctor patient profile cards."""
    if activity.prescribed_by_id and activity.prescribed_by.role == 'doctor':
        return 'Doctor'
    if activity.logged_by_id:
        role = activity.logged_by.role
        if role == 'caregiver':
            return 'Caregiver'
        if role == 'patient':
            return 'Patient'
        return activity.logged_by.get_role_display()
    return 'Patient'


ACTIVITY_STATUS_LABELS = {
    'scheduled': 'Scheduled',
    'upcoming': 'Upcoming',
    'active': 'Active',
    'completed': 'Completed',
    'missed': 'Missed',
    'cancelled': 'Cancelled',
}


def activity_status_label(key):
    return ACTIVITY_STATUS_LABELS.get(key, key)


def activity_display_status(activity, now=None):
    """Return (status_key, related_log) for an activity schedule."""
    now = now or timezone.localtime()
    today = now.date()

    if not activity.is_active:
        last = ActivityLog.objects.filter(activity=activity).order_by('-scheduled_time').first()
        if last and last.status == 'completed':
            return 'completed', last
        if last and last.status == 'missed':
            return 'missed', last
        if last and last.status == 'skipped':
            return 'cancelled', last
        return 'cancelled', last

    in_prog = ActivityLog.objects.filter(activity=activity, status='in_progress').first()
    if in_prog:
        return 'active', in_prog

    today_logs = ActivityLog.objects.filter(
        activity=activity, scheduled_time__date=today,
    ).order_by('scheduled_time')
    for log in today_logs:
        if log.status == 'completed':
            return 'completed', log
        if log.status == 'missed':
            return 'missed', log
        if log.status == 'skipped':
            return 'cancelled', log
        if log.status == 'scheduled':
            diff = seconds_until_slot(log.scheduled_time, now)
            if diff > 0:
                return 'upcoming', log
            return 'scheduled', log

    next_dt, _ = find_next_slot(activity, today)
    if next_dt:
        return 'upcoming', None

    return 'scheduled', None


def activity_compliance_for(activity, days=30):
    since = date.today() - timedelta(days=days)
    logs = ActivityLog.objects.filter(activity=activity, scheduled_time__date__gte=since)
    total = logs.count()
    completed = logs.filter(status='completed').count()
    missed = logs.filter(status='missed').count()
    pct = int((completed / total * 100) if total else 100)
    return {'total': total, 'completed': completed, 'missed': missed, 'compliance_pct': pct}


def slot_status_label(log, now=None):
    """Static status text — countdown lives only on the activity session page."""
    now = now or timezone.localtime()
    if log.status == 'completed':
        return 'Completed'
    if log.status == 'missed':
        return 'Missed'
    if log.status == 'in_progress':
        return 'In Progress'
    if log.status == 'skipped':
        return 'Skipped'
    diff = seconds_until_slot(log.scheduled_time, now)
    if diff > 0:
        return 'Scheduled'
    if diff >= -3600:
        return 'Due now'
    return 'Overdue'


def get_or_create_log(activity, slot_dt, patient):
    log, created = ActivityLog.objects.get_or_create(
        activity=activity,
        scheduled_time=slot_dt,
        defaults={'patient': patient, 'status': 'scheduled'},
    )
    return log, created


def process_overdue_log(log, now=None):
    now = now or timezone.localtime()
    if log.status != 'scheduled':
        return False

    from apps.medicines.reminder_tracking_service import (
        MISSED_REASON,
        ensure_tracking,
        mark_tracking_missed,
        window_expired,
    )

    tracking = ensure_tracking(log.patient, 'activity', log.id, log.scheduled_time)
    if not window_expired(tracking, now):
        return False

    log.status = 'missed'
    log.missed_reason = log.missed_reason or MISSED_REASON
    log.missed_at = now
    log.save(update_fields=['status', 'missed_reason', 'missed_at'])
    mark_tracking_missed(tracking)

    from apps.medicines.views import calculate_risk_score
    calculate_risk_score(log.patient)

    severity = log.activity.severity
    if severity in ('high', 'critical'):
        from apps.connections.models import DoctorPatientConnection
        from apps.notifications.utils import notify_user
        conn = DoctorPatientConnection.objects.filter(
            patient=log.patient, status='accepted',
        ).select_related('doctor').first()
        if conn:
            notify_user(
                user=conn.doctor,
                title='⚠️ Missed Critical Activity',
                message=(
                    f'{log.patient.get_full_name()} missed "{log.activity.title}" '
                    f'({log.activity.get_activity_type_display()}).'
                ),
                notification_type='alert',
                priority='high',
                category=f'act_missed_{log.id}',
            )
    return True


def _slot_item(log, now):
    diff = seconds_until_slot(log.scheduled_time, now)
    local_started = timezone.localtime(log.started_at) if log.started_at else None
    local_completed = timezone.localtime(log.completed_at) if log.completed_at else None
    item = {
        'log': log,
        'log_id': log.id,
        'activity_id': log.activity_id,
        'title': log.activity.title,
        'time_display': timezone.localtime(log.scheduled_time).strftime('%I:%M %p').lstrip('0'),
        'scheduled_time_iso': timezone.localtime(log.scheduled_time).isoformat(),
        'duration_minutes': log.activity.duration_minutes,
        'duration_seconds': (log.activity.duration_minutes or 1) * 60,
        'status': log.status,
        'status_label': slot_status_label(log, now),
        'seconds_until': diff,
        'can_start': log.status == 'scheduled' and diff <= 0,
        'is_upcoming': log.status == 'scheduled' and diff > 0,
        'in_progress': log.status == 'in_progress',
        'started_at_iso': local_started.isoformat() if local_started else '',
        'started_at_display': local_started.strftime('%I:%M %p').lstrip('0') if local_started else '',
        'completed_at_display': local_completed.strftime('%I:%M %p').lstrip('0') if local_completed else '',
        'missed_reason': log.missed_reason or '',
        'has_start_proof': bool(log.start_proof_upload),
        'has_completion_proof': bool(log.proof_upload),
    }
    if log.status == 'completed':
        item['status_label'] = 'Completed Successfully'
    elif log.status == 'missed':
        item['status_label'] = log.missed_reason or 'Missed'
    return item


def categorize_activity_logs(patient, day=None):
    """Today-only buckets — no duplicate future-day cards."""
    day = day or date.today()
    now = timezone.localtime()

    today_due = []
    today_upcoming = []
    missed = []
    completed = []

    activities = Activity.objects.filter(patient=patient, is_active=True)
    seen_log_ids = set()

    for activity in activities:
        for slot_dt in get_today_slots(activity, day):
            log, _ = get_or_create_log(activity, slot_dt, patient)
            if log.id in seen_log_ids:
                continue
            seen_log_ids.add(log.id)
            process_overdue_log(log, now)
            log.refresh_from_db()

            item = _slot_item(log, now)
            diff = item['seconds_until']

            if log.status == 'completed':
                completed.append(item)
            elif log.status == 'missed':
                missed.append(item)
            elif log.status == 'in_progress':
                today_due.append(item)
            elif log.status == 'scheduled' and diff <= 0:
                today_due.append(item)
            elif log.status == 'scheduled':
                today_upcoming.append(item)

    today_due.sort(key=lambda x: x['log'].scheduled_time)
    today_upcoming.sort(key=lambda x: x['log'].scheduled_time)

    return {
        'today': today_due,
        'upcoming': today_upcoming,
        'missed': missed,
        'completed': completed,
        'compliance': activity_compliance_stats(patient),
    }


def build_schedule_summary(activity, patient=None, today=None, can_manage=False):
    """One compact card per activity schedule (not per occurrence)."""
    today = today or date.today()
    now = timezone.localtime()
    patient = patient or activity.patient

    next_dt, next_day = find_next_slot(activity, today)
    compliance = activity_compliance_for(activity)

    last_completed = (
        ActivityLog.objects.filter(activity=activity, status='completed')
        .order_by('-completed_at')
        .first()
    )

    days_active = 0
    if activity.start_date:
        end = activity.end_date or today
        days_active = max(0, (min(end, today) - activity.start_date).days + 1)

    if next_dt and next_day == today:
        next_label = f'Today · {next_dt.strftime("%I:%M %p").lstrip("0")}'
    elif next_dt:
        next_label = f'{next_day.strftime("%b %d")} · {next_dt.strftime("%I:%M %p").lstrip("0")}'
    else:
        next_label = 'No upcoming slot'

    pending_today = ActivityLog.objects.filter(
        activity=activity,
        scheduled_time__date=today,
        status__in=('scheduled', 'in_progress'),
    ).exists()

    return {
        'activity': activity,
        'activity_id': activity.id,
        'title': activity.title,
        'frequency_label': schedule_frequency_label(activity),
        'times_label': schedule_times_label(activity),
        'duration_minutes': activity.duration_minutes,
        'next_label': next_label,
        'status_label': 'Active' if activity.is_active else 'Inactive',
        'pending_today': pending_today,
        'compliance_pct': compliance['compliance_pct'],
        'missed_count': compliance['missed'],
        'days_active': days_active,
        'prescribed_by': prescribed_by_label(activity),
        'last_completed': last_completed.completed_at if last_completed else None,
        'can_manage': can_manage,
        'is_recurring': activity.schedule_type != 'one_time',
    }


def get_active_schedule_summaries(patient, user=None, caregiver_mode=False, request=None):
    from apps.medicines.activity_permissions import user_can_manage_activity
    activities = Activity.objects.filter(patient=patient, is_active=True).order_by('title')
    summaries = []
    for a in activities:
        can_manage = user_can_manage_activity(user, a, caregiver_mode, request) if user else False
        summaries.append(build_schedule_summary(a, patient, can_manage=can_manage))
    return summaries


def get_activity_detail_bundle(activity):
    """Full detail payload for activity detail page."""
    compliance = activity_compliance_for(activity, days=30)
    base_qs = ActivityLog.objects.filter(activity=activity).select_related('marked_by')
    recent_logs = base_qs.order_by('-scheduled_time')[:50]
    missed_logs = base_qs.filter(status='missed').order_by('-scheduled_time')[:20]
    completed_logs = base_qs.filter(status='completed').order_by('-scheduled_time')[:20]

    next_dt, next_day = find_next_slot(activity)

    from apps.medicines.models import ActivityAuditLog
    audit_logs = ActivityAuditLog.objects.filter(activity=activity).select_related('user')[:20]

    return {
        'activity': activity,
        'compliance': compliance,
        'recent_logs': recent_logs,
        'missed_logs': missed_logs,
        'completed_logs': completed_logs,
        'audit_logs': audit_logs,
        'frequency_label': schedule_frequency_label(activity),
        'times_label': schedule_times_label(activity),
        'prescribed_by': prescribed_by_label(activity),
        'next_label': (
            f'{next_day.strftime("%b %d, %Y")} · {next_dt.strftime("%I:%M %p").lstrip("0")}'
            if next_dt else '—'
        ),
    }


def get_patient_activities_for_doctor_view(patient, doctor_user=None):
    """All patient activity schedules + log counts for doctor patient profile."""
    from apps.medicines.activity_permissions import user_can_manage_activity

    now = timezone.localtime()
    activities = Activity.objects.filter(patient=patient).select_related(
        'prescribed_by', 'logged_by',
    ).order_by('-is_active', '-recorded_at')

    cards = []
    for activity in activities:
        can_manage = (
            user_can_manage_activity(doctor_user, activity)
            if doctor_user else False
        )
        summary = build_schedule_summary(activity, patient, can_manage=can_manage)
        status_key, status_log = activity_display_status(activity, now)
        summary['created_by_badge'] = created_by_role_badge(activity)
        summary['created_by_label'] = prescribed_by_label(activity)
        summary['display_status_key'] = status_key
        summary['display_status_label'] = activity_status_label(status_key)
        summary['status_log'] = status_log
        summary['completion_display'] = ''
        if status_log and status_log.status == 'completed' and status_log.completed_at:
            summary['completion_display'] = timezone.localtime(
                status_log.completed_at,
            ).strftime('%I:%M %p').lstrip('0')
        cards.append(summary)

    logs_qs = ActivityLog.objects.filter(patient=patient)
    active_schedules = activities.filter(is_active=True).count()
    upcoming_logs = logs_qs.filter(status='scheduled', scheduled_time__gte=now).count()
    in_progress_logs = logs_qs.filter(status='in_progress').count()

    return {
        'cards': cards,
        'counts': {
            'scheduled': active_schedules,
            'upcoming': upcoming_logs,
            'active': in_progress_logs,
            'completed': logs_qs.filter(status='completed').count(),
            'missed': logs_qs.filter(status='missed').count(),
        },
        'compliance': activity_compliance_stats(patient),
        'missed_this_month': logs_qs.filter(
            status='missed',
            scheduled_time__date__gte=date.today().replace(day=1),
        ).count(),
    }


def get_doctor_activity_monitoring(doctor):
    """Per-patient activity summaries for doctor dashboard."""
    from apps.connections.models import DoctorPatientConnection

    results = []
    conns = DoctorPatientConnection.objects.filter(
        doctor=doctor, status='accepted',
    ).select_related('patient')

    for conn in conns:
        patient = conn.patient
        summaries = get_active_schedule_summaries(patient)
        if not summaries:
            continue
        overall = activity_compliance_stats(patient)
        results.append({
            'patient': patient,
            'activities': summaries,
            'overall_compliance': overall['compliance_pct'],
            'total_missed': overall['missed'],
        })
    return results


def build_activity_reminder(activity, slot_dt, patient, now=None):
    now = now or timezone.localtime()
    log, _ = get_or_create_log(activity, slot_dt, patient)
    from apps.medicines.reminder_tracking_service import (
        complete_tracking,
        ensure_tracking,
        is_tracking_popup_due,
        tracking_payload,
    )

    tracking = ensure_tracking(patient, 'activity', log.id, log.scheduled_time)
    process_overdue_log(log, now)
    log.refresh_from_db()
    tracking.refresh_from_db()

    if log.status == 'completed':
        complete_tracking('activity', log.id)
    elif log.status in ('in_progress', 'skipped'):
        complete_tracking('activity', log.id)

    diff = seconds_until_slot(log.scheduled_time, now)
    done = log.status in ('completed', 'missed', 'skipped', 'in_progress')
    popup_due = (
        not done
        and log.status == 'scheduled'
        and is_tracking_popup_due(tracking, now)
    )

    local_scheduled = timezone.localtime(log.scheduled_time)
    freq = schedule_frequency_label(activity)
    local_snoozed = timezone.localtime(tracking.next_popup_at) if tracking.status == 'snoozed' else None
    local_started = timezone.localtime(log.started_at) if log.started_at else None
    local_completed = timezone.localtime(log.completed_at) if log.completed_at else None
    track = tracking_payload(tracking)

    return {
        'log_id': log.id,
        'activity_id': activity.id,
        'title': activity.title,
        'description': activity.description or '',
        'activity_type': activity.activity_type,
        'activity_type_display': activity.get_activity_type_display(),
        'duration_minutes': activity.duration_minutes,
        'frequency_label': freq,
        'time': local_scheduled.strftime('%H:%M'),
        'time_display': local_scheduled.strftime('%I:%M %p').lstrip('0'),
        'scheduled_time': local_scheduled.isoformat(),
        'seconds_until': diff,
        'status': log.status,
        'status_label': slot_status_label(log, now),
        'is_unlocked': diff <= 0 and log.status == 'scheduled',
        'is_upcoming': diff > 0 and log.status == 'scheduled',
        'can_start': log.status == 'scheduled' and diff <= 0,
        'is_overdue': diff < -REMINDER_WINDOW_SECONDS or log.status == 'missed',
        'popup_due': popup_due,
        'reminder_count': track['reminder_count'],
        'snoozed_until': track['snoozed_until'],
        'tracking_id': track['tracking_id'],
        'tracking_status': track['tracking_status'],
        'next_popup_at': track['next_popup_at'],
        'session_url': (
            f'/medicines/activities/session/{log.id}/'
            if log.status == 'in_progress' else None
        ),
        'taken': log.status == 'completed',
        'in_progress': log.status == 'in_progress',
        'severity': activity.severity,
        'requires_proof': activity.requires_proof,
        'started_at_display': local_started.strftime('%I:%M %p').lstrip('0') if local_started else '',
        'completed_at_display': local_completed.strftime('%I:%M %p').lstrip('0') if local_completed else '',
        'started_at_iso': local_started.isoformat() if local_started else '',
        'duration_seconds': (activity.duration_minutes or 1) * 60,
        'remaining_seconds': log.remaining_seconds if log.status == 'in_progress' else 0,
        'can_complete': log.can_complete if log.status == 'in_progress' else False,
        'missed_reason': log.missed_reason or '',
    }


def get_patient_activity_reminders(patient, day=None):
    day = day or date.today()
    now = timezone.localtime()
    reminders = []
    activities = Activity.objects.filter(patient=patient, is_active=True)

    for activity in activities:
        if not activity.reminders_enabled:
            continue
        for slot_dt in get_today_slots(activity, day):
            reminders.append(build_activity_reminder(activity, slot_dt, patient, now))

    reminders.sort(key=lambda x: x['seconds_until'])
    return reminders


def activity_compliance_stats(patient, days=30):
    since = date.today() - timedelta(days=days)
    logs = ActivityLog.objects.filter(patient=patient, scheduled_time__date__gte=since)
    total = logs.count()
    completed = logs.filter(status='completed').count()
    missed = logs.filter(status='missed').count()
    pct = int((completed / total * 100) if total else 100)
    return {
        'total': total,
        'completed': completed,
        'missed': missed,
        'compliance_pct': pct,
    }
