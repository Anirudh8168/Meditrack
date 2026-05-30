"""Messaging authorization helpers."""
from apps.accounts.models import CustomUser
from apps.connections.models import DoctorPatientConnection


def user_can_message(sender: CustomUser, receiver: CustomUser) -> bool:
    if sender.id == receiver.id:
        return False
    if sender.role == 'doctor' and receiver.role == 'patient':
        return DoctorPatientConnection.objects.filter(
            doctor=sender, patient=receiver, status='accepted'
        ).exists()
    if sender.role == 'patient' and receiver.role == 'doctor':
        return DoctorPatientConnection.objects.filter(
            patient=sender, doctor=receiver, status='accepted'
        ).exists()
    if sender.role == 'patient' and receiver.role == 'caregiver':
        from apps.caregiver.models import CaregiverPatientAssignment
        return CaregiverPatientAssignment.objects.filter(
            patient=sender, caregiver=receiver, status='active'
        ).exists()
    if sender.role == 'caregiver' and receiver.role == 'patient':
        from apps.caregiver.models import CaregiverPatientAssignment
        return CaregiverPatientAssignment.objects.filter(
            caregiver=sender, patient=receiver, status='active'
        ).exists()
    if sender.role == 'caregiver' and receiver.role == 'doctor':
        from apps.caregiver.models import CaregiverPatientAssignment
        patient_ids = CaregiverPatientAssignment.objects.filter(
            caregiver=sender, status='active'
        ).values_list('patient_id', flat=True)
        return DoctorPatientConnection.objects.filter(
            doctor=receiver, patient_id__in=patient_ids, status='accepted'
        ).exists()
    return False
