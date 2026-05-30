"""Medicine dose reminder state — built from centralized status engine."""
from datetime import date

from django.utils import timezone

from apps.medicines.models import Medicine, MedicineLog, ReminderTracking
from apps.medicines.medicine_schedule_utils import is_medicine_active_on_date, is_slot_obligatory
from apps.medicines.medicine_status_engine import (
    MISSED,
    TAKEN,
    UPCOMING,
    dose_status_to_reminder_payload,
    get_dose_status,
)
from apps.medicines.reminder_engine import parse_slot_datetime, seconds_until_slot
from apps.medicines.reminder_tracking_service import (
    MISSED_REASON,
    complete_tracking,
    ensure_tracking,
    mark_tracking_missed,
    tracking_payload,
    window_expired,
)


def get_or_create_medicine_log(medicine, slot_dt, patient):
    """Create dose log only for obligatory slots that have reached scheduled time."""
    from apps.medicines.inventory_service import medicine_has_stock
    if not medicine_has_stock(medicine):
        return None, False
    if not is_slot_obligatory(medicine, slot_dt):
        return None, False
    log = MedicineLog.objects.filter(
        medicine=medicine,
        scheduled_time=slot_dt,
    ).first()
    if log:
        return log, False
    log = MedicineLog.objects.create(
        medicine=medicine,
        patient=patient,
        scheduled_time=slot_dt,
        status='scheduled',
    )
    return log, True


def process_overdue_medicine_log(log, tracking, now=None):
    """Auto-mark missed after 1 hour with no response."""
    if log.status != 'scheduled':
        return False
    if not is_slot_obligatory(log.medicine, log.scheduled_time):
        return False
    from apps.medicines.inventory_service import medicine_has_stock
    if not medicine_has_stock(log.medicine):
        return False
    now = now or timezone.localtime()
    if not window_expired(tracking, now):
        return False

    log.status = 'missed'
    log.notes = log.notes or MISSED_REASON
    log.save(update_fields=['status', 'notes'])
    mark_tracking_missed(tracking)

    from apps.medicines.views import calculate_risk_score
    calculate_risk_score(log.patient, trigger_medicine=log.medicine)
    return True


def build_medicine_reminder(medicine, slot_time_str, patient, day=None, now=None):
    """Build reminder payload using get_dose_status — same logic as medicine cards."""
    from apps.medicines.inventory_service import medicine_has_stock

    if not medicine_has_stock(medicine):
        return None

    day = day or date.today()
    now = now or timezone.localtime()
    slot_dt = parse_slot_datetime(day, slot_time_str)

    if not is_slot_obligatory(medicine, slot_dt):
        return None

    diff = seconds_until_slot(slot_dt, now)

    if diff <= 0:
        log, _ = get_or_create_medicine_log(medicine, slot_dt, patient)
        if log and log.status == 'scheduled':
            tracking = ensure_tracking(patient, 'medicine', log.id, log.scheduled_time)
            process_overdue_medicine_log(log, tracking, now)
            log.refresh_from_db()

    dose = get_dose_status(medicine, slot_time_str, patient, day, now)

    if dose['status'] == UPCOMING:
        return dose_status_to_reminder_payload(medicine, dose, patient)

    if dose['status'] == TAKEN and dose['log_id']:
        complete_tracking('medicine', dose['log_id'])

    payload = dose_status_to_reminder_payload(medicine, dose, patient)

    if dose['log_id']:
        tr = ReminderTracking.objects.filter(
            reference_type='medicine', reference_id=dose['log_id'],
        ).first()
        if tr:
            payload.update(tracking_payload(tr, now))
            if dose['status'] in (UPCOMING, TAKEN, MISSED):
                payload['popup_due'] = False

    return payload


def get_patient_medicine_reminders(patient, day=None):
    day = day or date.today()
    reminders = []
    medicines = Medicine.objects.filter(patient=patient, is_active=True)
    for med in medicines:
        if not is_medicine_active_on_date(med, day):
            continue
        for slot_time_str in med.time_slots or []:
            try:
                item = build_medicine_reminder(med, slot_time_str, patient, day, now=None)
                if item:
                    reminders.append(item)
            except Exception:
                continue
    reminders.sort(key=lambda x: x['seconds_until'])
    return reminders
