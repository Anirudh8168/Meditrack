"""Medicine dose scheduling helpers — date/slot eligibility."""
from datetime import date

from django.utils import timezone

from apps.medicines.reminder_engine import parse_slot_datetime


def get_prescription_anchor(medicine):
    """Earliest datetime from which dose slots apply for this prescription."""
    if medicine.created_at:
        return timezone.localtime(medicine.created_at)
    return timezone.localtime()


def is_medicine_active_on_date(medicine, day=None):
    """Whether this medicine has doses scheduled on the given calendar day."""
    day = day or date.today()
    if not medicine.is_active:
        return False
    if medicine.prescription_status == 'stopped':
        return False
    if medicine.start_date and day < medicine.start_date:
        return False
    if medicine.end_date and day > medicine.end_date:
        return False
    freq = medicine.frequency
    if freq == 'weekly' and medicine.start_date:
        return (day - medicine.start_date).days % 7 == 0
    if freq == 'as_needed':
        return True
    return True


def is_slot_obligatory(medicine, slot_dt):
    """
    True when a dose slot counts for scheduling, reminders, and missed logic.
    Slots before the prescription was created are skipped.
    """
    if timezone.is_naive(slot_dt):
        slot_dt = timezone.make_aware(slot_dt, timezone.get_current_timezone())
    slot_day = timezone.localtime(slot_dt).date()
    if not is_medicine_active_on_date(medicine, slot_day):
        return False
    return slot_dt >= get_prescription_anchor(medicine)


def attach_medicine_dose_ui(medicine, patient, day=None, now=None):
    """Attach dynamic UI fields using the centralized status engine."""
    from apps.medicines.medicine_status_engine import get_medicine_status

    status = get_medicine_status(medicine, patient, day, now)

    medicine.today_taken_count = status['today_taken_count']
    medicine.today_taken = status['today_taken']
    medicine.can_take_more = status['can_take_more']
    medicine.over_dosed = not status['can_take_more'] and status['today_taken_count'] > 0

    medicine.is_time_to_take = status['is_time_to_take']
    medicine.dose_button_state = status['dose_button_state']
    medicine.next_slot_time = status['next_slot_time']
    medicine.next_slot_display = status['next_slot_display']
    medicine.minutes_until_next = status['minutes_until_next']
    medicine.active_slot_time = status['active_slot_time']
    medicine.active_slot_display = status['active_slot_display']
    medicine.next_dose_display = status['next_dose_display']
    medicine.reminder_snoozed = status['reminder_snoozed']
    medicine.status_message = status['status_message']
    medicine.medicine_status = status['primary_status']
    medicine.is_overdue = status['is_overdue']
    medicine.overdue_minutes = status['overdue_minutes']
    medicine.can_mark = status['can_mark']
    medicine.has_stock = status['has_stock']
    medicine.not_purchased_yet = status['not_purchased_yet']
    medicine.purchased_quantity = status['purchased_quantity']
    medicine.prescribed_quantity_display = status['prescribed_quantity']
    medicine.remaining_required = status['remaining_required']
    medicine.stock_quantity_display = status['stock_quantity']
    return medicine


def get_medicine_slot_states(medicine, patient, day=None, now=None):
    """Backward-compatible slot state list from centralized engine."""
    from apps.medicines.medicine_status_engine import get_medicine_dose_statuses

    state_map = {
        'UPCOMING': 'upcoming',
        'DUE_NOW': 'due',
        'REMIND_LATER_ACTIVE': 'due',
        'TAKEN': 'taken',
        'MISSED': 'missed',
    }
    doses = get_medicine_dose_statuses(medicine, patient, day, now)
    return [
        {
            'slot_str': d['slot_str'],
            'slot_dt': d['slot_dt'],
            'seconds_until': d['seconds_until'],
            'log_status': d['log_status'],
            'state': state_map.get(d['status'], d['status'].lower()),
            'can_mark': d['can_mark'],
            'tracking_status': d['tracking_status'],
            'time_display': d['time_display'],
            'dose_status': d['status'],
            'is_overdue': d['is_overdue'],
            'overdue_minutes': d['overdue_minutes'],
        }
        for d in doses
    ]


def find_due_slot_for_marking(medicine, patient, day=None, now=None):
    from apps.medicines.medicine_status_engine import find_due_slot_for_marking as _find
    return _find(medicine, patient, day, now)


def find_next_upcoming_slot(states):
    upcoming = [s for s in states if s.get('dose_status') == 'UPCOMING' or s.get('state') == 'upcoming']
    if not upcoming:
        return None
    return min(upcoming, key=lambda s: s['seconds_until'])
