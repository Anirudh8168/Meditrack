"""Automatic health-risk escalation alerts for patients with poor medicine adherence."""
from datetime import date, timedelta

from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

from apps.connections.models import DoctorPatientConnection
from apps.caregiver.models import CaregiverPatientAssignment
from apps.family.models import FamilyMember
from apps.notifications.utils import notify_user

from apps.medicines.models import (
    MedicineLog,
    FamilyContact,
    HealthRiskAlert,
    MissedAlertLog,
)

HIGH_RISK_COOLDOWN_HOURS = 6
CAREGIVER_ALERT_COOLDOWN_HOURS = 12


def count_consecutive_medicine_misses(patient, limit=25):
    """Most recent consecutive missed doses (stops at first taken dose)."""
    logs = MedicineLog.objects.filter(
        patient=patient,
        status__in=('missed', 'taken'),
    ).order_by('-scheduled_time')[:limit]
    count = 0
    for log in logs:
        if log.status == 'missed':
            count += 1
        else:
            break
    return count


def get_medicine_adherence_stats(patient):
    today = date.today()
    now = timezone.now()
    recent_misses = MedicineLog.objects.filter(
        patient=patient,
        status='missed',
        scheduled_time__date__gte=today - timedelta(days=3),
    ).count()
    consecutive = count_consecutive_medicine_misses(patient)
    taken_24h = MedicineLog.objects.filter(
        patient=patient,
        status='taken',
        scheduled_time__gte=now - timedelta(hours=24),
    ).exists()
    refill_gap_days = 0
    from apps.medicines.models import Medicine
    from apps.medicines.inventory_service import get_refill_gap_days
    for med in Medicine.objects.filter(patient=patient, is_active=True):
        refill_gap_days = max(refill_gap_days, get_refill_gap_days(med))
    return {
        'recent_misses_3d': recent_misses,
        'consecutive_misses': consecutive,
        'taken_in_24h': taken_24h,
        'refill_gap_days': refill_gap_days,
    }


def determine_escalation_level(risk, stats):
    """Return escalation level 1–4 from dynamic engine + adherence stats."""
    dynamic_level = 1
    if risk and getattr(risk, 'dynamic_analysis', None):
        dynamic_level = (risk.dynamic_analysis or {}).get('escalation_level', 1)
    elif risk and hasattr(risk, 'escalation_level'):
        dynamic_level = risk.escalation_level

    adherence_level = 1
    if risk and risk.level == 'critical' and not stats['taken_in_24h']:
        if stats['consecutive_misses'] >= 2 or stats['recent_misses_3d'] >= 3:
            adherence_level = 4
    elif risk and risk.level in ('high', 'critical'):
        if stats['consecutive_misses'] >= 2 or stats['recent_misses_3d'] >= 2:
            adherence_level = 3
    elif stats['consecutive_misses'] >= 3 or stats['recent_misses_3d'] >= 3:
        adherence_level = 2
    elif stats.get('refill_gap_days', 0) >= 3:
        adherence_level = max(adherence_level, 3)

    return max(dynamic_level, adherence_level)


def _cooldown_active(patient, escalation_level, hours):
    cutoff = timezone.now() - timedelta(hours=hours)
    return HealthRiskAlert.objects.filter(
        patient=patient,
        escalation_level=escalation_level,
        sent_at__gte=cutoff,
    ).exists()


def _doctor_for_patient(patient):
    conn = DoctorPatientConnection.objects.filter(
        patient=patient, status='accepted',
    ).select_related('doctor').first()
    return conn.doctor if conn else None


def _build_alert_content(patient, risk, stats, level):
    doctor = _doctor_for_patient(patient)
    doctor_name = doctor.get_full_name() if doctor else ''
    risk_label = risk.get_level_display()
    missed = stats['recent_misses_3d']
    consecutive = stats['consecutive_misses']
    dynamic = getattr(risk, 'dynamic_analysis', None) or {}
    insights = dynamic.get('medicine_insights') or []
    top_insight = insights[0] if insights else None
    prediction = dynamic.get('prediction_summary') or (
        (risk.health_impacts or ['Health deterioration risk'])[0]
    )

    if level == 4:
        title = '🚨 EMERGENCY ATTENTION REQUIRED'
        reason = dynamic.get('why_risk_increased', ['Critical repeated negligence'])[0]
        message = (
            f'{patient.get_full_name()} requires immediate attention.\n\n'
            f'Predicted risk: {prediction}\n'
            f'{consecutive} consecutive medicine misses · Risk: {risk_label} ({risk.score}/100)'
        )
    elif level == 3:
        title = '🚨 HIGH RISK PATIENT ALERT'
        reason = 'Health deterioration risk detected'
        if top_insight:
            reason = f"{top_insight.get('category_label', 'Medication')} negligence — {top_insight.get('medicine', 'medicine')}"
        message = (
            f'Patient: {patient.get_full_name()}\n\n'
            f'Predicted Risk: {prediction}\n\n'
        )
        if top_insight:
            message += (
                f"Missed: {top_insight.get('medicine')} — "
                f"{top_insight.get('consecutive_misses', consecutive)} continuous times\n"
            )
        message += (
            f'Risk: {risk_label} ({risk.score}/100)\n'
            f'Suggested intervention: Schedule follow-up and review adherence.'
        )
    else:
        title = '⚠️ Medication Adherence Alert'
        reason = dynamic.get('why_risk_increased', ['Multiple consecutive medicine misses'])[0]
        message = (
            f'{patient.get_full_name()} has missed {missed} medicines recently '
            f'({consecutive} consecutive).\n\nPossible impact: {prediction}'
        )

    if doctor_name:
        message += f'\n\nAssigned doctor: Dr. {doctor_name}'

    return {
        'title': title,
        'reason': reason,
        'message': message,
        'doctor_name': doctor_name,
        'risk_label': risk_label,
        'prediction': prediction,
        'top_insight': top_insight,
    }


def _notify_registered(user, title, message, priority, category, related_id):
    if not user:
        return
    notify_user(
        user=user,
        title=title,
        message=message,
        notification_type='alert',
        priority=priority,
        category=category,
        related_id=related_id,
    )


def _email_contact(email, subject, body):
    if not email:
        return
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=True,
        )
    except Exception:
        pass


def _dispatch_to_recipients(patient, content, level, alert_id):
    """Notify linked family, emergency contacts, caregivers, and doctor."""
    recipients = []
    priority = 'high' if level < 4 else 'high'
    category = f'health_risk_l{level}_{patient.id}'
    title = content['title']
    message = content['message']
    body_prefix = f'Alert for {patient.get_full_name()}:\n\n'

    if level >= 3:
        for member in FamilyMember.objects.filter(patient=patient):
            role = 'emergency_contact' if member.is_emergency_contact else 'family'
            entry = {'role': role, 'name': member.name, 'user_id': member.user_id}
            recipients.append(entry)
            if member.user:
                _notify_registered(
                    member.user, title, message, priority,
                    f'{category}_{member.user_id}', alert_id,
                )
            if member.email:
                _email_contact(member.email, title, body_prefix + message)

        for contact in FamilyContact.objects.filter(patient=patient, notify_on_missed=True):
            entry = {'role': 'emergency_contact', 'name': contact.name, 'phone': contact.phone}
            recipients.append(entry)
            if contact.email:
                _email_contact(contact.email, title, body_prefix + message)

    if level >= 2:
        for assignment in CaregiverPatientAssignment.objects.filter(
            patient=patient, status='active',
        ).select_related('caregiver'):
            cg = assignment.caregiver
            recipients.append({'role': 'caregiver', 'name': cg.get_full_name(), 'user_id': cg.id})
            _notify_registered(
                cg, title, message, priority,
                f'{category}_cg_{cg.id}', alert_id,
            )

    if level >= 3:
        doctor = _doctor_for_patient(patient)
        if doctor:
            recipients.append({'role': 'doctor', 'name': doctor.get_full_name(), 'user_id': doctor.id})
            _notify_registered(
                doctor, title, message, priority,
                f'{category}_dr_{doctor.id}', alert_id,
            )

    return recipients


def process_risk_escalation(patient, risk, trigger_medicine=None):
    """
    Evaluate adherence + risk and dispatch tiered alerts.
    Level 1: patient reminders only (no action here).
    Level 2: caregiver (12h cooldown).
    Level 3: family + emergency + caregiver + doctor (6h cooldown).
    Level 4: emergency escalation (6h cooldown).
    """
    if not risk:
        return None

    stats = get_medicine_adherence_stats(patient)
    level = determine_escalation_level(risk, stats)

    if level == 1:
        dynamic = getattr(risk, 'dynamic_analysis', None) or {}
        msg = dynamic.get('patient_message') or risk.level_message
        if risk.level in ('medium', 'high', 'critical') and msg:
            if not _cooldown_active(patient, 1, 12):
                notify_user(
                    user=patient,
                    title='⚠ Health Risk Update',
                    message=msg,
                    notification_type='alert',
                    priority='medium' if risk.level == 'medium' else 'high',
                    category=f'health_risk_l1_{patient.id}',
                    related_id=patient.id,
                )
        return None

    if level == 2 and _cooldown_active(patient, 2, CAREGIVER_ALERT_COOLDOWN_HOURS):
        return None
    if level == 3 and _cooldown_active(patient, 3, HIGH_RISK_COOLDOWN_HOURS):
        return None
    if level == 4 and _cooldown_active(patient, 4, HIGH_RISK_COOLDOWN_HOURS):
        return None

    content = _build_alert_content(patient, risk, stats, level)

    alert = HealthRiskAlert.objects.create(
        patient=patient,
        risk_score=risk.score,
        risk_level=risk.level,
        escalation_level=level,
        medicines_missed_count=stats['recent_misses_3d'],
        consecutive_misses=stats['consecutive_misses'],
        reason=content['reason'],
        message=content['message'],
        doctor_name=content['doctor_name'],
        trigger_medicine=trigger_medicine,
        recipients=[],
    )

    recipients = _dispatch_to_recipients(patient, content, level, alert.id)
    alert.recipients = recipients
    alert.save(update_fields=['recipients'])

    MissedAlertLog.objects.create(
        patient=patient,
        medicine=trigger_medicine,
        alert_type=f'health_risk_l{level}',
        sent_to=recipients,
        message=content['message'],
    )

    return alert


def get_alerts_for_user(user, limit=20):
    """Alerts visible to family/caregiver/doctor linked to patients."""
    from apps.accounts.models import CustomUser

    patient_ids = set()

    if user.role == 'family':
        patient_ids.update(
            FamilyMember.objects.filter(user=user).values_list('patient_id', flat=True)
        )
    elif user.role == 'caregiver':
        patient_ids.update(
            CaregiverPatientAssignment.objects.filter(
                caregiver=user, status='active',
            ).values_list('patient_id', flat=True)
        )
    elif user.role == 'doctor':
        patient_ids.update(
            DoctorPatientConnection.objects.filter(
                doctor=user, status='accepted',
            ).values_list('patient_id', flat=True)
        )
    elif user.role == 'patient':
        patient_ids.add(user.id)

    if not patient_ids:
        return HealthRiskAlert.objects.none()

    return HealthRiskAlert.objects.filter(
        patient_id__in=patient_ids,
    ).select_related('patient', 'trigger_medicine').order_by('-sent_at')[:limit]
