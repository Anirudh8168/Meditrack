import requests
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from datetime import date, timedelta, datetime
from .models import (
    Medicine, MedicineLog, MedicineRefill, MedicineInventoryEvent,
    Activity, ActivityLog, RiskScore, DailyHealthCheck, FamilyContact,
    MissedAlertLog, HealthRiskAlert,
)
from apps.medicines.activity_permissions import user_can_manage_activity
from apps.medicines.activity_service import (
    log_audit,
    parse_activity_form,
    edit_activity as edit_activity_record,
    delete_activity as delete_activity_record,
)
from apps.medicines.activity_utils import (
    categorize_activity_logs,
    resolve_activity_severity,
    get_patient_activity_reminders,
    get_or_create_log,
    activity_compliance_stats,
    get_active_schedule_summaries,
    get_activity_detail_bundle,
    get_doctor_activity_monitoring,
)
from apps.medicines.reminder_engine import (
    is_popup_due,
    parse_slot_datetime,
    seconds_until_slot,
    should_auto_mark_missed,
)
from apps.connections.models import DoctorPatientConnection
from apps.accounts.models import CustomUser
from apps.notifications.models import Notification
from apps.notifications.utils import notify_user, remove_notifications
from apps.family.utils import send_family_alert
from apps.medicines.color_utils import QUICK_COLORS, normalize_medicine_color
import json
import math


def _resolve_subject_user(request):
    """Patient user for data operations — supports caregiver acting mode."""
    from apps.caregiver.access import get_active_patient_context
    ctx = get_active_patient_context(request)
    if ctx['patient']:
        return ctx['patient'], ctx['caregiver_mode']
    return request.user, False


def _is_patient_context(request):
    user = request.user
    if user.role == 'patient':
        return True
    _, is_cg = _resolve_subject_user(request)
    return is_cg


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return round(r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)


def calculate_risk_score(patient, trigger_medicine=None):
    """Calculate patient risk via multi-factor healthcare engine."""
    from apps.medicines.risk_calculation_service import RiskCalculationService
    return RiskCalculationService.calculate(patient, trigger_medicine=trigger_medicine)


def notify_family_if_needed(patient, medicine=None):
    """Legacy hook — escalation is handled inside calculate_risk_score."""
    pass


@login_required
def find_pharmacies(request):
    """Live GPS only → nearby pharmacies/medical stores (Overpass + Nominatim addresses)."""
    from smarttrack.nearby_places_service import search_nearby_pharmacies

    lat = request.GET.get('lat')
    lng = request.GET.get('lng')

    if not lat or not lng:
        return JsonResponse({'success': False, 'error': 'Live location coordinates are required'}, status=400)

    try:
        lat_f, lng_f = float(lat), float(lng)
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid coordinates'}, status=400)

    if abs(lat_f) < 0.01 and abs(lng_f) < 0.01:
        return JsonResponse({'success': False, 'error': 'Invalid GPS coordinates (0,0)'}, status=400)

    fast = request.GET.get('fast', '1') != '0'
    emergency = request.GET.get('emergency', '0') == '1'

    try:
        pharmacies, search_radius_m = search_nearby_pharmacies(
            lat_f, lng_f, fast=fast, emergency=emergency
        )
    except Exception:
        return JsonResponse({
            'success': False,
            'error': 'Pharmacy search is temporarily unavailable. Please try again.',
        }, status=503)

    payload = {
        'success': True,
        'pharmacies': pharmacies,
        'total': len(pharmacies),
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
def medicine_list(request):
    subject, caregiver_mode = _resolve_subject_user(request)
    user = request.user

    if subject.role == 'patient' or caregiver_mode:
        medicines = Medicine.objects.filter(patient=subject, is_active=True).order_by('name')
    elif user.role == 'doctor':
        from apps.connections.models import DoctorPatientConnection as DPC
        conns = DPC.objects.filter(doctor=user, status='accepted')
        patient_ids = [c.patient_id for c in conns]
        medicines = Medicine.objects.filter(patient_id__in=patient_ids, is_active=True).order_by('-created_at')
    elif user.role == 'caregiver':
        from apps.caregiver.models import CaregiverPatientAssignment
        assignments = CaregiverPatientAssignment.objects.filter(caregiver=user, status='active')
        patient_ids = [a.patient_id for a in assignments]
        medicines = Medicine.objects.filter(patient_id__in=patient_ids, is_active=True).order_by('-created_at')
    else:
        medicines = Medicine.objects.none()

    today = date.today()
    now = timezone.localtime()
    is_patient_view = subject.role == 'patient' or caregiver_mode

    from apps.medicines.medicine_schedule_utils import attach_medicine_dose_ui

    for m in medicines:
        if is_patient_view:
            attach_medicine_dose_ui(m, subject, today, now)
        else:
            m.today_taken_count = m.logs.filter(scheduled_time__date=today, status='taken').count()
            m.today_taken = m.today_taken_count >= m.max_daily_doses
            m.can_take_more = m.today_taken_count < m.max_daily_doses
            m.is_time_to_take = False
            m.dose_button_state = 'locked'

    expired_meds = []
    if is_patient_view:
        expired_meds = Medicine.objects.filter(patient=subject, is_active=False).order_by('-updated_at')[:10]
        for m in Medicine.objects.filter(patient=subject, is_active=True):
            if m.end_date and m.end_date < today:
                m.is_active = False
                m.save()
                notify_user(
                    user=subject,
                    title='💊 Medicine Course Completed',
                    message=f'"{m.name}" prescription has expired (ended {m.end_date}). Course completed.',
                    notification_type='medicine',
                    category=f'med_expired_{m.id}'
                )

    return render(request, 'dashboard/patient/medicines.html', {
        'medicines': medicines,
        'expired_meds': expired_meds,
        'today': today,
        'now': now,
        'is_patient': is_patient_view,
        'is_doctor': user.role == 'doctor',
        'caregiver_mode': caregiver_mode,
    })


@login_required
def add_medicine(request):
    # Only doctors can add medicines
    if request.user.role == 'patient':
        messages.error(request, 'Patients cannot add medicines. Please contact your doctor.')
        return redirect('/medicines/')

    user = request.user
    patients = []
    if user.role == 'doctor':
        conns = DoctorPatientConnection.objects.filter(doctor=user, status='accepted')
        patients = [c.patient for c in conns]

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        dosage = request.POST.get('dosage', '').strip()
        frequency = request.POST.get('frequency', '')
        time_slots = request.POST.getlist('time_slots')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date') or None
        instructions = request.POST.get('instructions', '')
        expiry = request.POST.get('expiry_date') or None

        def _parse_date(val):
            if not val:
                return None
            try:
                return datetime.strptime(val, '%Y-%m-%d').date()
            except ValueError:
                return None

        start_date_parsed = _parse_date(start_date)
        end_date_parsed = _parse_date(end_date)
        expiry_parsed = _parse_date(expiry)
        is_critical = request.POST.get('is_critical_medicine') == 'on'
        from apps.medicines.inventory_service import parse_low_stock_alert_at
        low_stock_alert = parse_low_stock_alert_at(
            request.POST.get('low_stock_alert_at'),
            default=5 if is_critical else 3,
        )
        color = normalize_medicine_color(
            request.POST.get('color', 'blue'),
            request.POST.get('color', 'blue'),
            request.POST.get('custom_color', ''),
        )

        if not all([name, dosage, frequency, start_date_parsed]):
            messages.error(request, 'Please fill all required fields.')
            return render(request, 'dashboard/patient/add_medicine.html', {
                'patients': patients,
                'quick_colors': QUICK_COLORS,
                'quick_color_values': [c[0] for c in QUICK_COLORS],
            })

        patient_id = request.POST.get('patient_id')
        patient = get_object_or_404(CustomUser, id=patient_id)

        med = Medicine.objects.create(
            patient=patient, prescribed_by=user,
            name=name, dosage=dosage, frequency=frequency,
            time_slots=time_slots, start_date=start_date_parsed,
            end_date=end_date_parsed, instructions=instructions,
            expiry_date=expiry_parsed, color=color,
            is_critical_medicine=is_critical,
            critical_stock_threshold=low_stock_alert,
        )
        from apps.medicines.risk_calculation_service import _is_critical_medicine
        if not is_critical and _is_critical_medicine(med):
            med.is_critical_medicine = True
            med.save(update_fields=['is_critical_medicine'])
        from apps.medicines.inventory_service import apply_prescription_inventory
        qty = apply_prescription_inventory(med)
        notify_user(
            patient,
            title='💊 New Medicine Prescribed',
            message=(
                f'Dr. {user.get_full_name()} prescribed "{name}" ({dosage}) — '
                f'{qty} doses prescribed. Please add your purchase when you buy the medicine.'
            ),
            notification_type='medicine',
            priority='medium',
            category=f'med_prescription_{patient.id}_{name}'
        )
        messages.success(
            request,
            f'Medicine "{name}" prescribed — {qty} doses. Patient must confirm purchase before stock is available.',
        )
        return redirect(f'/dashboard/doctor/patient/{patient.id}/')

    return render(request, 'dashboard/patient/add_medicine.html', {
        'patients': patients,
        'quick_colors': QUICK_COLORS,
        'quick_color_values': [c[0] for c in QUICK_COLORS],
    })


@login_required
def mark_medicine(request, med_id):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=400)

    med = get_object_or_404(Medicine, id=med_id)
    user = request.user
    action = request.POST.get('action', 'taken')
    patient_ctx = _resolve_patient_for_reminders(request)

    if patient_ctx and med.patient_id != patient_ctx.id and user.role not in ('doctor', 'caregiver'):
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    if user.role == 'patient' and med.patient != user:
        return JsonResponse({'success': False, 'error': 'Not your medicine'}, status=403)

    if user.role == 'caregiver' and patient_ctx and med.patient_id != patient_ctx.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    today = date.today()
    now = timezone.localtime()
    explicit_log = None
    best_slot_dt = None

    if action == 'taken':
        from apps.medicines.inventory_service import medicine_has_stock, is_not_purchased_yet
        if not medicine_has_stock(med):
            msg = (
                'Medicine not purchased yet. Add a purchase before marking doses.'
                if is_not_purchased_yet(med)
                else 'Out of stock. Refill medicine before marking doses.'
            )
            return JsonResponse({'success': False, 'error': 'no_stock', 'message': msg})

        log_id_param = request.POST.get('log_id')
        if log_id_param:
            try:
                explicit_log = MedicineLog.objects.get(id=int(log_id_param), medicine=med)
            except (MedicineLog.DoesNotExist, TypeError, ValueError):
                return JsonResponse({
                    'success': False, 'error': 'invalid_log',
                    'message': 'Dose record not found.',
                })
            if explicit_log.status == 'taken':
                return JsonResponse({
                    'success': False, 'error': 'already_taken',
                    'message': (
                        'This scheduled dose has already been taken. '
                        'Taking excess dosage may be harmful.'
                    ),
                })
            if explicit_log.status == 'missed':
                return JsonResponse({
                    'success': False, 'error': 'dose_expired',
                    'message': 'Dose window expired.',
                })
            if explicit_log.status != 'scheduled':
                return JsonResponse({
                    'success': False, 'error': 'dose_closed',
                    'message': f'Dose already marked as {explicit_log.status}.',
                })
            from apps.medicines.reminder_engine import (
                REMINDER_WINDOW_SECONDS, parse_slot_datetime, seconds_until_slot,
            )
            diff = seconds_until_slot(explicit_log.scheduled_time, now)
            if diff > 0:
                from apps.medicines.medicine_schedule_utils import attach_medicine_dose_ui
                attach_medicine_dose_ui(med, med.patient, today, now)
                return JsonResponse({
                    'success': False,
                    'error': 'not_time',
                    'message': med.status_message or 'Medicine is not yet due.',
                    'next_dose': med.next_slot_display,
                })
            if diff < -REMINDER_WINDOW_SECONDS:
                return JsonResponse({
                    'success': False, 'error': 'dose_expired',
                    'message': 'Dose window expired.',
                })
            best_slot_dt = explicit_log.scheduled_time

        if best_slot_dt is None and user.role == 'patient' and med.time_slots:
            from apps.medicines.medicine_schedule_utils import (
                find_due_slot_for_marking, attach_medicine_dose_ui,
            )
            slot_dt, slot_info = find_due_slot_for_marking(med, med.patient, today, now)
            if not slot_dt:
                attach_medicine_dose_ui(med, med.patient, today, now)
                msg = med.status_message or 'Medicine is not yet due.'
                return JsonResponse({
                    'success': False,
                    'error': 'not_time',
                    'message': msg,
                    'next_dose': med.next_slot_display,
                })
            best_slot_dt = slot_dt
        elif best_slot_dt is None and user.role == 'patient':
            from apps.medicines.medicine_schedule_utils import attach_medicine_dose_ui
            attach_medicine_dose_ui(med, med.patient, today, now)
            return JsonResponse({
                'success': False,
                'error': 'not_time',
                'message': med.status_message or 'No scheduled dose window is open.',
                'next_dose': med.next_slot_display,
            })
        elif best_slot_dt is None and med.time_slots:
            from apps.medicines.medicine_schedule_utils import find_due_slot_for_marking
            slot_dt, _ = find_due_slot_for_marking(med, med.patient, today, now)
            best_slot_dt = slot_dt or now
        elif best_slot_dt is None:
            best_slot_dt = now
    else:
        best_slot_dt = now
        if med.time_slots:
            from apps.medicines.medicine_schedule_utils import find_due_slot_for_marking
            slot_dt, _ = find_due_slot_for_marking(med, med.patient, today, now)
            if slot_dt:
                best_slot_dt = slot_dt
            else:
                from apps.medicines.reminder_engine import parse_slot_datetime
                best_diff = float('inf')
                for slot_str in med.time_slots:
                    try:
                        slot_dt = parse_slot_datetime(today, slot_str)
                        diff = abs((slot_dt - now).total_seconds())
                        if diff < best_diff:
                            best_diff = diff
                            best_slot_dt = slot_dt
                    except Exception:
                        pass

    if action != 'taken' and med.time_slots and best_slot_dt == now:
        from apps.medicines.reminder_engine import parse_slot_datetime
        best_diff = float('inf')
        for slot_str in med.time_slots:
            try:
                slot_dt = parse_slot_datetime(today, slot_str)
                diff = abs((slot_dt - now).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_slot_dt = slot_dt
            except Exception:
                pass

    if action == 'taken':
        overdose_msg = (
            'This scheduled dose has already been taken. '
            'Taking excess dosage may be harmful.'
        )
        completing_pending = False
        if explicit_log and explicit_log.status == 'scheduled':
            completing_pending = True
        elif best_slot_dt:
            completing_pending = MedicineLog.objects.filter(
                medicine=med, scheduled_time=best_slot_dt, status='scheduled',
            ).exists()
        if not completing_pending:
            if best_slot_dt and MedicineLog.objects.filter(
                medicine=med, scheduled_time=best_slot_dt, status='taken',
            ).exists():
                return JsonResponse({
                    'success': False, 'error': 'already_taken', 'message': overdose_msg,
                })
            if best_slot_dt and MedicineLog.objects.filter(
                medicine=med, scheduled_time=best_slot_dt, status='missed',
            ).exists():
                return JsonResponse({
                    'success': False, 'error': 'dose_expired',
                    'message': 'Dose window expired.',
                })
            from apps.medicines.medicine_schedule_utils import find_due_slot_for_marking
            pending_dt, _ = find_due_slot_for_marking(med, med.patient, today, now)
            if not pending_dt:
                today_taken = med.logs.filter(
                    scheduled_time__date=today, status='taken',
                ).count()
                if today_taken >= med.max_daily_doses:
                    return JsonResponse({
                        'success': False,
                        'error': 'overdose',
                        'message': overdose_msg,
                        'max_doses': med.max_daily_doses,
                        'taken_today': today_taken,
                    })

    log = explicit_log
    if not log:
        log = MedicineLog.objects.filter(
            medicine=med, scheduled_time=best_slot_dt, status='scheduled',
        ).first()
    if log:
        log.status = action
        log.marked_by = user
        log.taken_at = now if action == 'taken' else None
        log.snoozed_until = None
        log.save(update_fields=['status', 'marked_by', 'taken_at', 'snoozed_until'])
    else:
        log = MedicineLog.objects.create(
            medicine=med, patient=med.patient,
            marked_by=user, scheduled_time=best_slot_dt,
            taken_at=now if action == 'taken' else None,
            status=action,
        )

    from apps.medicines.reminder_tracking_service import complete_tracking
    complete_tracking('medicine', log.id)

    from apps.medicines.inventory_service import (
        deduct_on_taken, record_inventory_event, should_show_low_stock_alert, mark_low_stock_alert_sent,
    )

    if action == 'taken':
        deduct_on_taken(med, log=log, marked_by=user)
        if should_show_low_stock_alert(med):
            notify_user(
                user=med.patient,
                title='⚠️ Medicine Stock Running Low',
                message=f'"{med.name}" — only {med.stock_quantity} doses remaining. Please refill to avoid treatment interruption.',
                notification_type='alert',
                priority='high',
                category=f'med_stock_low_{med.id}',
            )
            mark_low_stock_alert_sent(med)
        elif med.is_low_stock:
            notify_user(
                user=med.patient,
                title='⚠️ Low Medicine Stock',
                message=f'"{med.name}" is running low ({med.stock_quantity} remaining).',
                notification_type='alert',
                priority='medium',
                category=f'med_stock_low_{med.id}',
            )
    elif action in ('missed', 'skipped'):
        record_inventory_event(
            med, action, medicine_log=log, created_by=user,
            notes=f'Marked as {action}',
        )

    # Notifications to caregiver/doctor
    from apps.caregiver.models import CaregiverPatientAssignment
    for ca in CaregiverPatientAssignment.objects.filter(patient=med.patient, status='active'):
        Notification.objects.create(user=ca.caregiver, title=f'💊 {action.title()}', message=f'{med.patient.get_full_name()} marked {med.name} as {action}.', notification_type='medicine')

    from apps.connections.models import DoctorPatientConnection
    conn = DoctorPatientConnection.objects.filter(patient=med.patient, status='accepted').first()
    if conn and action == 'missed':
        Notification.objects.create(user=conn.doctor, title=f'⚠️ Missed Medicine', message=f'{med.patient.get_full_name()} missed {med.name}.', notification_type='alert')

    calculate_risk_score(med.patient, trigger_medicine=med)

    remove_notifications(
        user=med.patient,
        category_contains=f'med_reminder_{med.id}'
    )

    from apps.medicines.medicine_schedule_utils import attach_medicine_dose_ui
    attach_medicine_dose_ui(med, med.patient, today, now)

    return JsonResponse({
        'success': True,
        'medicine_name': med.name,
        'stock': med.stock_quantity,
        'prescribed_quantity': med.prescribed_quantity,
        'status': action,
        'taken_today': med.logs.filter(scheduled_time__date=today, status='taken').count(),
        'max_doses': med.max_daily_doses,
        'suggest_pharmacy': med.is_low_stock or med.is_critical_stock,
        'refill_required': med.refill_required,
        'low_stock': med.is_critical_stock,
        'dose_button_state': med.dose_button_state,
        'dose_status': getattr(med, 'medicine_status', None),
        'next_dose': med.next_dose_display or med.next_slot_display,
        'status_message': med.status_message,
        'is_overdue': getattr(med, 'is_overdue', False),
        'overdue_minutes': getattr(med, 'overdue_minutes', 0),
    })


@login_required
def medicine_detail(request, med_id):
    med = get_object_or_404(Medicine, id=med_id)
    user = request.user

    # Authorization
    authorized = False
    if user == med.patient:
        authorized = True
    elif user.role == 'doctor':
        from apps.connections.models import DoctorPatientConnection
        if DoctorPatientConnection.objects.filter(doctor=user, patient=med.patient, status='accepted').exists():
            authorized = True
    elif user.role == 'caregiver':
        from apps.caregiver.models import CaregiverPatientAssignment
        if CaregiverPatientAssignment.objects.filter(caregiver=user, patient=med.patient, status='active').exists():
            authorized = True

    if not authorized:
        messages.error(request, 'Unauthorized to view this medicine.')
        return redirect('/medicines/')

    all_logs = med.logs.order_by('-scheduled_time')

    taken = all_logs.filter(status='taken').count()
    missed = all_logs.filter(status='missed').count()
    total = all_logs.count()

    logs = all_logs[:30]
    adherence = int(taken / total * 100) if total > 0 else 0

    # Weekly chart data
    today = date.today()
    chart_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        dl = med.logs.filter(scheduled_time__date=d)
        chart_data.append({
            'day': d.strftime('%a'),
            'taken': dl.filter(status='taken').count(),
            'missed': dl.filter(status='missed').count(),
        })

    return render(request, 'dashboard/patient/medicine_detail.html', {
        'medicine': med, 'logs': logs,
        'taken': taken, 'missed': missed,
        'total': total, 'adherence': adherence,
        'chart_data': json.dumps(chart_data),
        'is_patient': user.role == 'patient',
    })


@login_required
def delete_medicine(request, med_id):
    if request.user.role == 'patient':
        messages.error(request, 'Patients cannot delete medicines.')
        return redirect('/medicines/')

    if request.method != 'POST':
        return redirect('/medicines/')

    med = get_object_or_404(Medicine, id=med_id)
    user = request.user
    if user.role == 'doctor' and med.prescribed_by == user:
        med.is_active = False
        med.deleted_by = user
        med.deleted_at = timezone.now()
        med.deletion_reason = request.POST.get('deletion_reason', '').strip()
        med.save(update_fields=['is_active', 'deleted_by', 'deleted_at', 'deletion_reason', 'updated_at'])
        notify_user(
            med.patient,
            title='Medicine Removed',
            message=f'Dr. {user.get_full_name()} removed "{med.name}" from your prescription.',
            notification_type='medicine',
            priority='medium',
            category=f'med_removed_{med.id}',
        )
        messages.success(request, f'Medicine "{med.name}" archived successfully.')
        return redirect(f'/dashboard/doctor/patient/{med.patient.id}/')
    messages.error(request, 'Unauthorized to remove this medicine.')
    return redirect('/medicines/')


@login_required
def activity_list(request):
    subject, caregiver_mode = _resolve_subject_user(request)
    user = request.user
    today = date.today()

    if subject.role == 'patient' or caregiver_mode:
        patient = subject
        schedule_summaries = get_active_schedule_summaries(
            patient, user=request.user, caregiver_mode=caregiver_mode, request=request,
        )
        sections = categorize_activity_logs(patient, today)
    elif user.role == 'doctor':
        from apps.connections.models import DoctorPatientConnection
        patient_ids = DoctorPatientConnection.objects.filter(
            doctor=user, status='accepted',
        ).values_list('patient_id', flat=True)
        schedule_summaries = []
        sections = {'today': [], 'upcoming': [], 'missed': [], 'completed': [], 'compliance': {'compliance_pct': 0}}
    elif user.role == 'caregiver':
        from apps.caregiver.models import CaregiverPatientAssignment
        patient_ids = CaregiverPatientAssignment.objects.filter(
            caregiver=user, status='active',
        ).values_list('patient_id', flat=True)
        schedule_summaries = []
        sections = {'today': [], 'upcoming': [], 'missed': [], 'completed': [], 'compliance': {'compliance_pct': 0}}
    else:
        schedule_summaries = []
        sections = {'today': [], 'upcoming': [], 'missed': [], 'completed': [], 'compliance': {'compliance_pct': 0}}

    return render(request, 'dashboard/patient/activities.html', {
        'schedule_summaries': schedule_summaries,
        'sections': sections,
        'caregiver_mode': caregiver_mode,
        'today': today,
    })


@login_required
def activity_detail(request, activity_id):
    activity = get_object_or_404(Activity.objects.select_related(
        'patient', 'prescribed_by', 'logged_by',
    ), id=activity_id)
    user = request.user
    subject, caregiver_mode = _resolve_subject_user(request)

    allowed = False
    if user.role == 'doctor':
        allowed = DoctorPatientConnection.objects.filter(
            doctor=user, patient=activity.patient, status='accepted',
        ).exists()
    elif subject and (subject.id == activity.patient_id or caregiver_mode):
        allowed = True
    elif user.role == 'patient' and user.id == activity.patient_id:
        allowed = True

    if not allowed:
        messages.error(request, 'Access denied.')
        return redirect('activity_list')

    detail = get_activity_detail_bundle(activity)
    can_manage = user_can_manage_activity(user, activity, caregiver_mode, request)
    patient_profile_url = None
    if user.role == 'doctor':
        from django.urls import reverse
        patient_profile_url = reverse('patient_detail', args=[activity.patient_id])
    return render(request, 'dashboard/patient/activity_detail.html', {
        'detail': detail,
        'caregiver_mode': caregiver_mode,
        'can_manage': can_manage,
        'patient_profile_url': patient_profile_url,
    })


@login_required
def edit_activity(request, activity_id):
    activity = get_object_or_404(Activity.objects.select_related('patient', 'prescribed_by'), id=activity_id)
    user = request.user
    subject, caregiver_mode = _resolve_subject_user(request)

    if not user_can_manage_activity(user, activity, caregiver_mode, request):
        messages.error(request, 'You do not have permission to edit this activity.')
        return redirect('activity_list')

    today = date.today()
    is_doctor_mode = user.role == 'doctor'
    is_recurring = activity.schedule_type != 'one_time'

    if request.method == 'POST':
        data = parse_activity_form(request.POST, is_doctor=is_doctor_mode)
        reason = request.POST.get('edit_reason', '').strip()
        scope = request.POST.get('edit_scope', 'entire')
        log_id = request.POST.get('log_id') or None
        effective_date = request.POST.get('effective_date') or str(today)

        if not data['title'] or not data['time_slots']:
            messages.error(request, 'Title and at least one time slot are required.')
            return redirect('edit_activity', activity_id=activity.id)
        if is_recurring and scope == 'occurrence':
            if not log_id:
                log_today = ActivityLog.objects.filter(
                    activity=activity, scheduled_time__date=today, status='scheduled',
                ).first()
                log_id = log_today.id if log_today else None
            if not log_id:
                messages.error(request, 'No scheduled occurrence found for today.')
                return redirect('edit_activity', activity_id=activity.id)

        ok, msg, redirect_id = edit_activity_record(
            activity, user, data, scope, reason or 'Schedule updated',
            log_id=log_id, effective_date=effective_date,
        )
        if ok:
            calculate_risk_score(activity.patient)
            messages.success(request, msg)
            return redirect('activity_detail', activity_id=redirect_id or activity.id)
        messages.error(request, msg)
        return redirect('edit_activity', activity_id=activity.id)

    return render(request, 'dashboard/patient/edit_activity.html', {
        'activity': activity,
        'caregiver_mode': caregiver_mode,
        'is_doctor_mode': is_doctor_mode,
        'is_recurring': is_recurring,
        'today': today,
        'weekdays': Activity.WEEKDAY_KEYS,
        'schedule_types': Activity.SCHEDULE_TYPES,
        'activity_types': Activity.ACTIVITY_TYPES,
        'doctor_priority_choices': Activity.DOCTOR_PRIORITY_CHOICES,
    })


@login_required
def delete_activity(request, activity_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    activity = get_object_or_404(Activity, id=activity_id)
    user = request.user
    _, caregiver_mode = _resolve_subject_user(request)

    if not user_can_manage_activity(user, activity, caregiver_mode, request):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    reason = request.POST.get('reason', '').strip()
    if not reason:
        return JsonResponse({'success': False, 'error': 'Reason is required'})

    scope = request.POST.get('scope', 'entire')
    log_id = request.POST.get('log_id') or None
    effective_date = request.POST.get('effective_date') or str(date.today())

    ok, msg = delete_activity_record(
        activity, user, scope, reason,
        log_id=log_id, effective_date=effective_date,
    )
    if not ok:
        return JsonResponse({'success': False, 'error': msg})

    calculate_risk_score(activity.patient)
    redirect_url = reverse('activity_list')
    if user.role == 'doctor':
        redirect_url = request.POST.get('redirect') or reverse(
            'patient_detail', args=[activity.patient_id],
        )
    return JsonResponse({'success': True, 'message': msg, 'redirect': redirect_url})


def _log_activity_redirect(is_doctor_mode, patient=None):
    if is_doctor_mode and patient:
        return redirect(f"{reverse('log_activity')}?patient_id={patient.id}")
    return redirect('log_activity')


@login_required
def log_activity(request):
    subject, caregiver_mode = _resolve_subject_user(request)
    user = request.user
    is_doctor_mode = False
    patient = None

    if user.role == 'doctor':
        patient_id = request.GET.get('patient_id') or request.POST.get('patient_id')
        if not patient_id:
            messages.error(request, 'Select a patient to schedule an activity.')
            return redirect('doctor_dashboard')
        patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
        if not DoctorPatientConnection.objects.filter(
            doctor=user, patient=patient, status='accepted',
        ).exists():
            messages.error(request, 'You are not connected with this patient.')
            return redirect('doctor_dashboard')
        is_doctor_mode = True
    elif subject.role == 'patient' or caregiver_mode:
        patient = subject
    else:
        messages.error(request, 'Only patients or caregivers in patient mode can schedule activities.')
        return redirect('/dashboard/')

    today = date.today()

    if request.method == 'POST':
        act_type = request.POST.get('activity_type', 'other')
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        duration = request.POST.get('duration_minutes')
        schedule_type = request.POST.get('schedule_type', 'one_time')
        start_date = request.POST.get('start_date') or str(today)
        end_date = request.POST.get('end_date') or None
        no_end_date = request.POST.get('no_end_date') == '1'
        time_slots = request.POST.getlist('time_slots')
        repeat_days = request.POST.getlist('repeat_days')
        doctor_priority = request.POST.get('doctor_priority', '').strip() if is_doctor_mode else None
        severity = resolve_activity_severity(act_type, doctor_priority=doctor_priority or None)

        if not title or not duration:
            messages.error(request, 'Title and duration are required.')
            return _log_activity_redirect(is_doctor_mode, patient)
        if not time_slots:
            messages.error(request, 'Add at least one scheduled time.')
            return _log_activity_redirect(is_doctor_mode, patient)
        if schedule_type in ('weekly', 'custom') and not repeat_days:
            messages.error(request, 'Select at least one day for weekly/custom schedule.')
            return _log_activity_redirect(is_doctor_mode, patient)

        activity = Activity.objects.create(
            patient=patient,
            prescribed_by=user if is_doctor_mode else None,
            logged_by=user,
            activity_type=act_type,
            title=title,
            description=description,
            duration_minutes=int(duration),
            schedule_type=schedule_type,
            start_date=start_date,
            end_date=None if no_end_date else end_date,
            time_slots=time_slots,
            repeat_days=repeat_days,
            severity=severity,
            requires_proof=request.POST.get('requires_proof') == '1',
            reminders_enabled=request.POST.get('reminders_enabled', '1') == '1',
            is_active=True,
        )
        log_audit(activity, user, 'created', changes={'title': {'new': title}})

        if caregiver_mode:
            from apps.caregiver.access import log_caregiver_action, get_active_assignment
            assignment = get_active_assignment(request, patient)
            if assignment:
                log_caregiver_action(assignment, request.user, 'activity_scheduled', title)

        notify_user(
            user=patient,
            title='📋 Activity Scheduled',
            message=f'"{title}" has been scheduled starting {start_date}.',
            notification_type='activity',
            priority='medium',
            category=f'act_sched_{activity.id}',
        )

        messages.success(request, f'Activity "{title}" scheduled successfully.')
        if is_doctor_mode:
            return redirect('patient_detail', patient_id=patient.id)
        return redirect('activity_list')

    return render(request, 'dashboard/patient/log_activity.html', {
        'caregiver_mode': caregiver_mode,
        'is_doctor_mode': is_doctor_mode,
        'patient': patient,
        'today': today,
        'weekdays': Activity.WEEKDAY_KEYS,
        'schedule_types': Activity.SCHEDULE_TYPES,
        'activity_types': Activity.ACTIVITY_TYPES,
        'doctor_priority_choices': Activity.DOCTOR_PRIORITY_CHOICES,
    })


def _resolve_patient_for_reminders(request):
    subject, caregiver_mode = _resolve_subject_user(request)
    if subject.role == 'patient' or caregiver_mode:
        return subject
    if request.user.role == 'patient':
        return request.user
    return None


@login_required
def activity_reminder_status(request):
    patient = _resolve_patient_for_reminders(request)
    if not patient:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    reminders = get_patient_activity_reminders(patient)
    for r in reminders:
        if r['popup_due']:
            notify_user(
                user=patient,
                title='⏰ Activity Reminder',
                message=(
                    f"Time for your scheduled activity: {r['title']} "
                    f"({r['duration_minutes']} min) · {r['time_display']}"
                ),
                notification_type='activity',
                priority='high',
                category=f"act_rem_popup_{r['log_id']}_{r.get('reminder_count', 0)}",
                related_id=r['log_id'],
            )

    next_item = next(
        (r for r in reminders if not r['taken'] and r['status'] not in ('missed', 'skipped')),
        None,
    )
    return JsonResponse({'reminders': reminders, 'next': next_item})


@login_required
def start_activity_session(request, log_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    log = get_object_or_404(ActivityLog.objects.select_related('activity'), id=log_id)
    patient = _resolve_patient_for_reminders(request)
    if not patient or log.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    if log.status not in ('scheduled', 'in_progress'):
        return JsonResponse({'success': False, 'error': 'Activity already completed or missed'})

    now = timezone.localtime()
    from apps.medicines.reminder_engine import seconds_until_slot
    diff = seconds_until_slot(log.scheduled_time, now)
    if log.status == 'scheduled' and diff > 0:
        return JsonResponse({
            'success': False,
            'error': 'early',
            'message': 'Activity cannot start before the scheduled time.',
            'seconds_until': diff,
        })

    start_proof = request.FILES.get('start_proof')
    if not start_proof:
        return JsonResponse({
            'success': False,
            'error': 'proof_required',
            'message': 'Please upload proof before starting your activity.',
        })

    if log.status == 'scheduled':
        log.status = 'in_progress'
        log.started_at = now
        log.start_proof_upload = start_proof
        log.snoozed_until = None
        log.marked_by = request.user
        log.save(update_fields=['status', 'started_at', 'start_proof_upload', 'snoozed_until', 'marked_by'])
        from apps.medicines.reminder_tracking_service import complete_tracking
        complete_tracking('activity', log.id)

    remove_notifications(user=patient, category_contains=f'act_rem_popup_{log.id}')

    return JsonResponse({
        'success': True,
        'redirect': reverse('activity_session', args=[log.id]),
    })


@login_required
def activity_session(request, log_id):
    log = get_object_or_404(ActivityLog.objects.select_related('activity'), id=log_id)
    patient = _resolve_patient_for_reminders(request)
    if not patient or log.patient_id != patient.id:
        return redirect('activity_list')
    if log.status in ('missed', 'completed', 'skipped'):
        return redirect('activity_list')

    now = timezone.localtime()
    local_scheduled = timezone.localtime(log.scheduled_time)
    from apps.medicines.reminder_engine import seconds_until_slot
    diff = seconds_until_slot(log.scheduled_time, now)
    phase = 'active' if log.status == 'in_progress' else 'ready'
    started_local = timezone.localtime(log.started_at) if log.started_at else None
    duration_seconds = (log.activity.duration_minutes or 1) * 60

    return render(request, 'dashboard/patient/activity_session.html', {
        'log': log,
        'activity': log.activity,
        'caregiver_mode': _resolve_subject_user(request)[1],
        'phase': phase,
        'scheduled_time_display': local_scheduled.strftime('%I:%M %p').lstrip('0'),
        'scheduled_time_iso': local_scheduled.isoformat(),
        'started_at_iso': started_local.isoformat() if started_local else '',
        'can_start_now': log.status == 'scheduled' and diff <= 0,
        'duration_seconds': duration_seconds,
        'started_at_display': started_local.strftime('%I:%M %p').lstrip('0') if started_local else '',
    })


@login_required
def complete_activity_session(request, log_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    log = get_object_or_404(ActivityLog.objects.select_related('activity'), id=log_id)
    patient = _resolve_patient_for_reminders(request)
    if not patient or log.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    if log.status != 'in_progress':
        return JsonResponse({'success': False, 'error': 'Start the activity first'})

    if not log.can_complete:
        remaining = log.remaining_seconds
        return JsonResponse({
            'success': False,
            'error': 'timer',
            'message': 'Complete the activity duration to enable completion.',
            'remaining_seconds': remaining,
        })

    proof = request.FILES.get('proof_upload')
    if not proof:
        return JsonResponse({
            'success': False,
            'error': 'proof_required',
            'message': 'Please upload proof to finish your activity.',
        })

    now = timezone.localtime()
    notes = request.POST.get('notes', '')
    log.status = 'completed'
    log.completed_at = now
    log.notes = notes
    log.snoozed_until = None
    log.marked_by = request.user
    log.duration_completed_minutes = log.activity.duration_minutes
    log.proof_upload = proof
    log.save()

    from apps.medicines.reminder_tracking_service import complete_tracking
    complete_tracking('activity', log.id)

    if log.activity.schedule_type == 'one_time':
        log.activity.is_active = False
        log.activity.save(update_fields=['is_active'])

    remove_notifications(user=patient, category_contains=f'act_rem_popup_{log.id}')
    calculate_risk_score(patient)

    if caregiver_mode := _resolve_subject_user(request)[1]:
        from apps.caregiver.access import log_caregiver_action, get_active_assignment
        assignment = get_active_assignment(request, patient)
        if assignment:
            log_caregiver_action(assignment, request.user, 'activity_completed', log.activity.title)

    return JsonResponse({'success': True, 'message': 'Activity completed successfully!'})


@login_required
def snooze_activity_reminder(request, log_id):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    log = get_object_or_404(ActivityLog, id=log_id)
    patient = _resolve_patient_for_reminders(request)
    if not patient or log.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    if log.status not in ('scheduled',):
        return JsonResponse({'success': False, 'error': 'Activity already started or completed'})

    from apps.medicines.reminder_tracking_service import (
        ensure_tracking, snooze_tracking, sync_log_from_tracking, tracking_payload,
    )
    tracking = ensure_tracking(patient, 'activity', log.id, log.scheduled_time)
    snooze_tracking(tracking)
    sync_log_from_tracking(log, tracking)

    notify_user(
        user=patient,
        title='⏰ Activity Reminder',
        message=f"Reminder: complete \"{log.activity.title}\" scheduled at "
                f"{timezone.localtime(log.scheduled_time).strftime('%I:%M %p').lstrip('0')}",
        notification_type='activity',
        priority='medium',
        category=f"act_rem_snooze_{log.id}_{log.reminder_count}",
        related_id=log.id,
    )
    return JsonResponse({
        'success': True,
        'message': 'Reminder snoozed for 10 minutes',
        **tracking_payload(tracking),
    })


@login_required
def ack_activity_reminder(request, log_id):
    """Record popup shown and schedule next retry in 10 minutes."""
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    log = get_object_or_404(ActivityLog, id=log_id)
    patient = _resolve_patient_for_reminders(request)
    if not patient or log.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    if log.status != 'scheduled':
        return JsonResponse({'success': True, 'suppressed': True})

    from apps.medicines.reminder_tracking_service import (
        ensure_tracking, record_popup_displayed, sync_log_from_tracking, tracking_payload,
    )
    tracking = ensure_tracking(patient, 'activity', log.id, log.scheduled_time)
    if tracking.last_popup_at:
        elapsed = (timezone.localtime() - timezone.localtime(tracking.last_popup_at)).total_seconds()
        if elapsed < 30:
            return JsonResponse({'success': True, 'already_recorded': True, **tracking_payload(tracking)})
    record_popup_displayed(tracking, ignored=True)
    sync_log_from_tracking(log, tracking)
    return JsonResponse({'success': True, **tracking_payload(tracking)})


@login_required
def skip_activity_session(request, log_id):
    """Mark activity as not completed / skipped after session."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    log = get_object_or_404(ActivityLog.objects.select_related('activity'), id=log_id)
    patient = _resolve_patient_for_reminders(request)
    if not patient or log.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    reason = request.POST.get('reason', 'Not completed by patient').strip()
    log.status = 'skipped'
    log.missed_reason = reason
    log.save(update_fields=['status', 'missed_reason'])
    remove_notifications(user=patient, category_contains=f'act_rem_popup_{log.id}')
    calculate_risk_score(patient)
    return JsonResponse({'success': True, 'redirect': reverse('activity_list')})


@login_required
def daily_health_check(request):
    subject, caregiver_mode = _resolve_subject_user(request)
    if subject.role != 'patient' and not caregiver_mode:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    patient = subject

    if request.method == 'POST':
        feeling = request.POST.get('feeling')
        notes = request.POST.get('notes', '')
        if not feeling:
            return JsonResponse({'success': False, 'error': 'Feeling is required'})

        today = date.today()
        existing = DailyHealthCheck.objects.filter(patient=patient, checked_at__date=today).first()
        if existing:
            return JsonResponse({'success': False, 'error': 'already_checked', 'feeling': existing.feeling})

        check = DailyHealthCheck.objects.create(patient=patient, feeling=feeling, notes=notes)

        if feeling == 'not_good':
            recent_bad = DailyHealthCheck.objects.filter(
                patient=patient, feeling='not_good',
                checked_at__date__gte=today - timedelta(days=3)
            ).count()
            if recent_bad >= 2:
                conn = DoctorPatientConnection.objects.filter(patient=patient, status='accepted').first()
                if conn:
                    Notification.objects.create(
                        user=conn.doctor,
                        title='⚠️ Patient Reporting Poor Health',
                        message=f'{patient.get_full_name()} has reported feeling "Not Good" {recent_bad} times in the last 3 days.',
                        notification_type='alert'
                    )
                from apps.family.utils import send_family_alert
                send_family_alert(
                    patient=patient,
                    alert_type='health',
                    title='⚠️ Health Alert',
                    message=f'{patient.get_full_name()} has reported feeling "Not Good" multiple times recently. Please check in with them.',
                    priority='high'
                )

        return JsonResponse({'success': True, 'feeling': feeling})

    today = date.today()
    check = DailyHealthCheck.objects.filter(patient=patient, checked_at__date=today).first()
    if check:
        return JsonResponse({'checked': True, 'feeling': check.feeling})
    return JsonResponse({'checked': False})


@login_required
def health_analytics(request):
    subject, caregiver_mode = _resolve_subject_user(request)
    if subject.role != 'patient' and not caregiver_mode:
        return redirect('/dashboard/')

    user = subject

    today = date.today()

    # 30-day adherence
    monthly_data = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        dl = MedicineLog.objects.filter(patient=user, scheduled_time__date=d)
        total = dl.count()
        taken = dl.filter(status='taken').count()
        monthly_data.append({
            'date': d.strftime('%b %d'),
            'taken': taken,
            'missed': dl.filter(status='missed').count(),
            'pct': int(taken / total * 100) if total > 0 else 0,
        })

    # Weekly adherence
    weekly_data = monthly_data[-7:]

    # Health checks history
    health_checks = DailyHealthCheck.objects.filter(patient=user).order_by('-checked_at')[:30]

    # Risk scores history
    risk = calculate_risk_score(user)
    from apps.medicines.risk_calculation_service import RiskCalculationService
    risk_trend = RiskCalculationService.get_trend(user, days=7)

    # Miss analysis per medicine
    medicines = Medicine.objects.filter(patient=user, is_active=True)
    med_stats = []
    for m in medicines:
        logs = m.logs.filter(scheduled_time__date__gte=today - timedelta(days=30))
        total = logs.count()
        taken = logs.filter(status='taken').count()
        missed = logs.filter(status='missed').count()
        med_stats.append({
            'name': m.name,
            'taken': taken,
            'missed': missed,
            'total': total,
            'adherence': int(taken / total * 100) if total > 0 else 0,
        })

    context = {
        'monthly_data': json.dumps(monthly_data),
        'weekly_data': json.dumps(weekly_data),
        'health_checks': health_checks,
        'risk': risk,
        'risk_trend': json.dumps(risk_trend),
        'med_stats': json.dumps(med_stats),
        'today': today,
    }
    return render(request, 'dashboard/patient/health_analytics.html', context)


@login_required
def family_contacts(request):
    subject, caregiver_mode = _resolve_subject_user(request)
    if subject.role != 'patient' and not caregiver_mode:
        return redirect('/dashboard/')

    user = subject
    contacts = FamilyContact.objects.filter(patient=user)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            name = request.POST.get('name', '').strip()
            phone = request.POST.get('phone', '').strip()
            email = request.POST.get('email', '').strip()
            relation = request.POST.get('relation', 'other')
            if name:
                FamilyContact.objects.create(
                    patient=user, name=name, phone=phone,
                    email=email, relation=relation
                )
                messages.success(request, f'Family contact "{name}" added.')
        elif action == 'delete':
            contact_id = request.POST.get('contact_id')
            FamilyContact.objects.filter(id=contact_id, patient=user).delete()
            messages.success(request, 'Contact removed.')
        return redirect('/medicines/family-contacts/')

    return render(request, 'dashboard/patient/family_contacts.html', {'contacts': contacts})


@login_required
def medicine_reminder_status(request):
    """API: today's medicine schedule — popups are time-based only (server-driven)."""
    patient = _resolve_patient_for_reminders(request)
    if not patient:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    from apps.medicines.medicine_reminder_utils import get_patient_medicine_reminders

    reminders = get_patient_medicine_reminders(patient)
    next_dose = next((r for r in reminders if not r['taken'] and not r.get('missed')), None)
    return JsonResponse({'reminders': reminders, 'next_dose': next_dose})


@login_required
def snooze_medicine_reminder(request, log_id):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    log = get_object_or_404(MedicineLog, id=log_id)
    patient = _resolve_patient_for_reminders(request)
    if not patient or log.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    if log.status != 'scheduled':
        return JsonResponse({'success': False, 'error': 'Dose already resolved'})

    from apps.medicines.reminder_tracking_service import (
        ensure_tracking, snooze_tracking, sync_log_from_tracking, tracking_payload,
    )
    tracking = ensure_tracking(patient, 'medicine', log.id, log.scheduled_time)
    snooze_tracking(tracking)
    sync_log_from_tracking(log, tracking)
    from apps.medicines.inventory_service import record_inventory_event
    record_inventory_event(
        log.medicine, 'remind_later', medicine_log=log, created_by=request.user,
        notes='Patient chose Remind Me Later',
    )
    return JsonResponse({
        'success': True,
        'message': 'Reminder snoozed for 10 minutes',
        **tracking_payload(tracking),
    })


@login_required
def ack_medicine_reminder(request, log_id):
    """Record popup shown and schedule next retry in 10 minutes."""
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    log = get_object_or_404(MedicineLog, id=log_id)
    patient = _resolve_patient_for_reminders(request)
    if not patient or log.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    if log.status != 'scheduled':
        return JsonResponse({'success': True, 'suppressed': True})

    from apps.medicines.reminder_tracking_service import (
        ensure_tracking, record_popup_displayed, sync_log_from_tracking, tracking_payload,
    )
    tracking = ensure_tracking(patient, 'medicine', log.id, log.scheduled_time)
    if tracking.last_popup_at:
        elapsed = (timezone.localtime() - timezone.localtime(tracking.last_popup_at)).total_seconds()
        if elapsed < 30:
            return JsonResponse({'success': True, 'already_recorded': True, **tracking_payload(tracking)})
    record_popup_displayed(tracking, ignored=True)
    sync_log_from_tracking(log, tracking)
    from apps.medicines.inventory_service import record_inventory_event
    record_inventory_event(
        log.medicine, 'delayed', medicine_log=log, created_by=request.user,
        notes='Reminder popup acknowledged — retry scheduled',
    )
    return JsonResponse({'success': True, **tracking_payload(tracking)})


@login_required
def health_risk_alerts(request):
    """JSON feed of health risk escalation alerts for linked roles."""
    from apps.medicines.risk_alert_service import get_alerts_for_user
    from django.utils.timesince import timesince

    alerts = get_alerts_for_user(request.user, limit=30)
    data = []
    for a in alerts:
        data.append({
            'id': a.id,
            'patient_id': a.patient_id,
            'patient_name': a.patient.get_full_name(),
            'patient_phone': a.patient_phone,
            'emergency_phone': a.emergency_phone,
            'escalation_level': a.escalation_level,
            'severity': a.severity_label,
            'risk_level': a.risk_level,
            'risk_score': a.risk_score,
            'medicines_missed': a.medicines_missed_count,
            'consecutive_misses': a.consecutive_misses,
            'reason': a.reason,
            'message': a.message,
            'doctor_name': a.doctor_name,
            'recipients_count': len(a.recipients or []),
            'sent_at': timezone.localtime(a.sent_at).strftime('%I:%M %p').lstrip('0'),
            'time_ago': f'{timesince(a.sent_at)} ago',
        })
    return JsonResponse({'success': True, 'alerts': data})


@login_required
def edit_medicine(request, med_id):
    """Doctors (original prescriber) or Authorized Caregivers can edit medicines."""
    med = get_object_or_404(Medicine, id=med_id)
    user = request.user

    # Permission Check
    authorized = False
    if user.role == 'doctor' and med.prescribed_by == user:
        authorized = True
    elif user.role == 'caregiver':
        from apps.caregiver.models import CaregiverPatientAssignment
        if CaregiverPatientAssignment.objects.filter(caregiver=user, patient=med.patient, status='active', can_manage_appointments=True).exists():
            authorized = True

    if not authorized:
        messages.error(request, 'Unauthorized to edit this medicine.')
        return redirect(user.get_dashboard_url())

    if request.method == 'POST':
        med.name = request.POST.get('name', med.name).strip()
        med.dosage = request.POST.get('dosage', med.dosage).strip()
        med.frequency = request.POST.get('frequency', med.frequency)
        med.time_slots = request.POST.getlist('time_slots')
        med.start_date = request.POST.get('start_date', med.start_date)
        med.end_date = request.POST.get('end_date') or med.end_date
        med.instructions = request.POST.get('instructions', med.instructions).strip()
        med.stock_quantity = int(request.POST.get('stock_quantity', med.stock_quantity))
        from apps.medicines.inventory_service import parse_low_stock_alert_at
        med.critical_stock_threshold = parse_low_stock_alert_at(
            request.POST.get('low_stock_alert_at'),
            default=med.critical_stock_threshold or 3,
        )
        med.low_stock_threshold = max(med.low_stock_threshold, med.critical_stock_threshold + 2)
        med.expiry_date = request.POST.get('expiry_date') or med.expiry_date
        med.color = normalize_medicine_color(
            request.POST.get('color', med.color),
            med.color,
            request.POST.get('custom_color', ''),
        )
        med.save()
        messages.success(request, f'Medicine "{med.name}" updated successfully.')
        if user.role == 'doctor':
            return redirect(f'/dashboard/doctor/patient/{med.patient.id}/')
        return redirect(f'/dashboard/caregiver/patient/{med.patient.id}/')

    return render(request, 'dashboard/doctor/edit_medicine.html', {
        'medicine': med,
        'quick_colors': QUICK_COLORS,
        'quick_color_values': [c[0] for c in QUICK_COLORS],
        'time_slots_json': json.dumps(med.time_slots or []),
    })


@login_required
def deactivate_medicine(request, med_id):
    """Only doctors can deactivate medicines."""
    med = get_object_or_404(Medicine, id=med_id)
    if request.user.role != 'doctor' or med.prescribed_by != request.user:
        messages.error(request, 'Unauthorized to deactivate this medicine.')
        return redirect('/dashboard/doctor/')

    med.is_active = False
    med.prescription_status = 'stopped'
    med.save(update_fields=['is_active', 'prescription_status', 'updated_at'])
    messages.success(request, f'Medicine "{med.name}" has been deactivated.')
    return redirect(f'/dashboard/doctor/patient/{med.patient.id}/')


@login_required
def inventory_alerts(request):
    """JSON feed of low-stock medicines needing popup (patient/caregiver)."""
    patient, _ = _resolve_subject_user(request)
    if not patient or patient.role != 'patient':
        return JsonResponse({'success': True, 'alerts': []})
    from apps.medicines.inventory_service import get_patient_inventory_alerts
    alerts = get_patient_inventory_alerts(patient)
    return JsonResponse({'success': True, 'alerts': alerts})


@login_required
def dismiss_inventory_alert(request, med_id):
    """Remind me later for low stock — respects cooldown."""
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    med = get_object_or_404(Medicine, id=med_id)
    patient, _ = _resolve_subject_user(request)
    if not patient or med.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    from apps.medicines.inventory_service import mark_low_stock_alert_sent, snooze_low_stock_alert, suppress_low_stock_for_refill
    import json
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        body = {}
    action = body.get('action') or request.POST.get('action', 'snooze')

    if action == 'refill_opened':
        suppress_low_stock_for_refill(med)
        return JsonResponse({'success': True, 'message': 'Refill opened — reminder suppressed'})
    if action == 'shown':
        mark_low_stock_alert_sent(med)
        return JsonResponse({'success': True, 'message': 'Alert recorded'})
    if action == 'snooze':
        minutes = int(body.get('minutes') or request.POST.get('minutes') or 360)
        snooze_low_stock_alert(med, minutes=minutes)
        return JsonResponse({'success': True, 'message': f'Reminder snoozed for {minutes} minutes'})

    mark_low_stock_alert_sent(med)
    return JsonResponse({'success': True, 'message': 'Reminder snoozed for 24 hours'})


@login_required
def refill_medicine(request, med_id):
    """Patient/caregiver refill workflow."""
    med = get_object_or_404(Medicine, id=med_id, is_active=True)
    patient, caregiver_mode = _resolve_subject_user(request)
    user = request.user

    if patient and med.patient_id == patient.id:
        pass
    elif user.role == 'doctor':
        conn = DoctorPatientConnection.objects.filter(
            doctor=user, patient=med.patient, status='accepted',
        ).exists()
        if not conn:
            messages.error(request, 'Unauthorized.')
            return redirect(user.get_dashboard_url())
        patient = med.patient
    else:
        messages.error(request, 'Unauthorized.')
        return redirect(user.get_dashboard_url())

    from apps.medicines.inventory_service import suppress_low_stock_for_refill
    if request.method == 'GET':
        suppress_low_stock_for_refill(med)

    if request.method == 'POST':
        try:
            qty = int(request.POST.get('quantity_purchased', 0))
        except (TypeError, ValueError):
            qty = 0
        if qty < 1:
            messages.error(request, 'Please enter a valid quantity purchased.')
            return render(request, 'dashboard/patient/refill_medicine.html', {'medicine': med, 'patient': patient})

        purchase_date = request.POST.get('purchase_date') or date.today().isoformat()
        from apps.medicines.inventory_service import process_refill, get_partial_refill_status
        refill = process_refill(
            med,
            quantity_purchased=qty,
            purchase_date=purchase_date,
            pharmacy_name=request.POST.get('pharmacy_name', '').strip(),
            notes=request.POST.get('notes', '').strip(),
            recorded_by=user,
        )
        partial = get_partial_refill_status(med)
        notify_user(
            med.patient,
            title='✅ Medicine Refilled',
            message=f'"{med.name}" stock updated to {med.stock_quantity} units.',
            notification_type='medicine',
            priority='medium',
            category=f'med_refill_{med.id}',
        )
        if partial['is_partial']:
            conn = DoctorPatientConnection.objects.filter(patient=med.patient, status='accepted').first()
            if conn:
                notify_user(
                    conn.doctor,
                    title='⚠️ Partial Refill Detected',
                    message=(
                        f'{med.patient.get_full_name()} purchased only {partial["purchased"]}/'
                        f'{partial["prescribed"]} units of {med.name}. Treatment interruption possible.'
                    ),
                    notification_type='alert',
                    priority='high',
                    category=f'med_partial_refill_{med.id}',
                )
            messages.warning(
                request,
                f'Partial refill recorded ({partial["purchased"]}/{partial["prescribed"]} units). '
                'Your doctor has been notified.',
            )
        else:
            messages.success(request, f'Refill saved. New stock: {med.stock_quantity} units.')
        calculate_risk_score(med.patient, trigger_medicine=med)
        return redirect('/medicines/')

    return render(request, 'dashboard/patient/refill_medicine.html', {
        'medicine': med,
        'patient': patient,
        'caregiver_mode': caregiver_mode,
    })


@login_required
def quick_refill_medicine(request, med_id):
    """AJAX quick refill from dashboard low-stock alert."""
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)

    med = get_object_or_404(Medicine, id=med_id, is_active=True)
    patient, _ = _resolve_subject_user(request)
    user = request.user
    if not patient or med.patient_id != patient.id:
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    import json
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        body = {}

    try:
        qty = int(body.get('quantity_purchased') or request.POST.get('quantity_purchased', 0))
    except (TypeError, ValueError):
        qty = 0
    if qty < 1:
        return JsonResponse({'success': False, 'error': 'Please enter a valid quantity.'})

    purchase_date = body.get('purchase_date') or request.POST.get('purchase_date') or date.today().isoformat()

    from apps.medicines.inventory_service import process_refill, get_partial_refill_status
    refill = process_refill(
        med,
        quantity_purchased=qty,
        purchase_date=purchase_date,
        pharmacy_name=(body.get('pharmacy_name') or request.POST.get('pharmacy_name') or '').strip(),
        notes=(body.get('notes') or request.POST.get('notes') or '').strip(),
        recorded_by=user,
    )
    partial = get_partial_refill_status(med)

    notify_user(
        med.patient,
        title='✅ Stock Updated Successfully',
        message=f'"{med.name}" — new stock: {med.stock_quantity} doses.',
        notification_type='medicine',
        priority='medium',
        category=f'med_refill_{med.id}',
    )

    conn = DoctorPatientConnection.objects.filter(patient=med.patient, status='accepted').first()
    if conn:
        notify_user(
            conn.doctor,
            title='💊 Medicine Refilled',
            message=(
                f'{med.patient.get_full_name()} refilled {med.name} '
                f'(+{qty} doses). New stock: {med.stock_quantity}.'
            ),
            notification_type='medicine',
            priority='medium',
            category=f'med_refill_doctor_{med.id}',
        )
        if partial['is_partial']:
            notify_user(
                conn.doctor,
                title='⚠️ Partial Refill Detected',
                message=(
                    f'{med.patient.get_full_name()} purchased only {partial["purchased"]}/'
                    f'{partial["prescribed"]} units of {med.name}.'
                ),
                notification_type='alert',
                priority='high',
                category=f'med_partial_refill_{med.id}',
            )

    calculate_risk_score(med.patient, trigger_medicine=med)

    return JsonResponse({
        'success': True,
        'medicine_name': med.name,
        'new_stock': med.stock_quantity,
        'quantity_added': qty,
        'purchased_total': partial['purchased'],
        'prescribed_total': partial['prescribed'],
        'remaining_required': partial['shortfall'],
        'refill_id': refill.id,
        'partial_refill': partial['is_partial'],
    })
