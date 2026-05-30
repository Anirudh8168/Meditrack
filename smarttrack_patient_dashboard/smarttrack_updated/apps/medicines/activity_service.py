"""Activity edit, delete, and audit trail."""
from datetime import date, datetime, timedelta

from django.utils import timezone

from apps.medicines.models import Activity, ActivityAuditLog, ActivityLog
from apps.medicines.activity_utils import resolve_activity_severity
from apps.medicines.reminder_engine import parse_slot_datetime
from apps.notifications.utils import remove_notifications


TRACKED_FIELDS = [
    'title', 'activity_type', 'description', 'duration_minutes',
    'schedule_type', 'start_date', 'end_date', 'time_slots', 'repeat_days',
    'severity', 'requires_proof', 'reminders_enabled',
]


def activity_snapshot(activity):
    snap = {}
    for f in TRACKED_FIELDS:
        val = getattr(activity, f)
        if f in ('start_date', 'end_date') and val:
            val = val.isoformat()
        snap[f] = val
    return snap


def diff_snapshots(before, after):
    changes = {}
    for key in TRACKED_FIELDS:
        if before.get(key) != after.get(key):
            changes[key] = {'old': before.get(key), 'new': after.get(key)}
    return changes


def log_audit(activity, user, action, reason='', changes=None, scope='', effective_date=None):
    ActivityAuditLog.objects.create(
        activity=activity,
        user=user,
        action=action,
        scope=scope or '',
        reason=reason or '',
        changes=changes or {},
        effective_date=effective_date,
    )


def parse_activity_form(post, is_doctor=False):
    no_end = post.get('no_end_date') == '1'
    act_type = post.get('activity_type', 'other')
    doctor_priority = post.get('doctor_priority', '').strip() if is_doctor else None
    return {
        'activity_type': act_type,
        'title': post.get('title', '').strip(),
        'description': post.get('description', '').strip(),
        'duration_minutes': int(post.get('duration_minutes') or 30),
        'schedule_type': post.get('schedule_type', 'one_time'),
        'start_date': post.get('start_date') or str(date.today()),
        'end_date': None if no_end else (post.get('end_date') or None),
        'time_slots': post.getlist('time_slots'),
        'repeat_days': post.getlist('repeat_days'),
        'requires_proof': post.get('requires_proof') == '1',
        'reminders_enabled': post.get('reminders_enabled', '1') == '1',
        'severity': resolve_activity_severity(act_type, doctor_priority or None),
    }


def _coerce_date(val):
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str) and val.strip():
        return datetime.strptime(val.strip()[:10], '%Y-%m-%d').date()
    return None


def apply_form_to_activity(activity, data):
    activity.activity_type = data['activity_type']
    activity.title = data['title']
    activity.description = data['description']
    activity.duration_minutes = data['duration_minutes']
    activity.schedule_type = data['schedule_type']
    activity.start_date = _coerce_date(data['start_date']) or date.today()
    activity.end_date = _coerce_date(data['end_date'])
    activity.time_slots = data['time_slots']
    activity.repeat_days = data['repeat_days']
    activity.severity = data['severity']
    activity.requires_proof = data['requires_proof']
    activity.reminders_enabled = data['reminders_enabled']
    activity.save()


def _cancel_future_logs(activity, from_date, reason=''):
    ActivityLog.objects.filter(
        activity=activity,
        scheduled_time__date__gte=from_date,
        status__in=('scheduled', 'in_progress'),
    ).update(status='skipped', missed_reason=reason or 'Schedule updated or removed')


def edit_activity(activity, user, data, scope, reason, log_id=None, effective_date=None):
    effective_date = _coerce_date(effective_date) or date.today()
    if log_id:
        log_id = int(log_id)
    before = activity_snapshot(activity)

    if scope == 'occurrence' and log_id:
        log = ActivityLog.objects.filter(id=log_id, activity=activity).first()
        if not log:
            return False, 'Occurrence not found', None
        changes = {}
        if data['time_slots']:
            try:
                new_time = data['time_slots'][0]
                new_dt = parse_slot_datetime(log.scheduled_time.date(), new_time)
                changes['time'] = {
                    'old': log.scheduled_time.strftime('%I:%M %p'),
                    'new': new_dt.strftime('%I:%M %p'),
                }
                log.scheduled_time = new_dt
            except ValueError:
                pass
        if data.get('duration_minutes'):
            changes['duration_minutes'] = {
                'old': activity.duration_minutes,
                'new': data['duration_minutes'],
            }
            activity.duration_minutes = data['duration_minutes']
            activity.save(update_fields=['duration_minutes'])
        log.save()
        log_audit(activity, user, 'updated', reason, changes, 'occurrence', log.scheduled_time.date())
        return True, 'Occurrence updated', activity.id

    if scope == 'future' and activity.schedule_type != 'one_time':
        if effective_date <= (activity.start_date or date.today()):
            scope = 'entire'
        else:
            end_before = activity.end_date
            activity.end_date = effective_date - timedelta(days=1)
            activity.save(update_fields=['end_date'])
            _cancel_future_logs(activity, effective_date, reason)

            new_activity = Activity.objects.create(
                patient=activity.patient,
                prescribed_by=activity.prescribed_by,
                logged_by=user,
                activity_type=data['activity_type'],
                title=data['title'],
                description=data['description'],
                duration_minutes=data['duration_minutes'],
                schedule_type=data['schedule_type'],
                start_date=effective_date,
                end_date=end_before,
                time_slots=data['time_slots'],
                repeat_days=data['repeat_days'],
                severity=data['severity'],
                requires_proof=data['requires_proof'],
                reminders_enabled=data['reminders_enabled'],
                is_active=True,
            )
            after = activity_snapshot(new_activity)
            log_audit(new_activity, user, 'updated', reason, diff_snapshots(before, after), 'future', effective_date)
            return True, 'Future schedule updated from ' + effective_date.strftime('%b %d, %Y'), new_activity.id

    apply_form_to_activity(activity, data)
    after = activity_snapshot(activity)
    changes = diff_snapshots(before, after)
    log_audit(activity, user, 'updated', reason, changes, scope or 'entire', effective_date)
    remove_notifications(user=activity.patient, category_contains=f'act_reminder_{activity.id}')
    return True, 'Activity updated successfully', activity.id


def delete_activity(activity, user, scope, reason, log_id=None, effective_date=None):
    effective_date = _coerce_date(effective_date) or date.today()
    if log_id:
        log_id = int(log_id)
    summary = {
        'title': activity.title,
        'schedule': activity.get_schedule_type_display(),
        'times': ', '.join(activity.time_slots or []),
    }

    if scope == 'occurrence' and log_id:
        log = ActivityLog.objects.filter(id=log_id, activity=activity).first()
        if not log:
            return False, 'Occurrence not found'
        log.status = 'skipped'
        log.missed_reason = reason
        log.save(update_fields=['status', 'missed_reason'])
        log_audit(activity, user, 'deleted', reason, {'occurrence': log.scheduled_time.isoformat()}, 'occurrence', log.scheduled_time.date())
        return True, 'This occurrence was removed'

    if scope == 'future' and activity.schedule_type != 'one_time':
        activity.end_date = effective_date - timedelta(days=1)
        activity.save(update_fields=['end_date'])
        _cancel_future_logs(activity, effective_date, reason)
        log_audit(activity, user, 'deleted', reason, summary, 'future', effective_date)
        return True, 'Future occurrences removed'

    activity.is_active = False
    activity.end_date = date.today()
    activity.save(update_fields=['is_active', 'end_date'])
    _cancel_future_logs(activity, date.today(), reason)
    remove_notifications(user=activity.patient, category_contains=f'act_reminder_{activity.id}')
    log_audit(activity, user, 'deleted', reason, summary, 'entire', date.today())
    return True, 'Activity deleted permanently'
