"""Shared reminder logic for medicines and scheduled activities."""
from datetime import datetime, timedelta

from django.utils import timezone

REMINDER_INTERVAL_SECONDS = 600  # 10 minutes
REMINDER_WINDOW_SECONDS = 3600   # 1 hour max retry window
POPUP_TOLERANCE_SECONDS = 5      # ±5s at exact scheduled time only


def _parse_time(slot_time_str):
    slot_time_str = (slot_time_str or '').strip()
    if not slot_time_str:
        raise ValueError('Empty time slot')
    for fmt, length in (('%H:%M:%S', 8), ('%H:%M', 5)):
        try:
            return datetime.strptime(slot_time_str[:length], fmt).time()
        except ValueError:
            continue
    raise ValueError(f'Invalid time slot: {slot_time_str}')


def parse_slot_datetime(day, slot_time_str):
    """Build timezone-aware local datetime for a calendar day + HH:MM slot."""
    slot_time = _parse_time(slot_time_str)
    naive = datetime.combine(day, slot_time)
    tz = timezone.get_current_timezone()
    if timezone.is_aware(naive):
        return naive
    return timezone.make_aware(naive, tz)


def seconds_until_slot(slot_dt, now=None):
    now = now or timezone.localtime()
    if timezone.is_naive(slot_dt):
        slot_dt = timezone.make_aware(slot_dt, timezone.get_current_timezone())
    return int((slot_dt - now).total_seconds())


def is_popup_due(diff_seconds, reminder_count=0, snoozed_until=None, last_popup_at=None):
    """
    Popup once scheduled time is reached (current_time >= scheduled_time) and every
    10 minutes within the 1-hour window. Uses >= not exact equality so polling
    never misses a dose reminder.
    """
    now = timezone.localtime()
    if snoozed_until:
        if timezone.is_naive(snoozed_until):
            snoozed_until = timezone.make_aware(snoozed_until, timezone.get_current_timezone())
        if now < snoozed_until:
            return False

    if diff_seconds > 0:
        return False
    if abs(diff_seconds) > REMINDER_WINDOW_SECONDS:
        return False

    if last_popup_at:
        if timezone.is_naive(last_popup_at):
            last_popup_at = timezone.make_aware(last_popup_at, timezone.get_current_timezone())
        elapsed = (now - last_popup_at).total_seconds()
        if elapsed < REMINDER_INTERVAL_SECONDS - POPUP_TOLERANCE_SECONDS:
            return False

    return True


def record_popup_shown(log, increment_count=True):
    """Persist that a reminder popup was displayed or dismissed."""
    now = timezone.localtime()
    log.last_popup_at = now
    if increment_count:
        log.reminder_count += 1
    log.save(update_fields=['last_popup_at', 'reminder_count'])
    return log


def should_auto_mark_missed(diff_seconds, status, started=False):
    """After 1 hour past scheduled time with no start/complete."""
    if status in ('completed', 'missed', 'skipped', 'in_progress'):
        return False
    return diff_seconds < -REMINDER_WINDOW_SECONDS


def next_snooze_time(minutes=10):
    return timezone.localtime() + timedelta(minutes=minutes)
