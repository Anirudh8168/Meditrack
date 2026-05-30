"""Central reminder tracking — medicines and activities share one workflow."""
from datetime import timedelta

from django.utils import timezone

from apps.medicines.models import ReminderTracking
from apps.medicines.reminder_engine import REMINDER_INTERVAL_SECONDS, REMINDER_WINDOW_SECONDS

MISSED_REASON = 'No response to reminder'


def ensure_tracking(patient, reference_type, reference_id, scheduled_datetime):
    """Get or create tracking row for a medicine dose or activity log."""
    scheduled = scheduled_datetime
    if timezone.is_naive(scheduled):
        scheduled = timezone.make_aware(scheduled, timezone.get_current_timezone())

    tracking, _ = ReminderTracking.objects.get_or_create(
        reference_type=reference_type,
        reference_id=reference_id,
        defaults={
            'patient': patient,
            'scheduled_datetime': scheduled,
            'next_popup_at': scheduled,
            'status': 'pending',
        },
    )
    return tracking


def window_expired(tracking, now=None):
    now = now or timezone.localtime()
    end = tracking.scheduled_datetime + timedelta(seconds=REMINDER_WINDOW_SECONDS)
    return now > end


def is_tracking_popup_due(tracking, now=None):
    """Popup when scheduled time reached and next_popup_at has passed."""
    now = now or timezone.localtime()
    if tracking.status not in ('pending', 'snoozed'):
        return False
    if now < tracking.scheduled_datetime:
        return False
    if window_expired(tracking, now):
        return False
    next_at = tracking.next_popup_at
    if timezone.is_naive(next_at):
        next_at = timezone.make_aware(next_at, timezone.get_current_timezone())
    return now >= next_at


def record_popup_displayed(tracking, ignored=False):
    """Popup was shown — schedule next retry in 10 minutes."""
    now = timezone.localtime()
    tracking.last_popup_at = now
    tracking.next_popup_at = now + timedelta(seconds=REMINDER_INTERVAL_SECONDS)
    tracking.current_reminder_count += 1
    if ignored:
        tracking.ignored_count += 1
    if tracking.status == 'snoozed':
        tracking.status = 'pending'
    tracking.save(update_fields=[
        'last_popup_at', 'next_popup_at', 'current_reminder_count',
        'ignored_count', 'status', 'updated_at',
    ])
    return tracking


def snooze_tracking(tracking):
    """User clicked Remind Me Later — retry in 10 minutes."""
    now = timezone.localtime()
    tracking.status = 'snoozed'
    tracking.last_popup_at = now
    tracking.next_popup_at = now + timedelta(seconds=REMINDER_INTERVAL_SECONDS)
    tracking.current_reminder_count += 1
    tracking.save(update_fields=[
        'status', 'last_popup_at', 'next_popup_at',
        'current_reminder_count', 'updated_at',
    ])
    return tracking


def complete_tracking(reference_type, reference_id):
    ReminderTracking.objects.filter(
        reference_type=reference_type,
        reference_id=reference_id,
        status__in=('pending', 'snoozed'),
    ).update(status='completed', updated_at=timezone.localtime())


def mark_tracking_missed(tracking):
    tracking.status = 'missed'
    tracking.ignored_count += 1
    tracking.save(update_fields=['status', 'ignored_count', 'updated_at'])


def sync_log_from_tracking(log, tracking):
    """Keep legacy log fields aligned with tracking row."""
    log.last_popup_at = tracking.last_popup_at
    log.reminder_count = tracking.current_reminder_count
    log.snoozed_until = tracking.next_popup_at if tracking.status == 'snoozed' else None
    log.save(update_fields=['last_popup_at', 'reminder_count', 'snoozed_until'])


def tracking_payload(tracking, now=None):
    now = now or timezone.localtime()
    local_next = timezone.localtime(tracking.next_popup_at)
    local_snoozed = local_next if tracking.status == 'snoozed' else None
    return {
        'tracking_id': tracking.id,
        'tracking_status': tracking.status,
        'next_popup_at': local_next.isoformat(),
        'snoozed_until': local_snoozed.isoformat() if local_snoozed else None,
        'reminder_count': tracking.current_reminder_count,
        'ignored_count': tracking.ignored_count,
        'popup_due': is_tracking_popup_due(tracking, now),
    }
