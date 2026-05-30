from django.db.models import Q

from apps.caregiver.models import CaregiverPatientAssignment

from .models import Notification


def get_notifications_for_user(user):
    """Notifications visible to the logged-in user (role-aware)."""
    if not user or not user.is_authenticated:
        return Notification.objects.none()
    if user.role == 'caregiver':
        patient_ids = CaregiverPatientAssignment.objects.filter(
            caregiver=user, status='active'
        ).values_list('patient_id', flat=True)
        return Notification.objects.filter(
            Q(user=user) | Q(user_id__in=patient_ids)
        ).distinct()
    return Notification.objects.filter(user=user)


def get_notifications_for_request(request):
    """Notifications for the active patient context (caregiver acting mode uses patient)."""
    from apps.caregiver.access import get_active_patient_context

    ctx = get_active_patient_context(request)
    if ctx['caregiver_mode'] and ctx['patient']:
        return Notification.objects.filter(user=ctx['patient'])
    return get_notifications_for_user(request.user)
