from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from .models import DoctorPatientConnection
from apps.accounts.models import CustomUser
from apps.notifications.models import Notification


@login_required
def search_users(request):
    query = request.GET.get('q', '').strip()
    user = request.user
    results = []
    if query and len(query) >= 2:
        if user.role == 'patient':
            qs = CustomUser.objects.filter(
                role='doctor', is_active=True
            ).filter(
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(doctor_profile__doctor_id__icontains=query) |
                Q(doctor_profile__full_name__icontains=query) |
                Q(doctor_profile__specialty__icontains=query) |
                Q(doctor_profile__hospital_name__icontains=query)
            ).exclude(id=user.id).distinct()
            for doc in qs[:10]:
                conn = DoctorPatientConnection.objects.filter(patient=user, doctor=doc).first()
                try:
                    prof = doc.doctor_profile
                    specialty = prof.get_specialty_display() if prof.specialty else 'General'
                    hospital = prof.hospital_name or ''
                except:
                    specialty = 'General'
                    hospital = ''
                results.append({
                    'id': doc.id,
                    'name': f"Dr. {doc.get_full_name()}",
                    'unique_id': doc.unique_id,
                    'specialty': specialty,
                    'hospital': hospital,
                    'connection_status': conn.status if conn else None,
                    'connection_id': conn.id if conn else None,
                })
        elif user.role == 'doctor':
            qs = CustomUser.objects.filter(
                role='patient', is_active=True
            ).filter(
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(patient_profile__patient_id__icontains=query) |
                Q(patient_profile__first_name__icontains=query) |
                Q(patient_profile__last_name__icontains=query)
            ).exclude(id=user.id).distinct()
            for pat in qs[:10]:
                conn = DoctorPatientConnection.objects.filter(patient=pat, doctor=user).first()
                try:
                    prof = pat.patient_profile
                    blood_group = prof.blood_group or ''
                    diagnosis = prof.primary_diagnosis or ''
                except:
                    blood_group = ''
                    diagnosis = ''
                results.append({
                    'id': pat.id,
                    'name': pat.get_full_name(),
                    'unique_id': pat.unique_id,
                    'blood_group': blood_group,
                    'diagnosis': diagnosis,
                    'connection_status': conn.status if conn else None,
                    'connection_id': conn.id if conn else None,
                })
    return JsonResponse({'results': results})


@login_required
def send_request(request):
    if request.method == 'POST':
        target_id = request.POST.get('target_id')
        message = request.POST.get('message', '')
        user = request.user
        target = get_object_or_404(CustomUser, id=target_id)
        if user.role == 'patient' and target.role == 'doctor':
            patient, doctor = user, target
        elif user.role == 'doctor' and target.role == 'patient':
            patient, doctor = target, user
        else:
            return JsonResponse({'success': False, 'error': 'Invalid connection'})
        conn, created = DoctorPatientConnection.objects.get_or_create(
            patient=patient, doctor=doctor,
            defaults={'requested_by': user, 'request_message': message, 'status': 'pending'}
        )
        if not created:
            return JsonResponse({'success': False, 'error': 'Connection already exists'})
        Notification.objects.create(
            user=target,
            title='New Connection Request',
            message=f'{user.get_display_name()} sent you a connection request.',
            notification_type='connection',
            related_id=conn.id
        )
        return JsonResponse({'success': True, 'message': 'Request sent!'})
    return JsonResponse({'success': False})


@login_required
def respond_request(request, conn_id):
    if request.method == 'POST':
        conn = get_object_or_404(DoctorPatientConnection, id=conn_id)
        action = request.POST.get('action')
        user = request.user
        if (user.role == 'doctor' and conn.doctor == user) or (user.role == 'patient' and conn.patient == user):
            if action == 'accept':
                conn.status = 'accepted'
                conn.save()
                other = conn.patient if user.role == 'doctor' else conn.doctor
                Notification.objects.create(
                    user=other,
                    title='Connection Accepted',
                    message=f'{user.get_display_name()} accepted your connection request.',
                    notification_type='connection',
                    related_id=conn.id
                )
                messages.success(request, 'Connection accepted!')
            elif action == 'reject':
                conn.status = 'rejected'
                conn.save()
                messages.info(request, 'Connection rejected.')
        return redirect(request.META.get('HTTP_REFERER', '/dashboard/'))
    return redirect('/dashboard/')


@login_required
def connection_list(request):
    from apps.caregiver.access import get_active_patient_context

    user = request.user
    ctx = get_active_patient_context(request)

    if user.role == 'patient' or (user.role == 'caregiver' and ctx['caregiver_mode'] and ctx['patient']):
        subject = ctx['patient'] if user.role == 'caregiver' else user
        accepted = DoctorPatientConnection.objects.filter(patient=subject, status='accepted').select_related('doctor', 'doctor__doctor_profile')
        pending_sent = DoctorPatientConnection.objects.filter(patient=subject, status='pending', requested_by=subject)
        pending_received = DoctorPatientConnection.objects.filter(patient=subject, status='pending').exclude(requested_by=subject)
    elif user.role == 'doctor':
        accepted = DoctorPatientConnection.objects.filter(doctor=user, status='accepted').select_related('patient', 'patient__patient_profile')
        pending_sent = DoctorPatientConnection.objects.filter(doctor=user, status='pending', requested_by=user)
        pending_received = DoctorPatientConnection.objects.filter(doctor=user, status='pending').exclude(requested_by=user)
    elif user.role == 'caregiver':
        messages.info(request, 'Enter caregiver mode for a patient to view their doctor connections.')
        return redirect('caregiver_dashboard')
    else:
        accepted = DoctorPatientConnection.objects.none()
        pending_sent = DoctorPatientConnection.objects.none()
        pending_received = DoctorPatientConnection.objects.none()

    from apps.caregiver.models import get_hospital_caregiver_for_patient
    patient_caregivers = {}
    if user.role == 'doctor':
        for conn in accepted:
            cg = get_hospital_caregiver_for_patient(conn.patient, doctor=user)
            patient_caregivers[conn.patient_id] = cg
            conn.active_caregiver = cg

    return render(request, 'dashboard/connections.html', {
        'accepted': accepted,
        'pending_sent': pending_sent,
        'pending_received': pending_received,
        'patient_caregivers': patient_caregivers,
        'caregiver_mode': ctx['caregiver_mode'],
        'acting_patient': ctx['patient'] if ctx['caregiver_mode'] else None,
    })
