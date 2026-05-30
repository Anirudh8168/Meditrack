"""
Universal medicine dose status engine — single source of truth for ALL UI.

States: UPCOMING | DUE_NOW | REMIND_LATER_ACTIVE | TAKEN | MISSED | NOT_APPLICABLE
"""
from datetime import date

from django.utils import timezone

from apps.medicines.models import MedicineLog, ReminderTracking
from apps.medicines.reminder_engine import (
    REMINDER_WINDOW_SECONDS,
    parse_slot_datetime,
    seconds_until_slot,
)
from apps.medicines.reminder_tracking_service import is_tracking_popup_due
from apps.medicines.medicine_schedule_utils import (
    get_prescription_anchor,
    is_medicine_active_on_date,
    is_slot_obligatory,
)

# Canonical status constants
UPCOMING = 'UPCOMING'
DUE_NOW = 'DUE_NOW'
REMIND_LATER_ACTIVE = 'REMIND_LATER_ACTIVE'
TAKEN = 'TAKEN'
MISSED = 'MISSED'
NOT_APPLICABLE = 'NOT_APPLICABLE'
NO_STOCK = 'NO_STOCK'


def _format_slot_display(slot_dt):
    return timezone.localtime(slot_dt).strftime('%I:%M %p').lstrip('0')


def _load_log_and_tracking(medicine, slot_dt):
    log = MedicineLog.objects.filter(
        medicine=medicine, scheduled_time=slot_dt,
    ).first()
    tracking = None
    if log:
        tracking = ReminderTracking.objects.filter(
            reference_type='medicine', reference_id=log.id,
        ).first()
    return log, tracking


def get_dose_status(medicine, slot_str, patient, day=None, now=None):
    """
    Single source of truth for one dose slot on a calendar day.

    Returns dict with: status, can_mark, popup_due, is_overdue, overdue_minutes,
    seconds_until, time_display, slot_dt, slot_str, log_id, log_status, tracking_status.
    """
    day = day or date.today()
    now = now or timezone.localtime()
    slot_dt = parse_slot_datetime(day, slot_str)
    diff = seconds_until_slot(slot_dt, now)

    base = {
        'slot_str': slot_str,
        'slot_dt': slot_dt,
        'seconds_until': diff,
        'time_display': _format_slot_display(slot_dt),
        'log_id': None,
        'log_status': 'scheduled',
        'tracking_status': None,
        'tracking_id': None,
        'can_mark': False,
        'popup_due': False,
        'is_overdue': False,
        'overdue_minutes': 0,
        'is_upcoming': False,
        'taken': False,
        'missed': False,
    }

    if not is_slot_obligatory(medicine, slot_dt):
        base['status'] = NOT_APPLICABLE
        return base

    from apps.medicines.inventory_service import medicine_has_stock, is_not_purchased_yet
    has_stock = medicine_has_stock(medicine)

    log, tracking = _load_log_and_tracking(medicine, slot_dt)
    log_status = log.status if log else 'scheduled'
    tracking_status = tracking.status if tracking else None

    base['log_id'] = log.id if log else None
    base['log_status'] = log_status
    base['tracking_status'] = tracking_status
    base['tracking_id'] = tracking.id if tracking else None

    if log_status in ('taken', 'skipped'):
        base.update(status=TAKEN, taken=True, can_mark=False)
        return base

    if log_status == 'missed':
        base.update(status=MISSED, missed=True, can_mark=False)
        return base

    if diff > 0:
        base.update(
            status=UPCOMING, is_upcoming=True, can_mark=False, popup_due=False,
            no_stock=not has_stock,
        )
        return base

    if not has_stock:
        base.update(
            status=NO_STOCK,
            can_mark=False,
            popup_due=False,
            no_stock=True,
            not_purchased_yet=is_not_purchased_yet(medicine),
        )
        return base

    if diff < -REMINDER_WINDOW_SECONDS:
        base.update(status=MISSED, missed=True, can_mark=False, popup_due=False)
        return base

    # Valid window: scheduled_time <= now <= scheduled_time + 1 hour
    is_overdue = diff < 0
    overdue_minutes = max(0, abs(diff) // 60) if is_overdue else 0

    if tracking_status == 'snoozed':
        status = REMIND_LATER_ACTIVE
    else:
        status = DUE_NOW

    popup_due = False
    if log_status == 'scheduled':
        if tracking:
            popup_due = is_tracking_popup_due(tracking, now)
        else:
            # Scheduled time reached — tracking row created on reminder sync
            popup_due = diff <= 0

    base.update(
        status=status,
        can_mark=True,
        popup_due=popup_due,
        is_overdue=is_overdue,
        overdue_minutes=overdue_minutes,
    )
    return base


def get_medicine_dose_statuses(medicine, patient, day=None, now=None):
    """All applicable dose statuses for today, sorted by slot time."""
    day = day or date.today()
    now = now or timezone.localtime()
    if not is_medicine_active_on_date(medicine, day):
        return []
    statuses = []
    for slot_str in medicine.time_slots or []:
        try:
            dose = get_dose_status(medicine, slot_str, patient, day, now)
            if dose['status'] != NOT_APPLICABLE:
                statuses.append(dose)
        except (ValueError, TypeError):
            continue
    statuses.sort(key=lambda d: d['slot_dt'])
    return statuses


def _status_message(primary, doses, today_taken_count, max_daily_doses):
    """Human-readable message aligned with primary status."""
    if not primary:
        if today_taken_count >= max_daily_doses:
            return 'All doses taken today ✓'
        return 'Not scheduled yet'

    st = primary['status']
    td = primary['time_display']

    if st == UPCOMING:
        return f'Next dose at {td}'
    if st == NO_STOCK:
        if primary.get('not_purchased_yet'):
            return 'Medicine not purchased yet — add purchase to enable dosing'
        return 'Out of stock — refill to mark doses'
    if st == DUE_NOW:
        if primary['is_overdue']:
            return f'Due now · Overdue by {primary["overdue_minutes"]} min'
        return 'Due now'
    if st == REMIND_LATER_ACTIVE:
        if primary['is_overdue']:
            return f'Reminder active · Overdue by {primary["overdue_minutes"]} min'
        return 'Due now · Reminder active'
    if st == TAKEN:
        upcoming = next((d for d in doses if d['status'] == UPCOMING), None)
        if upcoming:
            return f'✓ Dose taken · Next dose at {upcoming["time_display"]}'
        return '✓ Dose taken'
    if st == MISSED:
        upcoming = next((d for d in doses if d['status'] == UPCOMING), None)
        if upcoming:
            return f'Missed {td} · Next dose at {upcoming["time_display"]}'
        return f'Missed dose at {td}'
    return ''


def _map_button_state(primary, doses, today_taken_count, max_daily_doses):
    """Map canonical status to template dose_button_state."""
    if not doses:
        return 'not_scheduled'

    if today_taken_count >= max_daily_doses and all(
        d['status'] in (TAKEN, MISSED) for d in doses
    ):
        return 'all_taken'

    if not primary:
        return 'locked'

    st = primary['status']
    if st == DUE_NOW:
        return 'due'
    if st == NO_STOCK:
        return 'no_stock'
    if st == REMIND_LATER_ACTIVE:
        return 'snoozed'
    if st == UPCOMING:
        return 'locked'
    if st == TAKEN:
        upcoming = any(d['status'] == UPCOMING for d in doses)
        return 'taken_waiting' if upcoming else 'all_taken'
    if st == MISSED:
        if any(d['status'] in (UPCOMING, DUE_NOW, REMIND_LATER_ACTIVE) for d in doses):
            return 'locked'
        return 'missed'
    return 'locked'


def get_medicine_status(medicine, patient, day=None, now=None):
    """
    Aggregate medicine-level status for cards, banners, buttons, and API.

    Priority for primary active dose:
      1. DUE_NOW / REMIND_LATER_ACTIVE (earliest in window)
      2. UPCOMING (nearest future)
      3. TAKEN (most recent, if waiting for next)
      4. MISSED (only when nothing else is actionable today)
    """
    day = day or date.today()
    now = now or timezone.localtime()

    today_taken_count = medicine.logs.filter(
        scheduled_time__date=day, status='taken',
    ).count()
    max_daily_doses = medicine.max_daily_doses

    from apps.medicines.inventory_service import (
        get_partial_refill_status, is_not_purchased_yet, medicine_has_stock,
    )
    purchase = get_partial_refill_status(medicine)

    result = {
        'medicine_id': medicine.id,
        'medicine_name': medicine.name,
        'day': day.isoformat(),
        'today_taken_count': today_taken_count,
        'max_daily_doses': max_daily_doses,
        'today_taken': today_taken_count >= max_daily_doses,
        'can_take_more': today_taken_count < max_daily_doses,
        'is_active_today': is_medicine_active_on_date(medicine, day),
        'has_stock': medicine_has_stock(medicine),
        'not_purchased_yet': is_not_purchased_yet(medicine),
        'stock_quantity': medicine.stock_quantity,
        'prescribed_quantity': medicine.prescribed_quantity or 0,
        'purchased_quantity': purchase['purchased'],
        'remaining_required': purchase['shortfall'],
        'doses': [],
        'primary_dose': None,
        'primary_status': None,
        'is_time_to_take': False,
        'can_mark': False,
        'popup_due': False,
        'is_overdue': False,
        'overdue_minutes': 0,
        'status_message': '',
        'dose_button_state': 'not_scheduled',
        'next_slot_time': None,
        'next_slot_display': None,
        'next_dose_display': None,
        'active_slot_time': None,
        'active_slot_display': None,
        'minutes_until_next': None,
        'reminder_snoozed': False,
    }

    if not result['is_active_today']:
        if medicine.start_date and day < medicine.start_date:
            result['dose_button_state'] = 'not_started'
            result['status_message'] = f'Course starts {medicine.start_date.strftime("%b %d, %Y")}'
        else:
            result['dose_button_state'] = 'not_scheduled'
            result['status_message'] = 'Not scheduled today'
        return result

    doses = get_medicine_dose_statuses(medicine, patient, day, now)
    result['doses'] = doses

    if not doses:
        result['dose_button_state'] = 'not_scheduled'
        result['status_message'] = 'No time slots configured'
        return result

    primary = None
    for d in doses:
        if d['status'] in (DUE_NOW, REMIND_LATER_ACTIVE, NO_STOCK):
            primary = d
            break
    if not primary:
        upcoming = [d for d in doses if d['status'] == UPCOMING]
        if upcoming:
            primary = min(upcoming, key=lambda x: x['seconds_until'])
    if not primary:
        taken = [d for d in doses if d['status'] == TAKEN]
        if taken:
            primary = taken[-1]
    if not primary:
        missed = [d for d in doses if d['status'] == MISSED]
        if missed:
            primary = missed[-1]

    result['primary_dose'] = primary
    result['primary_status'] = primary['status'] if primary else None

    if primary:
        result['is_time_to_take'] = primary['can_mark']
        result['can_mark'] = primary['can_mark']
        result['popup_due'] = primary['popup_due']
        result['is_overdue'] = primary['is_overdue']
        result['overdue_minutes'] = primary['overdue_minutes']
        result['active_slot_time'] = primary['slot_str']
        result['active_slot_display'] = primary['time_display']
        if primary['status'] == REMIND_LATER_ACTIVE:
            result['reminder_snoozed'] = True

    upcoming = next((d for d in doses if d['status'] == UPCOMING), None)
    if upcoming:
        result['next_slot_time'] = upcoming['slot_str']
        result['next_slot_display'] = upcoming['time_display']
        result['next_dose_display'] = upcoming['time_display']
        result['minutes_until_next'] = max(0, int(upcoming['seconds_until'] / 60))
    elif primary and primary['status'] in (DUE_NOW, REMIND_LATER_ACTIVE):
        later = [d for d in doses if d['status'] == UPCOMING and d['slot_dt'] > primary['slot_dt']]
        if later:
            nxt = min(later, key=lambda x: x['seconds_until'])
            result['next_dose_display'] = nxt['time_display']

    result['dose_button_state'] = _map_button_state(
        primary, doses, today_taken_count, max_daily_doses,
    )
    result['status_message'] = _status_message(
        primary, doses, today_taken_count, max_daily_doses,
    )
    return result


def dose_status_to_reminder_payload(medicine, dose_status, patient):
    """Build reminder API payload from canonical dose status."""
    slot_dt = dose_status['slot_dt']
    local_scheduled = timezone.localtime(slot_dt)
    st = dose_status['status']

    payload = {
        'type': 'medicine',
        'log_id': dose_status['log_id'],
        'med_id': medicine.id,
        'name': medicine.name,
        'dosage': medicine.dosage,
        'time': dose_status['slot_str'],
        'time_display': dose_status['time_display'],
        'scheduled_time': local_scheduled.isoformat(),
        'seconds_until': dose_status['seconds_until'],
        'dose_status': st,
        'status': dose_status['log_status'],
        'is_unlocked': dose_status['can_mark'],
        'is_overdue': dose_status['is_overdue'],
        'overdue_minutes': dose_status['overdue_minutes'],
        'is_upcoming': st == UPCOMING,
        'taken': st == TAKEN,
        'missed': st == MISSED,
        'color': medicine.color,
        'doctor': medicine.prescribed_by.get_full_name() if medicine.prescribed_by else 'N/A',
        'stock_quantity': medicine.stock_quantity,
        'not_purchased_yet': st == NO_STOCK and dose_status.get('not_purchased_yet'),
        'popup_due': dose_status['popup_due'] and st not in (NO_STOCK, UPCOMING),
        'can_take': dose_status['can_mark'],
        'status_message': (
            f'Overdue by {dose_status["overdue_minutes"]} min'
            if dose_status['is_overdue'] and dose_status['can_mark']
            else ('Due now' if dose_status['can_mark'] else dose_status['time_display'])
        ),
        'tracking_id': dose_status.get('tracking_id'),
        'tracking_status': dose_status.get('tracking_status') or 'pending',
        'next_popup_at': local_scheduled.isoformat() if st == UPCOMING else None,
        'snoozed_until': None,
        'reminder_count': 0,
        'ignored_count': 0,
    }
    return payload


def find_due_slot_for_marking(medicine, patient, day=None, now=None):
    """Return slot_dt for the current due dose, or None if not in valid window."""
    for dose in get_medicine_dose_statuses(medicine, patient, day, now):
        if dose['can_mark'] and dose['log_status'] == 'scheduled':
            return dose['slot_dt'], dose
    return None, None
