from apps.caregiver.access import get_acting_patient, get_active_assignment_for_caregiver


def caregiver_mode_context(request):
    if not request.user.is_authenticated or request.user.role != 'caregiver':
        return {}
    acting_patient = get_acting_patient(request)
    active_assignment = get_active_assignment_for_caregiver(request.user)
    return {
        'caregiver_acting_for': acting_patient,
        'caregiver_active_assignment': active_assignment,
        'caregiver_mode': acting_patient is not None,
    }
