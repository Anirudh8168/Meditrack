"""Caregiver patient access helpers — one caregiver, one patient, full access."""
from apps.caregiver.models import (
    CaregiverPatientAssignment,
    get_active_assignment_for_caregiver,
)
from apps.connections.models import DoctorPatientConnection
from apps.accounts.models import CustomUser


SESSION_ACTING_FOR_KEY = 'caregiver_acting_for'


def caregiver_has_active_patient(caregiver):
    return get_active_assignment_for_caregiver(caregiver) is not None


def get_acting_patient(request):
    """Return patient when caregiver has explicitly entered patient mode (session)."""
    if not request.user.is_authenticated or request.user.role != 'caregiver':
        return None
    patient_id = request.session.get(SESSION_ACTING_FOR_KEY)
    if not patient_id:
        return None
    assignment = CaregiverPatientAssignment.objects.filter(
        caregiver=request.user, patient_id=patient_id, status='active',
    ).select_related('patient').first()
    return assignment.patient if assignment else None


def get_caregiver_patient(request):
    """Patient for data operations — session first, then active assignment."""
    patient = get_acting_patient(request)
    if patient:
        return patient
    if not request.user.is_authenticated or request.user.role != 'caregiver':
        return None
    assignment = get_active_assignment_for_caregiver(request.user)
    return assignment.patient if assignment else None


def get_active_assignment(request, patient=None):
    """Active CaregiverPatientAssignment for the logged-in caregiver."""
    if not request.user.is_authenticated or request.user.role != 'caregiver':
        return None
    patient = patient or get_caregiver_patient(request)
    if not patient:
        return None
    return CaregiverPatientAssignment.objects.filter(
        caregiver=request.user, patient=patient, status='active',
    ).first()


def get_active_patient_context(request):
    """
    Resolve who data operations should target.

    Returns dict:
      patient — CustomUser (patient) or None
      actor — logged-in user
      caregiver_mode — True when caregiver is acting for a patient in session
      assignment — CaregiverPatientAssignment or None
    """
    actor = request.user
    if not actor.is_authenticated:
        return {
            'patient': None,
            'actor': None,
            'caregiver_mode': False,
            'assignment': None,
        }

    if actor.role == 'patient':
        return {
            'patient': actor,
            'actor': actor,
            'caregiver_mode': False,
            'assignment': None,
        }

    if actor.role == 'caregiver':
        patient = get_caregiver_patient(request)
        if patient:
            assignment = get_active_assignment(request, patient)
            return {
                'patient': patient,
                'actor': actor,
                'caregiver_mode': get_acting_patient(request) is not None,
                'assignment': assignment,
            }

    return {
        'patient': None,
        'actor': actor,
        'caregiver_mode': False,
        'assignment': None,
    }


def get_patient_connected_doctors(patient):
    """Accepted doctor connections for a patient."""
    if not patient:
        return []
    return list(
        CustomUser.objects.filter(
            id__in=DoctorPatientConnection.objects.filter(
                patient=patient, status='accepted',
            ).values_list('doctor_id', flat=True),
            role='doctor',
        ).select_related('doctor_profile').order_by('first_name', 'last_name')
    )


def resolve_patient_for_request(request):
    """
    Resolve the patient whose data should be shown/acted on.
    Returns (patient_user, is_caregiver_mode) or (None, False).
    """
    ctx = get_active_patient_context(request)
    if ctx['patient']:
        return ctx['patient'], ctx['caregiver_mode']
    return None, False


def enter_caregiver_mode(request, patient):
    """Set session for caregiver acting on behalf of patient."""
    assignment = CaregiverPatientAssignment.objects.filter(
        caregiver=request.user, patient=patient, status='active',
    ).first()
    if not assignment:
        return False
    request.session[SESSION_ACTING_FOR_KEY] = patient.id
    return True


def exit_caregiver_mode(request):
    request.session.pop(SESSION_ACTING_FOR_KEY, None)


def log_caregiver_action(assignment, caregiver, action_type, description):
    from apps.caregiver.models import CaregiverActivityTimeline
    CaregiverActivityTimeline.objects.create(
        assignment=assignment,
        caregiver=caregiver,
        action_type=action_type,
        description=description,
    )


def patient_age(patient):
    try:
        profile = patient.patient_profile
        if profile and profile.date_of_birth:
            from datetime import date
            today = date.today()
            dob = profile.date_of_birth
            return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except Exception:
        pass
    return None


def patient_assigned_doctor(patient):
    from apps.connections.models import DoctorPatientConnection
    conn = DoctorPatientConnection.objects.filter(
        patient=patient, status='accepted',
    ).select_related('doctor').first()
    return conn.doctor if conn else None
