"""Emergency consultation timeout and missed-request handling."""
from datetime import date

from django.utils import timezone

from apps.notifications.utils import notify_user
from apps.family.utils import send_family_alert
from apps.caregiver.models import CaregiverPatientAssignment

MISSED_EMERGENCY_REASON = (
    'Doctor unavailable / no response within 5 minutes'
)


def _notify_patient_emergency_timeout(apt):
    msg = (
        'Doctor is currently unavailable. Please visit a nearby clinic or hospital immediately.'
    )
    notify_user(
        user=apt.patient,
        title='🚨 Emergency — Doctor Unavailable',
        message=msg,
        notification_type='alert',
        priority='high',
        category=f'apt_timeout_{apt.id}',
        related_id=apt.id,
    )
    send_family_alert(
        patient=apt.patient,
        alert_type='emergency_timeout',
        title='Emergency — Doctor Unavailable',
        message=f'{apt.patient.get_full_name()}: {msg} Nearest clinic recommended in SmartTrack.',
        priority='high',
    )
    for assignment in CaregiverPatientAssignment.objects.filter(patient=apt.patient, status='active'):
        if assignment.caregiver_id != apt.patient_id:
            notify_user(
                user=assignment.caregiver,
                title='🚨 Patient Emergency — Doctor Unavailable',
                message=f'{apt.patient.get_full_name()} emergency call timed out. {msg}',
                notification_type='alert',
                priority='high',
                category=f'apt_timeout_{apt.id}',
                related_id=apt.id,
            )


def notify_doctor_missed_emergency(apt):
    """Alert doctor that patient attempted emergency consultation."""
    patient_name = apt.patient.get_full_name()
    when = apt.timeout_at or timezone.now()
    time_str = timezone.localtime(when).strftime('%I:%M %p on %b %d, %Y')
    notes = (apt.reason or apt.emergency_notes or 'Emergency video consultation').strip()
    notify_user(
        user=apt.doctor,
        title='🚨 Missed Emergency Alert',
        message=(
            f'Patient {patient_name} attempted an emergency consultation, but you were unavailable. '
            f'No response within 5 minutes. Request time: {time_str}. Details: {notes}'
        ),
        notification_type='alert',
        priority='high',
        category=f'apt_doctor_missed_{apt.id}',
        related_id=apt.id,
    )


def expire_emergency_if_needed(apt) -> bool:
    """
    If emergency window elapsed, mark timed out and notify patient + doctor.
    Returns True if appointment was newly expired.
    """
    if not apt.is_emergency or apt.appointment_type != 'emergency_video':
        return False
    if apt.status != 'pending_doctor_confirmation':
        return False
    now = timezone.now()
    if not apt.timeout_at or now < apt.timeout_at:
        return False
    if not apt.mark_as_timeout():
        return False
    _notify_patient_emergency_timeout(apt)
    notify_doctor_missed_emergency(apt)
    from apps.medicines.views import calculate_risk_score
    calculate_risk_score(apt.patient)
    return True


def expire_stale_emergencies_for_doctor(doctor):
    from .models import Appointment

    qs = Appointment.objects.filter(
        doctor=doctor,
        is_emergency=True,
        appointment_type='emergency_video',
        status='pending_doctor_confirmation',
        timeout_at__lte=timezone.now(),
    )
    for apt in qs:
        expire_emergency_if_needed(apt)


def expire_stale_emergencies_for_patient(patient):
    from .models import Appointment

    qs = Appointment.objects.filter(
        patient=patient,
        is_emergency=True,
        appointment_type='emergency_video',
        status='pending_doctor_confirmation',
        timeout_at__lte=timezone.now(),
    )
    for apt in qs:
        expire_emergency_if_needed(apt)


TERMINAL_EMERGENCY_STATUSES = (
    'timeout', 'rejected', 'completed', 'ended', 'confirmed', 'ongoing',
    'cancelled', 'cancelled_by_patient', 'cancelled_by_doctor',
)


def get_doctor_today_emergency_history(doctor, today=None):
    """Emergency records for dashboard — current date only, newest first."""
    from .models import Appointment

    today = today or date.today()
    return (
        Appointment.objects.filter(
            doctor=doctor,
            appointment_type='emergency_video',
            is_emergency=True,
            appointment_date=today,
        )
        .exclude(status='pending_doctor_confirmation')
        .exclude(status__in=('pending', 'pending_confirmation'))
        .select_related('patient')
        .order_by('-timeout_at', '-rejected_at', '-confirmed_at', '-updated_at')
    )


def get_doctor_full_emergency_history(doctor, limit=50):
    from .models import Appointment

    return (
        Appointment.objects.filter(
            doctor=doctor,
            appointment_type='emergency_video',
            is_emergency=True,
        )
        .exclude(status='pending_doctor_confirmation')
        .exclude(status__in=('pending', 'pending_confirmation'))
        .select_related('patient')
        .order_by('-appointment_date', '-timeout_at', '-updated_at')[:limit]
    )


def get_unseen_missed_emergencies_today(doctor, today=None):
    from .models import Appointment

    today = today or date.today()
    return (
        Appointment.objects.filter(
            doctor=doctor,
            appointment_type='emergency_video',
            is_emergency=True,
            appointment_date=today,
            status='timeout',
            doctor_missed_alert_seen=False,
        )
        .select_related('patient')
        .order_by('-timeout_at', '-updated_at')
    )


def dismiss_missed_emergency_alert(apt, doctor_user) -> bool:
    if apt.doctor_id != doctor_user.id or apt.status != 'timeout':
        return False
    if apt.doctor_missed_alert_seen:
        return True
    apt.doctor_missed_alert_seen = True
    events = list(apt.emergency_events or [])
    events.append({'type': 'doctor_dismissed_missed_alert', 'at': timezone.now().isoformat()})
    apt.emergency_events = events[-40:]
    apt.save(update_fields=['doctor_missed_alert_seen', 'emergency_events', 'updated_at'])
    return True


def is_emergency_expired(apt) -> bool:
    if apt.status == 'timeout':
        return True
    if (
        apt.status == 'pending_doctor_confirmation'
        and apt.is_emergency
        and apt.timeout_at
        and timezone.now() >= apt.timeout_at
    ):
        return True
    return False
