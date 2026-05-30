"""
Healthcare risk calculation — delegates to DynamicRiskEngineService for
real-time predictive analysis; retains report/trend helpers.
"""
from datetime import date, timedelta

from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.appointments.models import Appointment
from apps.medicines.models import (
    Activity,
    ActivityLog,
    DailyHealthCheck,
    Medicine,
    MedicineLog,
    RiskScore,
    RiskScoreHistory,
)
from apps.medicines.dynamic_risk_engine import (
    DynamicRiskEngineService,
    RISK_TYPE_LABELS,
    WEIGHTS,
    _classify_medicine,
    _consecutive_misses,
    _disease_context,
    _patient_profile,
)

# Re-export labels for templates/imports


def _is_critical_medicine(med):
    return _classify_medicine(med) in ('heart', 'kidney', 'diabetes', 'hypertension')


class RiskCalculationService:
    """Central healthcare risk engine — call calculate() on medicine/activity/appointment events."""

    @classmethod
    def calculate(cls, patient, trigger_medicine=None, persist=True):
        result = DynamicRiskEngineService.analyze(patient, trigger_medicine=trigger_medicine)

        if not persist:
            return result

        risk, _ = RiskScore.objects.update_or_create(
            patient=patient if not isinstance(patient, int) else CustomUser.objects.get(pk=patient),
            defaults={
                'score': result['score'],
                'level': result['level'],
                'factors': result['factors'],
                'risk_types': result['risk_types'],
                'component_scores': result['component_scores'],
                'reasons': result['reasons'],
                'health_impacts': result['health_impacts'],
                'recommended_actions': result['recommended_actions'],
                'level_message': result['level_message'],
                'disease_context': result['disease_context'],
                'dynamic_analysis': result['dynamic_analysis'],
            },
        )

        RiskScoreHistory.objects.create(
            patient=risk.patient,
            score=result['score'],
            level=result['level'],
            risk_types=result['risk_types'],
            component_scores=result['component_scores'],
            reasons=result['reasons'],
            dynamic_snapshot=result['dynamic_analysis'],
        )

        from apps.medicines.risk_alert_service import process_risk_escalation
        process_risk_escalation(risk.patient, risk, trigger_medicine=trigger_medicine)

        from apps.profiles.profile_bridge import sync_patient_risk_cache
        sync_patient_risk_cache(risk.patient)

        return risk

    @staticmethod
    def _level_from_score(score):
        if score <= 25:
            return 'low'
        if score <= 50:
            return 'medium'
        if score <= 75:
            return 'high'
        return 'critical'

    @classmethod
    def get_trend(cls, patient, days=7):
        since = timezone.now() - timedelta(days=days)
        history = RiskScoreHistory.objects.filter(
            patient=patient, recorded_at__gte=since,
        ).order_by('recorded_at')
        return [
            {
                'date': h.recorded_at.strftime('%Y-%m-%d'),
                'score': h.score,
                'level': h.level,
            }
            for h in history
        ]

    @classmethod
    def build_report_payload(cls, patient, doctor=None, days=30):
        """Collect comprehensive data for PDF/HTML reports."""
        today = date.today()
        since = today - timedelta(days=days)
        risk = RiskScore.objects.filter(patient=patient).first()
        if not risk or (timezone.now() - risk.recorded_at).total_seconds() > 3600:
            risk = cls.calculate(patient, persist=True)

        profile = _patient_profile(patient)
        disease = _disease_context(profile)
        dynamic = risk.dynamic_analysis or {}

        medicines_detail = []
        inventory_summaries = []
        refill_gaps = []
        for med in Medicine.objects.filter(patient=patient, is_active=True):
            from apps.medicines.inventory_service import (
                get_medicine_inventory_summary, get_partial_refill_status, get_refill_gap_days,
            )
            inv = get_medicine_inventory_summary(med)
            inventory_summaries.append(inv)
            gap = get_refill_gap_days(med)
            if gap >= 1:
                refill_gaps.append({'medicine': med.name, 'gap_days': gap})
            partial = get_partial_refill_status(med)
            logs = med.logs.filter(scheduled_time__date__gte=since)
            taken = logs.filter(status='taken').count()
            missed = logs.filter(status='missed').count()
            total = logs.count()
            last_missed = logs.filter(status='missed').order_by('-scheduled_time').first()
            consecutive = _consecutive_misses(logs)
            missed_dates = [
                l.scheduled_time.strftime('%b %d') for l in logs.filter(status='missed').order_by('scheduled_time')[:10]
            ]
            slots = ', '.join(med.time_slots[:3]) if med.time_slots else '—'
            medicines_detail.append({
                'name': med.name,
                'dosage': med.dosage,
                'scheduled': slots,
                'taken': taken,
                'missed': missed,
                'total': total,
                'adherence_pct': int(taken / total * 100) if total else 100,
                'repeated_misses': consecutive >= 2,
                'consecutive_misses': consecutive,
                'last_missed': last_missed.scheduled_time.strftime('%b %d, %I:%M %p') if last_missed else '—',
                'missed_dates': missed_dates,
                'is_critical': _is_critical_medicine(med),
                'category': _classify_medicine(med),
                'prescribed_quantity': inv['prescribed_quantity'],
                'remaining_stock': inv['remaining_stock'],
                'partial_refill': partial['is_partial'],
                'refill_gap_days': gap,
                'refill_status': 'Partial' if partial['is_partial'] else ('Full' if partial['purchased'] else 'None'),
            })

        activities_detail = []
        for act in Activity.objects.filter(patient=patient, is_active=True):
            logs = ActivityLog.objects.filter(activity=act, scheduled_time__date__gte=since)
            completed = logs.filter(status='completed').count()
            missed = logs.filter(status='missed').count()
            total = logs.count()
            times = ', '.join(act.time_slots[:2]) if act.time_slots else '—'
            activities_detail.append({
                'title': act.title,
                'type': act.get_activity_type_display(),
                'schedule': f'{act.get_schedule_type_display()} · {times}',
                'completed': completed,
                'missed': missed,
                'total': total,
                'adherence_pct': int(completed / total * 100) if total else 100,
            })

        apts = Appointment.objects.filter(patient=patient, appointment_date__gte=since)
        apt_stats = {
            'booked': apts.count(),
            'completed': apts.filter(status__in=('completed', 'ended')).count(),
            'cancelled': apts.filter(status__in=('cancelled', 'cancelled_by_patient', 'cancelled_by_doctor')).count(),
            'missed': apts.filter(status__in=('timeout', 'rejected', 'doctor_unavailable')).count(),
        }

        checks = DailyHealthCheck.objects.filter(patient=patient, checked_at__date__gte=since)
        questionnaire = {
            'total_checks': checks.count(),
            'not_good': checks.filter(feeling='not_good').count(),
            'symptoms': {},
        }
        for c in checks:
            for s in (c.symptoms or []):
                key = str(s)
                questionnaire['symptoms'][key] = questionnaire['symptoms'].get(key, 0) + 1

        trend_7 = cls.get_trend(patient, days=7)
        trend_30 = cls.get_trend(patient, days=30)

        week_adherence = []
        for i in range(4, -1, -1):
            ws = today - timedelta(weeks=i + 1)
            we = today - timedelta(weeks=i)
            wl = MedicineLog.objects.filter(patient=patient, scheduled_time__date__gte=ws, scheduled_time__date__lt=we)
            wt = wl.filter(status='taken').count()
            wn = wl.count()
            week_adherence.append({'week': f'W{i + 1}', 'pct': int(wt / wn * 100) if wn else 0})

        repeated_issues = []
        for m in medicines_detail:
            if m['missed']:
                repeated_issues.append(
                    f"Missed {m['name']}: {m['missed']} times"
                    + (f" ({m['consecutive_misses']} consecutive)" if m['consecutive_misses'] >= 2 else '')
                    + (f" — dates: {', '.join(m['missed_dates'][:5])}" if m.get('missed_dates') else '')
                )
            if m.get('partial_refill'):
                repeated_issues.append(
                    f"Partial refill {m['name']}: {m['remaining_stock']}/{m['prescribed_quantity']} remaining supply"
                )
            if m.get('refill_gap_days', 0) >= 2:
                repeated_issues.append(f"No refill gap {m['name']}: {m['refill_gap_days']} days without stock")
        for a in activities_detail:
            if a['missed'] >= 2:
                repeated_issues.append(f"{a['title']} skipped: {a['missed']} times")

        from apps.caregiver.models import CaregiverPatientAssignment
        health_consequence = dynamic.get('health_consequence')
        caregiver_status = (
            'Assigned' if CaregiverPatientAssignment.objects.filter(patient=patient, status='active').exists()
            else 'None'
        )

        return {
            'patient': {
                'name': patient.get_full_name(),
                'id': patient.unique_id,
                'phone': patient.phone,
                'conditions': disease['conditions'],
                'primary_diagnosis': profile.primary_diagnosis if profile else '',
            },
            'doctor': doctor.get_full_name() if doctor else '',
            'risk': {
                'score': risk.score,
                'level': risk.level,
                'types': risk.risk_type_labels if hasattr(risk, 'risk_type_labels') else [],
                'reasons': risk.reasons or [],
                'impacts': risk.health_impacts or [],
                'actions': risk.recommended_actions or [],
                'components': risk.component_scores or {},
                'why_increased': dynamic.get('why_risk_increased', risk.reasons or []),
                'predictions': dynamic.get('predictions', risk.health_impacts or []),
                'prediction_summary': dynamic.get('prediction_summary', ''),
                'medicine_insights': dynamic.get('medicine_insights', []),
                'refill_insights': dynamic.get('refill_insights', []),
                'health_consequence': health_consequence,
                'weighted_points': dynamic.get('weighted_points', 0),
                'repeated_issues': repeated_issues,
            },
            'medicines': medicines_detail,
            'inventory': inventory_summaries,
            'refill_gaps': refill_gaps,
            'activities': activities_detail,
            'appointments': apt_stats,
            'questionnaire': questionnaire,
            'trend_7': trend_7,
            'trend_30': trend_30,
            'week_adherence': week_adherence,
            'period_days': days,
            'activity_adherence_pct': int(
                sum(a['completed'] for a in activities_detail) /
                max(1, sum(a['total'] for a in activities_detail)) * 100
            ) if activities_detail else 100,
            'appointment_adherence_pct': int(
                apt_stats['completed'] / max(1, apt_stats['booked']) * 100
            ),
            'caregiver_status': caregiver_status,
        }
