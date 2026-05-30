from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.db.utils import OperationalError
import time
from django.utils import timezone
from datetime import date, datetime, timedelta
from .models import Appointment, DoctorSchedule
from apps.connections.models import DoctorPatientConnection
from apps.caregiver.models import CaregiverPatientAssignment
from apps.caregiver.access import get_active_patient_context, get_patient_connected_doctors
from apps.notifications.models import Notification
from apps.notifications.utils import notify_user, remove_notifications
from apps.accounts.models import CustomUser
from apps.payments.models import ConsultationPayment
from apps.family.utils import send_family_alert
import json
import math
import requests


def _create_consultation_payment_if_due(request, apt):
    """Create pending online payment after video/emergency consultation completes."""
    from apps.payments.services import create_pending_payment
    caregiver = request.user if getattr(request.user, 'role', None) == 'caregiver' else None
    return create_pending_payment(apt, caregiver_user=caregiver)


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return round(r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)


def _user_can_view_emergency_apt(user, apt):
    if apt.patient == user:
        return True
    if user.role == 'caregiver':
        return CaregiverPatientAssignment.objects.filter(
            caregiver=user, patient=apt.patient, status='active'
        ).exists()
    return False


@login_required
def dismiss_missed_emergency_alert(request, apt_id):
    from apps.appointments.emergency_utils import dismiss_missed_emergency_alert as dismiss_alert

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    if request.user.role != 'doctor':
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    apt = get_object_or_404(Appointment, id=apt_id, doctor=request.user)
    if not dismiss_alert(apt, request.user):
        return JsonResponse({'success': False, 'error': 'Unable to dismiss alert'}, status=400)
    remaining = Appointment.objects.filter(
        doctor=request.user,
        appointment_type='emergency_video',
        is_emergency=True,
        appointment_date=date.today(),
        status='timeout',
        doctor_missed_alert_seen=False,
    ).count()
    return JsonResponse({'success': True, 'remaining_unseen': remaining})


@login_required
def emergency_history_full(request):
    """Legacy URL → unified history page."""
    return redirect('/appointments/history/?category=emergency&preset=all')


@login_required
def appointment_history(request):
    """Full appointment history with date filters (not on dashboard)."""
    from apps.appointments.history_utils import (
        HISTORY_CATEGORIES,
        annotate_history_list,
        build_history_filter_query,
        DEFAULT_EMERGENCY_DRAFT,
        filter_by_date,
        order_history,
        queryset_for_category,
        resolve_history_date_range,
    )

    user = request.user
    if user.role not in ('patient', 'doctor'):
        return redirect(user.get_dashboard_url())

    today = date.today()
    category = (request.GET.get('category') or 'all').strip().lower()
    if category not in HISTORY_CATEGORIES:
        category = 'all'

    if user.role == 'patient':
        apts = Appointment.objects.filter(patient=user).select_related(
            'doctor', 'doctor__doctor_profile'
        )
    else:
        apts = Appointment.objects.filter(doctor=user).select_related('patient')

    date_from, date_to, history_preset = resolve_history_date_range(request, today)
    items = annotate_history_list(
        order_history(
            filter_by_date(queryset_for_category(apts, category), date_from, date_to)
        ),
        user,
    )

    meta = HISTORY_CATEGORIES[category]
    return render(request, 'dashboard/appointments/appointment_history.html', {
        'items': items,
        'category': category,
        'category_meta': meta,
        'history_preset': history_preset,
        'history_date_from': date_from,
        'history_date_to': date_to,
        'today': today,
        'filter_query': build_history_filter_query(request, category),
        'default_emergency_draft': DEFAULT_EMERGENCY_DRAFT,
        'back_url': '/appointments/' if user.role == 'patient' else '/dashboard/doctor/',
    })


@login_required
def doctor_emergency_sync(request):
    """Expire stale emergencies for doctor dashboard live sync."""
    from apps.appointments.emergency_utils import expire_stale_emergencies_for_doctor

    if request.user.role != 'doctor':
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    before = Appointment.objects.filter(
        doctor=request.user,
        is_emergency=True,
        appointment_type='emergency_video',
        status='pending_doctor_confirmation',
        timeout_at__lte=timezone.now(),
    ).count()
    expire_stale_emergencies_for_doctor(request.user)
    active = Appointment.objects.filter(
        doctor=request.user,
        is_emergency=True,
        appointment_type='emergency_video',
        status='pending_doctor_confirmation',
    ).count()
    return JsonResponse({
        'success': True,
        'expired_count': before,
        'active_emergency_count': active,
    })


@login_required
def check_emergency_timeout(request, apt_id):
    from apps.appointments.emergency_utils import expire_emergency_if_needed

    apt = get_object_or_404(Appointment, id=apt_id)
    if not _user_can_view_emergency_apt(request.user, apt):
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    now = timezone.now()
    remaining = 0
    if apt.timeout_at and apt.status == 'pending_doctor_confirmation':
        remaining = max(0, int((apt.timeout_at - now).total_seconds()))

    if expire_emergency_if_needed(apt):
        return JsonResponse({
            'success': True,
            'status': 'timeout',
            'remaining_seconds': 0,
            'message': 'Doctor is currently unavailable. Please visit a nearby clinic or hospital immediately.',
        })

    show_fallback = apt.status in ('timeout', 'rejected') and apt.is_emergency
    return JsonResponse({
        'success': True,
        'status': apt.status,
        'remaining_seconds': remaining,
        'timeout_at': apt.timeout_at.isoformat() if apt.timeout_at else None,
        'show_fallback': show_fallback,
        'rejection_reason': apt.rejection_reason or '',
        'doctor_name': apt.doctor.get_full_name() if apt.doctor_id else '',
    })


@login_required
def patient_active_emergency(request):
    """Return patient's in-progress emergency wait (for UI restore after navigation/refresh)."""
    from apps.appointments.emergency_utils import expire_emergency_if_needed

    ctx = get_active_patient_context(request)
    user = request.user
    if user.role == 'patient':
        patient = user
    elif user.role == 'caregiver' and ctx['patient']:
        patient = ctx['patient']
        if not ctx['assignment']:
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    else:
        return JsonResponse({'success': True, 'active': False})

    apt = (
        Appointment.objects.filter(
            patient=patient,
            appointment_type='emergency_video',
            is_emergency=True,
            status='pending_doctor_confirmation',
        )
        .select_related('doctor')
        .order_by('-created_at')
        .first()
    )
    if not apt:
        return JsonResponse({'success': True, 'active': False})

    if expire_emergency_if_needed(apt):
        apt.refresh_from_db()

    now = timezone.now()
    remaining = 0
    if apt.timeout_at and apt.status == 'pending_doctor_confirmation':
        remaining = max(0, int((apt.timeout_at - now).total_seconds()))

    if apt.status != 'pending_doctor_confirmation':
        show_fallback = apt.status in ('timeout', 'rejected') and apt.is_emergency
        return JsonResponse({
            'success': True,
            'active': False,
            'apt_id': apt.id,
            'status': apt.status,
            'show_fallback': show_fallback,
            'rejection_reason': apt.rejection_reason or '',
            'remaining_seconds': 0,
        })

    return JsonResponse({
        'success': True,
        'active': True,
        'apt_id': apt.id,
        'status': apt.status,
        'remaining_seconds': remaining,
        'timeout_seconds': remaining or 300,
        'doctor_name': apt.doctor.get_full_name() if apt.doctor_id else '',
        'timeout_at': apt.timeout_at.isoformat() if apt.timeout_at else None,
    })


@login_required
def log_emergency_event_api(request, apt_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    apt = get_object_or_404(Appointment, id=apt_id)
    if not _user_can_view_emergency_apt(request.user, apt):
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    event_type = request.POST.get('event_type', '').strip()
    if not event_type:
        return JsonResponse({'success': False, 'error': 'event_type required'}, status=400)
    extra = {}
    clinic_name = request.POST.get('clinic_name', '').strip()
    if clinic_name:
        extra['clinic_name'] = clinic_name
    apt.log_emergency_event(event_type, extra or None)
    return JsonResponse({'success': True})


@login_required
def find_nearby_clinics_api(request):
    """Live GPS only → nearby hospitals/clinics (Overpass + Nominatim addresses)."""
    from smarttrack.nearby_places_service import search_nearby_clinics

    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    if not lat or not lng:
        return JsonResponse({'success': False, 'error': 'Location coordinates are required'}, status=400)

    try:
        lat_f, lng_f = float(lat), float(lng)
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid coordinates'}, status=400)

    if abs(lat_f) < 0.01 and abs(lng_f) < 0.01:
        return JsonResponse({'success': False, 'error': 'Invalid GPS coordinates (0,0)'}, status=400)

    fast = request.GET.get('fast', '1') != '0'
    emergency = request.GET.get('emergency', '0') == '1' or bool(request.GET.get('apt_id'))

    try:
        clinics, search_radius_m = search_nearby_clinics(
            lat_f, lng_f, fast=fast, emergency=emergency
        )
    except Exception:
        return JsonResponse({
            'success': False,
            'error': 'Clinic search is temporarily unavailable. Please call emergency services if needed.',
        }, status=503)

    apt_id = request.GET.get('apt_id')
    if apt_id:
        try:
            apt = Appointment.objects.get(id=int(apt_id))
            if _user_can_view_emergency_apt(request.user, apt):
                apt.log_emergency_event('nearby_clinic_suggested', {'count': len(clinics)})
        except (Appointment.DoesNotExist, ValueError):
            pass

    payload = {
        'success': True,
        'clinics': clinics,
        'total': len(clinics),
        'search_radius_m': search_radius_m,
        'user_lat': lat_f,
        'user_lng': lng_f,
    }
    from django.conf import settings
    if settings.DEBUG or request.GET.get('debug') == '1':
        from smarttrack.nearby_places_service import get_last_nearby_search_debug
        payload['debug'] = get_last_nearby_search_debug()
    return JsonResponse(payload)


@login_required
def book_appointment(request):
    user = request.user
    today = date.today()

    if user.role == 'doctor':
        return _book_appointment_doctor(request, user, today)

    ctx = get_active_patient_context(request)
    patient = ctx['patient']

    if user.role == 'caregiver':
        if not patient or not ctx['caregiver_mode']:
            messages.error(request, 'Enter caregiver mode for a patient before booking appointments.')
            return redirect('caregiver_dashboard')
        if not ctx['assignment'] or not ctx['assignment'].can_manage_appointments:
            messages.error(request, 'You do not have permission to book appointments for this patient.')
            return redirect('caregiver_dashboard')

    doctors = get_patient_connected_doctors(patient) if patient else []

    if request.method == 'POST':
        doctor_id = request.POST.get('doctor_id')
        apt_date = request.POST.get('appointment_date')
        apt_time = request.POST.get('appointment_time')
        apt_type = request.POST.get('appointment_type', 'in_person')
        reason = request.POST.get('reason', '')
        is_emergency = request.POST.get('is_emergency') == '1'

        if not all([doctor_id, apt_date, apt_time]):
            messages.error(request, 'Please fill all required fields.')
            return render(request, 'dashboard/patient/book_appointment.html', {
                'doctors': doctors, 'today': today, 'caregiver_mode': ctx['caregiver_mode'],
                'acting_patient': patient,
            })

        doctor = get_object_or_404(CustomUser, id=doctor_id, role='doctor')

        if user.role == 'patient':
            target_patient = user
        elif user.role == 'caregiver' and patient:
            target_patient = patient
            if not DoctorPatientConnection.objects.filter(
                patient=target_patient, doctor=doctor, status='accepted',
            ).exists():
                messages.error(request, 'Selected doctor is not connected to this patient.')
                return render(request, 'dashboard/patient/book_appointment.html', {
                    'doctors': doctors, 'today': today, 'caregiver_mode': True,
                    'acting_patient': patient,
                })
        else:
            messages.error(request, 'Unauthorized.')
            return redirect('/dashboard/')

        initial_status = 'pending_doctor_confirmation' if is_emergency else 'pending_confirmation'
        apt = Appointment.objects.create(
            patient=target_patient,
            doctor=doctor,
            appointment_date=apt_date,
            appointment_time=apt_time,
            appointment_type=apt_type,
            reason=reason,
            is_emergency=is_emergency,
            status=initial_status,
        )

        notify_user(
            user=doctor,
            title='🗓 New Appointment Request' + (' [EMERGENCY]' if is_emergency else ''),
            message=(
                f'{target_patient.get_full_name()} requested a {apt.get_appointment_type_display()} '
                f'on {apt_date} at {apt_time}. Reason: {reason or "—"}. Please confirm or reject.'
                + (f' (Booked by caregiver {user.get_full_name()})' if user.role == 'caregiver' else '')
            ),
            notification_type='appointment',
            priority='high' if is_emergency else 'medium',
            category=f'apt_req_{apt.id}',
            related_id=apt.id
        )

        if is_emergency:
            messages.success(request, '🚨 Emergency video consultation requested! Doctor has been notified urgently.')
        else:
            messages.success(request, '✅ Appointment booked successfully! Awaiting doctor confirmation.')
        return redirect('/appointments/')

    return render(request, 'dashboard/patient/book_appointment.html', {
        'doctors': doctors,
        'today': today,
        'caregiver_mode': ctx['caregiver_mode'],
        'acting_patient': patient,
    })


def _book_appointment_doctor(request, user, today):
    """Doctor schedules appointment for a connected patient — auto-confirmed."""
    conns = DoctorPatientConnection.objects.filter(doctor=user, status='accepted').select_related('patient')
    patients = [c.patient for c in conns]
    patient_id = request.GET.get('patient_id') or request.POST.get('patient_id')
    selected_patient = None
    if patient_id:
        selected_patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
        if not DoctorPatientConnection.objects.filter(doctor=user, patient=selected_patient, status='accepted').exists():
            messages.error(request, 'This patient is not connected to you.')
            return redirect('/appointments/book/')

    if request.method == 'POST':
        if not selected_patient:
            messages.error(request, 'Please select a patient.')
            return redirect('/appointments/book/')
        apt_date = request.POST.get('appointment_date')
        apt_time = request.POST.get('appointment_time')
        apt_type = request.POST.get('appointment_type', 'in_person')
        reason = request.POST.get('reason', '')

        if not all([apt_date, apt_time]):
            messages.error(request, 'Please fill date and time.')
            return redirect(f'/appointments/book/?patient_id={selected_patient.id}')

        if apt_type == 'emergency_video':
            apt_type = 'video'

        apt = Appointment.objects.create(
            patient=selected_patient,
            doctor=user,
            appointment_date=apt_date,
            appointment_time=apt_time,
            appointment_type=apt_type,
            reason=reason,
            is_emergency=False,
            status='confirmed',
            confirmed_at=timezone.now(),
            confirmed_by=user,
            emergency_status='accepted',
            doctor_response='accepted',
            responded_at=timezone.now(),
        )
        if apt_type == 'video':
            apt.generate_video_link()

        notify_user(
            user=selected_patient,
            title='✅ Appointment Scheduled',
            message=(
                f'Dr. {user.get_full_name()} scheduled a {apt.get_appointment_type_display()} '
                f'for you on {apt_date} at {apt_time}. {("Notes: " + reason) if reason else ""}'
            ).strip(),
            notification_type='appointment',
            priority='medium',
            category=f'apt_confirm_{apt.id}',
            related_id=apt.id,
        )
        messages.success(request, f'Appointment booked for {selected_patient.get_full_name()}.')
        return redirect('/appointments/')

    if not patients and not selected_patient:
        messages.warning(request, 'Connect with patients before booking appointments.')

    return render(request, 'dashboard/doctor/book_appointment.html', {
        'patients': patients,
        'selected_patient': selected_patient or (patients[0] if len(patients) == 1 else None),
        'doctor': user,
        'today': today,
        'multiple_patients': len(patients) > 1,
    })


@login_required
def appointment_list(request):
    from apps.appointments.emergency_utils import (
        expire_stale_emergencies_for_doctor,
        expire_stale_emergencies_for_patient,
    )

    user = request.user
    today = date.today()
    ctx = get_active_patient_context(request)

    if user.role == 'doctor':
        expire_stale_emergencies_for_doctor(user)
    elif user.role == 'patient':
        expire_stale_emergencies_for_patient(user)
    elif user.role == 'caregiver' and ctx['patient']:
        expire_stale_emergencies_for_patient(ctx['patient'])

    if user.role == 'patient':
        apts = Appointment.objects.filter(patient=user).select_related('doctor', 'doctor__doctor_profile').order_by('-appointment_date', '-appointment_time')
    elif user.role == 'caregiver' and ctx['patient']:
        apts = Appointment.objects.filter(patient=ctx['patient']).select_related('doctor', 'doctor__doctor_profile').order_by('-appointment_date', '-appointment_time')
    elif user.role == 'doctor':
        apts = Appointment.objects.filter(doctor=user).select_related('patient').order_by('-appointment_date', '-appointment_time')
    else:
        apts = Appointment.objects.none()

    upcoming = apts.filter(
        appointment_date__gte=today,
        status__in=[
            'pending', 'pending_confirmation', 'pending_doctor_confirmation',
            'doctor_confirmed', 'patient_confirmed', 'confirmed', 'ongoing'
        ]
    ).select_related('doctor', 'doctor__doctor_profile').order_by('appointment_date', 'appointment_time')

    for apt in upcoming:
        status_user = ctx['patient'] if user.role == 'caregiver' and ctx['patient'] else user
        apt.role_status = apt.get_role_based_status(status_user)

    from apps.appointments.history_utils import (
        build_today_dashboard_sections,
        DEFAULT_EMERGENCY_DRAFT,
        HISTORY_CATEGORIES,
    )

    today_sections = build_today_dashboard_sections(apts, user if user.role != 'caregiver' else ctx['patient'], today)
    if user.role == 'doctor':
        today_sections['today_emergency_consult'] = []
    else:
        today_sections['today_emergency'] = []
    today_sections['today_past'] = []

    return render(request, 'dashboard/patient/appointments.html', {
        'upcoming': upcoming,
        'today': today,
        'today_sections': today_sections,
        'history_categories': HISTORY_CATEGORIES,
        'default_emergency_draft': DEFAULT_EMERGENCY_DRAFT,
        'caregiver_mode': ctx['caregiver_mode'],
        'acting_patient': ctx['patient'] if ctx['caregiver_mode'] else None,
    })


@login_required
def update_appointment(request, apt_id):
    if request.method == 'POST':
        from apps.appointments.emergency_utils import expire_emergency_if_needed

        apt = get_object_or_404(Appointment, id=apt_id)
        user = request.user
        action = request.POST.get('action')

        if user.role == 'doctor' and apt.doctor == user:
            expire_emergency_if_needed(apt)
            apt.refresh_from_db()
            if action == 'confirm':
                success, error = apt.confirm_by_doctor(user)
                if not success:
                    messages.error(request, error)
                    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))

                doctor_name = user.get_full_name()
                notify_user(
                    user=apt.patient,
                    title='✅ Appointment Confirmed',
                    message=(
                        f'Dr. {doctor_name} confirmed your {apt.get_appointment_type_display()} '
                        f'on {apt.appointment_date} at {apt.appointment_time.strftime("%I:%M %p")}.'
                    ),
                    notification_type='appointment',
                    priority='medium',
                    category=f'apt_confirm_{apt.id}',
                    related_id=apt.id
                )
                messages.success(request, 'Appointment confirmed. Patient has been notified.')
            elif action == 'reject':
                reason = request.POST.get('rejection_reason', '').strip()
                if reason == 'Other':
                    reason = request.POST.get('rejection_reason_custom', '').strip()
                success, error = apt.reject_by_doctor(user, reason)
                if not success:
                    messages.error(request, error)
                    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))

                notify_user(
                    user=apt.patient,
                    title='❌ Appointment Rejected',
                    message=f'Dr. {user.get_full_name()} rejected your appointment. Reason: {reason}',
                    notification_type='appointment',
                    priority='high',
                    category=f'apt_reject_{apt.id}',
                    related_id=apt.id
                )
                if apt.is_emergency:
                    send_family_alert(
                        patient=apt.patient,
                        alert_type='emergency_rejected',
                        title='Emergency Call Rejected',
                        message=f'Dr. {user.get_full_name()} rejected the emergency call. Reason: {reason}',
                        priority='high',
                    )
                    for assignment in CaregiverPatientAssignment.objects.filter(
                        patient=apt.patient, status='active'
                    ):
                        if assignment.caregiver_id != apt.patient_id:
                            notify_user(
                                user=assignment.caregiver,
                                title='🚨 Patient Emergency Rejected',
                                message=f'{apt.patient.get_full_name()}: {reason}',
                                notification_type='alert',
                                priority='high',
                                category=f'apt_reject_{apt.id}',
                                related_id=apt.id,
                            )
                messages.info(request, 'Appointment rejected. Patient has been notified.')
            elif action == 'complete':
                success, error = apt.transition_to('completed')
                if not success:
                    messages.error(request, error)
                    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))

                apt.notes = request.POST.get('notes', apt.notes)
                apt.save()

                # Remove all notifications related to this appointment
                remove_notifications(user=apt.patient, category_contains=f'apt_{apt.id}')
                remove_notifications(user=apt.doctor, category_contains=f'apt_{apt.id}')

                _create_consultation_payment_if_due(request, apt)
                messages.success(request, 'Appointment marked as completed.')
            elif action == 'cancel':
                reason = request.POST.get('cancellation_reason', '').strip()
                if reason == 'Other':
                    reason = request.POST.get('cancellation_reason_custom', '').strip()
                if not reason:
                    messages.error(request, 'Cancellation reason is required.')
                    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))
                if apt.status in ('completed', 'ended', 'rejected', 'timeout', 'cancelled_by_doctor', 'cancelled_by_patient'):
                    messages.error(request, 'This appointment cannot be cancelled.')
                    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))
                apt.cancel_appointment('doctor', reason)
                notify_user(
                    user=apt.patient,
                    title='Appointment Cancelled by Doctor',
                    message=f'Dr. {user.get_full_name()} cancelled your appointment on {apt.appointment_date}. Reason: {reason}',
                    notification_type='appointment',
                    priority='high',
                    category=f'apt_cancel_{apt.id}',
                    related_id=apt.id,
                )
                messages.success(request, 'Appointment cancelled. Patient has been notified.')
            elif action == 'end_call':
                success, error, _history = apt.end_video_consultation(user)
                if not success:
                    messages.error(request, error)
                    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))

                notify_user(
                    user=apt.patient,
                    title='🏁 Consultation Ended',
                    message='Dr. ' + apt.doctor.get_full_name() + ' has ended the video consultation.',
                    notification_type='appointment',
                    priority='medium',
                    category=f'apt_ended_{apt.id}',
                    related_id=apt.id
                )
                _create_consultation_payment_if_due(request, apt)
                messages.success(request, 'Call ended.')

        elif (user.role == 'patient' and apt.patient == user) or \
             (user.role == 'caregiver' and CaregiverPatientAssignment.objects.filter(caregiver=user, patient=apt.patient, status='active', can_manage_appointments=True).exists()):

            target_user = apt.patient if user.role == 'patient' else user

            if action == 'confirm_attendance':
                if apt.status == 'doctor_confirmed' and apt.appointment_type in ('in_person', 'video'):
                    success, error = apt.transition_to('confirmed')
                    if not success:
                        messages.error(request, error)
                        return redirect(request.META.get('HTTP_REFERER', '/appointments/'))

                    notify_user(
                        user=apt.doctor,
                        title='✅ Patient Confirmed Attendance',
                        message=f'{target_user.get_full_name()} has confirmed their {apt.get_appointment_type_display()} appointment on {apt.appointment_date}.',
                        notification_type='appointment',
                        priority='medium',
                        category=f'apt_patient_confirm_{apt.id}',
                        related_id=apt.id
                    )
                    messages.success(request, 'Attendance confirmed.')
                else:
                    messages.error(request, 'This appointment is not eligible for attendance confirmation.')
                    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))
            elif action == 'cancel':
                messages.error(
                    request,
                    'Appointment cancellation is not available. Wait for your doctor to Confirm or Reject.',
                )
                return redirect(request.META.get('HTTP_REFERER', '/appointments/'))
            elif action == 'end_call':
                success, error, _history = apt.end_video_consultation(target_user)
                if not success:
                    messages.error(request, error)
                    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))

                notify_user(
                    user=apt.doctor,
                    title='🏁 Consultation Ended',
                    message=f'{target_user.get_full_name()} has ended the video consultation.',
                    notification_type='appointment',
                    priority='medium',
                    category=f'apt_ended_{apt.id}',
                    related_id=apt.id
                )
                _create_consultation_payment_if_due(request, apt)
                messages.success(request, 'Call ended.')
            elif action == 'switch_video':
                apt.appointment_type = 'video'
                apt.generate_video_link()
                apt.save()
                notify_user(
                    user=apt.doctor,
                    title='🎥 Appointment Switched to Video',
                    message=f'{target_user.get_full_name()} switched their appointment on {apt.appointment_date} to video consultation.',
                    notification_type='appointment',
                    priority='low',
                    category=f'apt_video_{apt.id}',
                    related_id=apt.id
                )
                messages.success(request, 'Appointment switched to video consultation.')

    return redirect(request.META.get('HTTP_REFERER', '/appointments/'))


@login_required
def end_video_call(request, apt_id):
    """JSON API — end video/emergency consultation and persist history."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    apt = get_object_or_404(Appointment, id=apt_id)
    user = request.user

    if user.role == 'caregiver':
        from apps.caregiver.models import CaregiverPatientAssignment
        if not CaregiverPatientAssignment.objects.filter(
            caregiver=user, patient=apt.patient, status='active', can_manage_appointments=True,
        ).exists():
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
        acting_user = apt.patient
    elif user in (apt.patient, apt.doctor):
        acting_user = user
    else:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    success, error, history = apt.end_video_consultation(acting_user)
    if not success:
        return JsonResponse({'success': False, 'error': error}, status=400)

    other = apt.doctor if acting_user == apt.patient else apt.patient
    notify_user(
        user=other,
        title='🏁 Consultation Ended',
        message=(
            f'{"Dr. " + apt.doctor.get_full_name() if acting_user == apt.doctor else apt.patient.get_full_name()} '
            f'ended the video consultation.'
        ),
        notification_type='appointment',
        priority='medium',
        category=f'apt_ended_{apt.id}',
        related_id=apt.id,
    )
    remove_notifications(user=apt.patient, category_contains=f'apt_{apt.id}')
    remove_notifications(user=apt.doctor, category_contains=f'apt_{apt.id}')
    _create_consultation_payment_if_due(request, apt)

    duration_label = apt.get_duration()
    return JsonResponse({
        'success': True,
        'message': 'Consultation ended successfully.',
        'redirect_url': '/appointments/',
        'duration': duration_label,
        'duration_seconds': apt.call_duration_seconds,
        'ended_by': apt.call_ended_by,
        'history_id': history.id if history else None,
    })



@login_required
def video_call(request, session_id):
    """
    The actual video consultation page.
    """
    apt = get_object_or_404(Appointment, video_session_id=session_id)
    if request.user != apt.patient and request.user != apt.doctor:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': 'You are not authorized to join this call.'}, status=403)
        return redirect('/appointments/')

    # Only allow join if confirmed or ongoing
    if apt.status not in ('confirmed', 'ongoing'):
        err = "This call has not been confirmed yet or has already ended."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': err}, status=403)
        messages.error(request, err)
        return redirect('/appointments/')

    # Mark participant joined for synchronized call state/timer.
    now = timezone.now()
    dirty = False
    if request.user == apt.doctor and not apt.doctor_joined_at:
        if not apt.patient_joined_at:
            apt.clear_webrtc_signaling()
            dirty = True
        apt.doctor_joined_at = now
        dirty = True
    if request.user == apt.patient and not apt.patient_joined_at:
        if not apt.doctor_joined_at:
            apt.clear_webrtc_signaling()
            dirty = True
        apt.patient_joined_at = now
        dirty = True

    # Move to ongoing when first participant enters confirmed call.
    if apt.status == 'confirmed':
        apt.status = 'ongoing'
        dirty = True

    # Start shared timer only when both participants have joined.
    if apt.doctor_joined_at and apt.patient_joined_at and not apt.call_started_at:
        apt.call_started_at = max(apt.doctor_joined_at, apt.patient_joined_at)
        dirty = True

    if dirty:
        apt.save()

    if apt.video_call_status != 'ended':
        apt.video_call_status = 'active'
        apt.save(update_fields=['video_call_status', 'updated_at'])

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'dashboard/patient/video_call_content.html', {'apt': apt})

    return render(request, 'dashboard/patient/video_call.html', {'apt': apt})


def _append_ice_candidate(ice_list, candidate):
    """Append ICE candidate; skip duplicates by candidate string."""
    cand_str = candidate.get('candidate') if isinstance(candidate, dict) else None
    if cand_str:
        for existing in ice_list:
            if isinstance(existing, dict) and existing.get('candidate') == cand_str:
                return ice_list
    ice_list.append(candidate)
    return ice_list[-80:]


def _save_webrtc_ice(apt_id, role, candidate):
    """Save ICE without long row locks (avoids SQLite database locked errors)."""
    field = 'webrtc_ice_doctor' if role == 'doctor' else 'webrtc_ice_patient'
    last_error = None
    for attempt in range(5):
        try:
            apt = Appointment.objects.get(pk=apt_id)
            current = list(getattr(apt, field) or [])
            setattr(apt, field, _append_ice_candidate(current, candidate))
            apt.save(update_fields=[field, 'updated_at'])
            return True
        except OperationalError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    raise last_error


@login_required
def webrtc_signal(request, apt_id):
    """
    REST signaling channel for offer/answer/ICE exchange.
  """
    apt = get_object_or_404(Appointment, id=apt_id)
    if request.user != apt.patient and request.user != apt.doctor:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    role = 'doctor' if request.user == apt.doctor else 'patient'

    if request.method == 'POST':
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

        event_type = payload.get('type')

        # ICE posts are frequent — do not use select_for_update (causes SQLite lock storms).
        if event_type == 'ice':
            candidate = payload.get('candidate')
            if not candidate:
                return JsonResponse({'success': False, 'error': 'Missing ICE candidate'}, status=400)
            try:
                _save_webrtc_ice(apt_id, role, candidate)
                return JsonResponse({'success': True, 'event': 'ice_saved'})
            except OperationalError:
                return JsonResponse(
                    {'success': False, 'error': 'Signaling busy, retrying…'},
                    status=503,
                )

        try:
            with transaction.atomic():
                apt = Appointment.objects.select_for_update().get(pk=apt_id)
                if request.user != apt.patient and request.user != apt.doctor:
                    return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

                if event_type == 'offer' and role == 'doctor':
                    sdp = payload.get('sdp') or {}
                    if not sdp.get('type') or not sdp.get('sdp'):
                        return JsonResponse({'success': False, 'error': 'Invalid offer SDP'}, status=400)
                    apt.webrtc_offer = sdp
                    apt.webrtc_answer = {}
                    apt.save(update_fields=['webrtc_offer', 'webrtc_answer', 'updated_at'])
                    return JsonResponse({'success': True, 'event': 'offer_saved'})

                if event_type == 'answer' and role == 'patient':
                    sdp = payload.get('sdp') or {}
                    if not sdp.get('type') or not sdp.get('sdp'):
                        return JsonResponse({'success': False, 'error': 'Invalid answer SDP'}, status=400)
                    apt.webrtc_answer = sdp
                    apt.save(update_fields=['webrtc_answer', 'updated_at'])
                    return JsonResponse({'success': True, 'event': 'answer_saved'})

                if event_type == 'connected':
                    if not apt.call_started_at:
                        apt.call_started_at = timezone.now()
                        apt.save(update_fields=['call_started_at', 'updated_at'])
                    return JsonResponse({
                        'success': True,
                        'event': 'connected',
                        'call_started_at': apt.call_started_at.isoformat() if apt.call_started_at else None,
                    })
        except OperationalError:
            return JsonResponse(
                {'success': False, 'error': 'Database busy, please retry'},
                status=503,
            )

        return JsonResponse({'success': False, 'error': 'Invalid signaling event'}, status=400)

    apt = Appointment.objects.get(pk=apt_id)
    offer = apt.webrtc_offer if role == 'patient' else {}
    answer = apt.webrtc_answer if role == 'doctor' else {}
    remote_ice = apt.webrtc_ice_patient if role == 'doctor' else apt.webrtc_ice_doctor

    return JsonResponse({
        'success': True,
        'role': role,
        'is_initiator': role == 'doctor',
        'room_id': apt.get_video_room_id(),
        'offer': offer if isinstance(offer, dict) and offer.get('sdp') else {},
        'answer': answer if isinstance(answer, dict) and answer.get('sdp') else {},
        'ice': list(remote_ice or []),
        'ice_count': len(remote_ice or []),
        'doctor_joined': bool(apt.doctor_joined_at),
        'patient_joined': bool(apt.patient_joined_at),
        'both_joined': bool(apt.doctor_joined_at and apt.patient_joined_at),
        'call_started_at': apt.call_started_at.isoformat() if apt.call_started_at else None,
        'status': apt.status,
        'video_call_status': apt.video_call_status,
        'call_ended': apt.video_call_status == 'ended' or apt.status in ('completed', 'ended'),
    })

@login_required
def nearby_clinics(request):
    """
    Provides a list of nearby emergency clinics.
    The actual searching is handled on the frontend via Google Maps/OSM API,
    but we provide the framework here.
    """
    return render(request, 'dashboard/patient/nearby_clinics.html')

@login_required
def appointment_detail(request, apt_id):
    apt = get_object_or_404(Appointment, id=apt_id)
    user = request.user
    ctx = get_active_patient_context(request)
    allowed = (
        user == apt.patient
        or user == apt.doctor
        or (user.role == 'caregiver' and ctx['patient'] and ctx['patient'].id == apt.patient_id)
    )
    if not allowed:
        return redirect('/appointments/')
    apt.role_status = apt.get_role_based_status(user if user.role != 'caregiver' else ctx['patient'])
    payment = None
    try:
        payment = apt.consultation_payment
    except ConsultationPayment.DoesNotExist:
        pass
    if payment is None and apt.status in ('completed', 'ended'):
        from apps.payments.services import requires_online_payment, create_pending_payment
        if requires_online_payment(apt):
            payment = create_pending_payment(apt)
    return render(request, 'dashboard/patient/appointment_detail.html', {
        'apt': apt,
        'payment': payment,
    })


@login_required
def request_emergency_video(request):
    if request.method == 'POST':
        user = request.user
        ctx = get_active_patient_context(request)
        if user.role not in ('patient', 'caregiver'):
            return JsonResponse({'success': False, 'error': 'Only patients or caregivers can request emergency consultations'})

        doctor_id = request.POST.get('doctor_id')
        notes = request.POST.get('notes', 'Emergency video consultation requested')

        if user.role == 'caregiver':
            target_patient = ctx['patient']
            if not target_patient or not ctx['caregiver_mode']:
                return JsonResponse({'success': False, 'error': 'Enter caregiver mode for a patient first'})
            if not ctx['assignment']:
                return JsonResponse({'success': False, 'error': 'Not authorized to request emergency for this patient'})
            requesting_user = user
            actual_patient = target_patient
        else:
            requesting_user = user
            actual_patient = user

        if doctor_id:
            doctor = get_object_or_404(CustomUser, id=doctor_id, role='doctor')
        else:
            # Find connected available doctor
            conn = DoctorPatientConnection.objects.filter(patient=actual_patient, status='accepted').first()
            if not conn:
                return JsonResponse({'success': False, 'error': 'No connected doctor found'})
            doctor = conn.doctor

        timeout_at = timezone.now() + timedelta(minutes=5)
        apt = Appointment.objects.create(
            patient=actual_patient,
            doctor=doctor,
            appointment_date=date.today(),
            appointment_time=timezone.localtime().time(),
            appointment_type='emergency_video',
            reason=notes,
            is_emergency=True,
            emergency_status='pending',
            status='pending_doctor_confirmation',
            timeout_at=timeout_at,
        )
        apt.log_emergency_event('emergency_request_created', {'doctor_id': doctor.id})

        notify_user(
            user=doctor,
            title='🚨 EMERGENCY: Immediate Video Consultation Needed',
            message=f'URGENT: {actual_patient.get_full_name()} needs an emergency video consultation immediately. (Requested by {requesting_user.get_full_name()}). Please join now.',
            notification_type='alert',
            priority='high',
            category=f'apt_emergency_{apt.id}',
            related_id=apt.id
        )

        # Alert family members
        send_family_alert(
            patient=actual_patient,
            alert_type='emergency',
            title='🚨 EMERGENCY SOS',
            message=f'Urgent: {actual_patient.get_full_name()} has triggered an SOS emergency video call. Immediate attention required!',
            priority='high'
        )

        return JsonResponse({
            'success': True,
            'apt_id': apt.id,
            'timeout_at': timeout_at.isoformat(),
            'timeout_seconds': 300,
            'doctor_name': doctor.get_full_name(),
            'message': 'Emergency consultation requested. Doctor has been notified urgently.',
        })

    return JsonResponse({'success': False}, status=400)


@login_required
def doctor_schedule(request, doctor_id):
    """Get doctor schedule as JSON for the booking form."""
    doctor = get_object_or_404(CustomUser, id=doctor_id, role='doctor')
    schedules = DoctorSchedule.objects.filter(doctor=doctor, is_available=True)
    data = [{
        'day': s.day_of_week,
        'start_time': s.start_time.strftime('%H:%M'),
        'end_time': s.end_time.strftime('%H:%M'),
        'slot_duration': s.slot_duration_minutes,
    } for s in schedules]

    # Get booked slots for next 30 days
    today = date.today()
    booked = {}
    for i in range(30):
        d = today + timedelta(days=i)
        day_name = d.strftime('%A').lower()
        apts = Appointment.objects.filter(
            doctor=doctor,
            appointment_date=d,
            status__in=[
                'pending', 'pending_confirmation', 'pending_doctor_confirmation',
                'confirmed', 'doctor_confirmed', 'patient_confirmed', 'ongoing',
            ]
        ).values_list('appointment_time', flat=True)
        if apts:
            booked[str(d)] = [t.strftime('%H:%M') for t in apts]

    return JsonResponse({
        'schedules': data,
        'booked_slots': booked,
        'doctor_name': f"Dr. {doctor.get_full_name()}",
    })
