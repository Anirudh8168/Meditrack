"""Permission checks for activity edit/delete."""
from apps.caregiver.access import get_active_assignment


def user_can_manage_activity(user, activity, caregiver_mode=False, request=None):
    """Return True if user may edit or delete this activity."""
    if not user or not user.is_authenticated:
        return False

    if user.role == 'doctor':
        return activity.prescribed_by_id == user.id

    if user.role == 'patient' and user.id == activity.patient_id:
        if activity.prescribed_by_id and activity.prescribed_by.role == 'doctor':
            return False
        return activity.logged_by_id == user.id

    if user.role == 'caregiver' and caregiver_mode and request:
        assignment = get_active_assignment(request, activity.patient)
        if assignment and assignment.patient_id == activity.patient_id:
            return assignment.can_log_activities
    return False
