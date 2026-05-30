"""Medicine inventory, refill tracking, and stock alert logic."""
import re
from datetime import date, timedelta

from django.utils import timezone

from apps.medicines.models import Medicine, MedicineInventoryEvent, MedicinePurchase, MedicineRefill

LOW_STOCK_ALERT_COOLDOWN_HOURS = 24
LOW_STOCK_SNOOZE_MINUTES = 360  # Remind me later — 6 hours
LOW_STOCK_REFILL_OPEN_HOURS = 24

SEVERITY_MESSAGES = {
    'warning': 'Please refill medicine to avoid interruption in treatment.',
    'high': 'Stock is running very low. Please refill soon.',
    'critical': 'Critical — only 1 dose remaining. Refill immediately.',
    'emergency': 'You may miss upcoming medicine doses. Please refill immediately.',
}

SEVERITY_LABELS = {
    'warning': 'Low',
    'high': 'High',
    'critical': 'Critical',
    'emergency': 'Emergency',
}


def parse_low_stock_alert_at(raw, default=3):
    """Parse doctor-defined refill alert threshold (1–30 doses)."""
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = default
    return max(1, min(30, val))


def get_low_stock_alert_threshold(medicine):
    """Per-medicine alert level — use property, never hardcode."""
    return getattr(medicine, 'low_stock_alert_at', None) or medicine.critical_stock_threshold or 3


def parse_units_per_dose(dosage_str):
    """Extract numeric units from dosage e.g. '2 tablets' -> 2."""
    if not dosage_str:
        return 1
    match = re.search(r'(\d+)\s*(tablet|tab|capsule|cap|pill|dose|unit|ml|mg)?', dosage_str.lower())
    if match:
        return max(1, int(match.group(1)))
    return 1


def _coerce_date(value):
    """Ensure DateField values are date objects (POST strings before DB coercion)."""
    if value is None or value == '':
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        from datetime import datetime
        return datetime.strptime(value.strip()[:10], '%Y-%m-%d').date()
    return value


def course_days(medicine):
    start = _coerce_date(medicine.start_date)
    end = _coerce_date(medicine.end_date)
    if end and start:
        return max(1, (end - start).days + 1)
    return 30


def calculate_prescribed_quantity(medicine):
    """Dosage per day × course duration."""
    daily_doses = medicine.max_daily_doses
    units = getattr(medicine, 'units_per_dose', None) or parse_units_per_dose(medicine.dosage)
    return max(1, daily_doses * units * course_days(medicine))


def medicine_has_stock(medicine):
    return (medicine.stock_quantity or 0) > 0


def is_not_purchased_yet(medicine):
    """True when doctor prescribed but patient has never confirmed a purchase."""
    return (medicine.total_refilled_quantity or 0) <= 0 and (medicine.stock_quantity or 0) <= 0


def get_medicine_compliance_stats(medicine, days=30):
    """Taken vs missed doses for compliance reporting."""
    since = date.today() - timedelta(days=days)
    logs = medicine.logs.filter(scheduled_time__date__gte=since)
    taken = logs.filter(status='taken').count()
    missed = logs.filter(status='missed').count()
    denom = taken + missed
    pct = int(min(100, taken / denom * 100)) if denom > 0 else 0
    return {'taken_doses': taken, 'missed_doses': missed, 'compliance_pct': pct}


def apply_prescription_inventory(medicine, save=True):
    """Set prescribed quantity only — patient stock starts at zero until purchase."""
    qty = calculate_prescribed_quantity(medicine)
    medicine.prescribed_quantity = qty
    medicine.stock_quantity = 0
    medicine.units_per_dose = parse_units_per_dose(medicine.dosage)
    start = _coerce_date(medicine.start_date)
    end = _coerce_date(medicine.end_date)
    medicine.expected_end_date = end or (start + timedelta(days=29) if start else None)
    medicine.prescription_status = 'active'
    medicine.refill_required = True
    medicine.total_refilled_quantity = 0
    medicine.stock_depleted_at = None
    if not medicine.low_stock_threshold:
        medicine.low_stock_threshold = max(7, get_low_stock_alert_threshold(medicine) + 2)
    if save:
        medicine.save()
    record_inventory_event(
        medicine, 'prescribed', quantity_delta=0,
        notes=f'Prescription: {qty} units for {course_days(medicine)} days — awaiting patient purchase',
    )
    return qty


def remaining_stock(medicine):
    return medicine.stock_quantity


def deduct_on_taken(medicine, log=None, marked_by=None):
    """Reduce stock when patient marks medicine taken."""
    if medicine.stock_quantity > 0:
        medicine.stock_quantity -= 1
    if medicine.stock_quantity <= 0 and not medicine.stock_depleted_at:
        medicine.stock_depleted_at = timezone.localdate()
        medicine.refill_required = True
    elif medicine.stock_quantity <= get_low_stock_alert_threshold(medicine):
        medicine.refill_required = True
    medicine.save(update_fields=[
        'stock_quantity', 'stock_depleted_at', 'refill_required', 'updated_at',
    ])
    record_inventory_event(
        medicine, 'taken', quantity_delta=-1, medicine_log=log,
        notes='Marked taken', created_by=marked_by,
    )
    return medicine.stock_quantity


def record_inventory_event(
    medicine, event_type, quantity_delta=0, medicine_log=None,
    refill=None, notes='', created_by=None,
):
    return MedicineInventoryEvent.objects.create(
        medicine=medicine,
        patient=medicine.patient,
        event_type=event_type,
        quantity_delta=quantity_delta,
        stock_after=medicine.stock_quantity,
        medicine_log=medicine_log,
        refill=refill,
        notes=notes,
        created_by=created_by,
    )


def process_refill(medicine, quantity_purchased, purchase_date=None, pharmacy_name='', recorded_by=None, notes=''):
    """Add purchased quantity (additive) and record permanent purchase history."""
    purchase_date = purchase_date or timezone.localdate()
    qty = max(1, int(quantity_purchased))
    before = medicine.stock_quantity or 0
    medicine.stock_quantity = before + qty
    medicine.total_refilled_quantity = (medicine.total_refilled_quantity or 0) + qty
    if medicine.stock_quantity > 0:
        medicine.refill_required = False
        medicine.stock_depleted_at = None
    medicine.save()

    prescribed = medicine.prescribed_quantity or calculate_prescribed_quantity(medicine)
    cumulative = medicine.total_refilled_quantity
    is_partial = cumulative < prescribed

    refill = MedicineRefill.objects.create(
        medicine=medicine,
        patient=medicine.patient,
        quantity_purchased=qty,
        purchase_date=purchase_date,
        pharmacy_name=pharmacy_name or '',
        recorded_by=recorded_by,
        is_partial=is_partial,
        stock_before=before,
        stock_after=medicine.stock_quantity,
    )
    MedicinePurchase.objects.create(
        medicine=medicine,
        patient=medicine.patient,
        purchase_quantity=qty,
        purchase_date=purchase_date,
        previous_stock=before,
        updated_stock=medicine.stock_quantity,
        pharmacy_name=pharmacy_name or '',
        notes=notes or '',
        recorded_by=recorded_by,
        refill=refill,
    )
    record_inventory_event(
        medicine, 'refilled', quantity_delta=qty, refill=refill,
        notes=f'Purchase +{qty}' + (' (partial)' if is_partial else ''),
        created_by=recorded_by,
    )
    clear_low_stock_snooze_if_resolved(medicine)
    resolve_stock_alerts_after_refill(medicine)
    return refill


def get_partial_refill_status(medicine):
    prescribed = medicine.prescribed_quantity or 0
    refilled = medicine.total_refilled_quantity or 0
    if prescribed <= 0:
        return {
            'is_partial': False, 'purchased': refilled, 'prescribed': 0, 'pct': 100,
            'shortfall': 0, 'not_purchased': refilled <= 0,
        }
    pct = int(min(100, refilled / prescribed * 100)) if prescribed else 100
    return {
        'is_partial': refilled < prescribed and refilled > 0,
        'not_purchased': refilled <= 0,
        'purchased': refilled,
        'prescribed': prescribed,
        'pct': pct,
        'shortfall': max(0, prescribed - refilled),
    }


def get_refill_gap_days(medicine):
    """Days without stock since depletion."""
    if medicine.stock_quantity > 0:
        return 0
    if not medicine.stock_depleted_at:
        return 0
    return max(0, (timezone.localdate() - medicine.stock_depleted_at).days)


def get_stock_alert_severity(medicine):
    """Absolute stock tiers: 3=warning, 2=high, 1=critical, 0=emergency."""
    sq = medicine.stock_quantity
    if sq <= 0:
        return 'emergency'
    if sq == 1:
        return 'critical'
    if sq == 2:
        return 'high'
    return 'warning'


def is_priority_stock_alert(medicine):
    return get_stock_alert_severity(medicine) in ('critical', 'emergency')


def get_refill_status_display(medicine):
    """Doctor/patient refill tracking — pending vs refilled."""
    last = medicine.refills.order_by('-purchase_date', '-created_at').first()
    threshold = get_low_stock_alert_threshold(medicine)
    if medicine.stock_quantity <= threshold or medicine.refill_required:
        return {
            'code': 'pending',
            'label': 'Pending',
            'last_refill_date': None,
            'last_refill_date_display': None,
            'quantity_added': None,
        }
    if last:
        return {
            'code': 'refilled',
            'label': 'Refilled',
            'last_refill_date': last.purchase_date.isoformat(),
            'last_refill_date_display': last.purchase_date.strftime('%b %d, %Y'),
            'quantity_added': last.quantity_purchased,
        }
    return {
        'code': 'ok',
        'label': '—',
        'last_refill_date': None,
        'last_refill_date_display': None,
        'quantity_added': None,
    }


def resolve_stock_alerts_after_refill(medicine):
    """Clear low-stock flags and snooze after successful refill."""
    threshold = get_low_stock_alert_threshold(medicine)
    updates = []
    if medicine.stock_quantity > threshold:
        medicine.refill_required = False
        medicine.low_stock_snooze_until = None
        medicine.last_low_stock_alert_at = None
        updates.extend(['refill_required', 'low_stock_snooze_until', 'last_low_stock_alert_at'])
    elif medicine.stock_quantity > 0:
        medicine.refill_required = False
        updates.append('refill_required')
    if medicine.stock_quantity > 0 and medicine.stock_depleted_at:
        medicine.stock_depleted_at = None
        updates.append('stock_depleted_at')
    if updates:
        updates.append('updated_at')
        medicine.save(update_fields=list(dict.fromkeys(updates)))
    clear_low_stock_snooze_if_resolved(medicine)


def should_show_low_stock_alert(medicine):
    """True when at/below doctor-defined alert threshold and cooldown elapsed."""
    if is_not_purchased_yet(medicine):
        return False
    threshold = get_low_stock_alert_threshold(medicine)
    if medicine.stock_quantity > threshold:
        return False
    if medicine.prescription_status != 'active':
        return False
    priority = is_priority_stock_alert(medicine)
    if not priority:
        snooze = getattr(medicine, 'low_stock_snooze_until', None)
        if snooze and snooze > timezone.now():
            return False
        last = medicine.last_low_stock_alert_at
        if last:
            hours = (timezone.now() - last).total_seconds() / 3600
            if hours < LOW_STOCK_ALERT_COOLDOWN_HOURS:
                return False
    return True


def snooze_low_stock_alert(medicine, minutes=None):
    """Remind me later — default 6 hours."""
    minutes = minutes if minutes is not None else LOW_STOCK_SNOOZE_MINUTES
    medicine.last_low_stock_alert_at = timezone.now()
    medicine.low_stock_snooze_until = timezone.now() + timedelta(minutes=minutes)
    medicine.save(update_fields=['last_low_stock_alert_at', 'low_stock_snooze_until', 'updated_at'])
    record_inventory_event(medicine, 'low_stock_alert', notes=f'Low stock snoozed for {minutes} minutes')


def suppress_low_stock_for_refill(medicine):
    """User opened refill workflow — suppress popup until snooze expires."""
    medicine.last_low_stock_alert_at = timezone.now()
    medicine.low_stock_snooze_until = timezone.now() + timedelta(hours=LOW_STOCK_REFILL_OPEN_HOURS)
    medicine.save(update_fields=['last_low_stock_alert_at', 'low_stock_snooze_until', 'updated_at'])
    record_inventory_event(medicine, 'low_stock_alert', notes='Low stock popup suppressed — refill opened')


def clear_low_stock_snooze_if_resolved(medicine):
    """Clear snooze after successful refill when stock is no longer at alert level."""
    threshold = get_low_stock_alert_threshold(medicine)
    if medicine.stock_quantity > threshold:
        if medicine.low_stock_snooze_until:
            medicine.low_stock_snooze_until = None
            medicine.save(update_fields=['low_stock_snooze_until', 'updated_at'])


def mark_low_stock_alert_sent(medicine):
    medicine.last_low_stock_alert_at = timezone.now()
    medicine.save(update_fields=['last_low_stock_alert_at', 'updated_at'])
    record_inventory_event(medicine, 'low_stock_alert', notes='Low stock notification shown')


def get_medicine_inventory_summary(medicine):
    partial = get_partial_refill_status(medicine)
    gap = get_refill_gap_days(medicine)
    compliance = get_medicine_compliance_stats(medicine)
    missed = medicine.logs.filter(status='missed').count()
    severity = get_stock_alert_severity(medicine)
    refill_status = get_refill_status_display(medicine)
    threshold = get_low_stock_alert_threshold(medicine)
    at_alert_level = medicine.stock_quantity <= threshold and not is_not_purchased_yet(medicine)
    not_purchased = is_not_purchased_yet(medicine)
    if not_purchased:
        severity = 'not_purchased'
    return {
        'medicine_id': medicine.id,
        'name': medicine.name,
        'dosage': medicine.dosage,
        'prescribed_quantity': medicine.prescribed_quantity or 0,
        'purchased_quantity': medicine.total_refilled_quantity or 0,
        'remaining_stock': medicine.stock_quantity,
        'remaining_required': partial['shortfall'],
        'total_refilled': medicine.total_refilled_quantity or 0,
        'not_purchased_yet': not_purchased,
        'expected_end_date': medicine.expected_end_date.isoformat() if medicine.expected_end_date else None,
        'refill_required': medicine.refill_required,
        'prescription_status': medicine.prescription_status,
        'partial_refill': partial['is_partial'],
        'partial_detail': partial,
        'refill_gap_days': gap,
        'missed_doses': missed,
        'taken_doses': compliance['taken_doses'],
        'compliance_pct': compliance['compliance_pct'],
        'low_stock': (medicine.is_critical_stock or at_alert_level) and not not_purchased,
        'is_critical_medicine': medicine.is_critical_medicine,
        'severity': severity,
        'severity_label': 'Not Purchased' if not_purchased else SEVERITY_LABELS.get(severity, 'Low'),
        'severity_message': (
            'Patient has not purchased this medicine yet.'
            if not_purchased else SEVERITY_MESSAGES.get(severity, SEVERITY_MESSAGES['warning'])
        ),
        'is_priority': is_priority_stock_alert(medicine) and not not_purchased,
        'refill_status': refill_status,
        'alert_threshold': threshold,
    }


def get_patient_inventory_alerts(patient):
    """Low-stock medicines needing dashboard popup."""
    alerts = []
    for med in Medicine.objects.filter(patient=patient, is_active=True, prescription_status='active'):
        if should_show_low_stock_alert(med):
            alerts.append(get_medicine_inventory_summary(med))
    alerts.sort(key=lambda a: (
        {'emergency': 0, 'critical': 1, 'high': 2, 'warning': 3}.get(a['severity'], 4),
        a['remaining_stock'],
    ))
    return alerts


def get_patient_stock_alert_cards(patient):
    """Dashboard alert cards — visible until snoozed or refilled."""
    cards = []
    for med in Medicine.objects.filter(patient=patient, is_active=True, prescription_status='active'):
        if is_not_purchased_yet(med):
            continue
        threshold = get_low_stock_alert_threshold(med)
        if med.stock_quantity > threshold and not med.refill_required:
            continue
        priority = is_priority_stock_alert(med)
        if not priority:
            snooze = getattr(med, 'low_stock_snooze_until', None)
            if snooze and snooze > timezone.now():
                continue
        cards.append(get_medicine_inventory_summary(med))
    cards.sort(key=lambda a: (
        {'emergency': 0, 'critical': 1, 'high': 2, 'warning': 3}.get(a['severity'], 4),
        a['remaining_stock'],
    ))
    return cards


def daily_refill_gap_monitor(patient):
    """Run daily-style check for zero-stock gaps; returns risk bump info."""
    bumps = []
    for med in Medicine.objects.filter(patient=patient, is_active=True):
        gap = get_refill_gap_days(med)
        if gap >= 1:
            bumps.append({
                'medicine': med.name,
                'gap_days': gap,
                'points': min(35, 10 + gap * 5),
            })
            if gap >= 3 and not med.refill_required:
                med.refill_required = True
                med.save(update_fields=['refill_required', 'updated_at'])
    return bumps
