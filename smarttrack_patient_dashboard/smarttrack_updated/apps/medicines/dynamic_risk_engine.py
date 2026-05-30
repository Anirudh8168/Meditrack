"""
Dynamic healthcare risk prediction engine.

Analyses rolling patient behaviour (7-day + 30-day), disease context,
medicine/activity/appointment patterns, and produces predictive outcomes
with escalation guidance — not static percentage-only scoring.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.appointments.models import Appointment
from apps.medicines.models import (
    Activity,
    ActivityLog,
    DailyHealthCheck,
    HealthRiskAlert,
    Medicine,
    MedicineLog,
    MissedAlertLog,
)

RECENT_WINDOW_DAYS = 7
BASELINE_WINDOW_DAYS = 30
RECENT_WEIGHT = 0.65
BASELINE_WEIGHT = 0.35

WEIGHTS = {
    'medicine': 0.30,
    'activity': 0.20,
    'appointment': 0.15,
    'health': 0.15,
    'emergency': 0.10,
    'negligence': 0.10,
}

RISK_POINT_WEIGHTS = {
    'missed_medicine': 10,
    'consecutive_miss': 25,
    'critical_medicine_miss': 50,
    'no_refill_gap': 35,
    'partial_refill': 20,
    'appointment_missed': 20,
    'activity_ignored': 10,
    'emergency_call': 40,
    'no_health_update': 15,
}

RISK_TYPE_LABELS = {
    'medication': 'Medication Risk',
    'physical': 'Physical Health Risk',
    'deterioration': 'Health Deterioration Risk',
    'appointment': 'Appointment Negligence Risk',
    'mental': 'Mental Health Risk',
    'lifestyle': 'Lifestyle Risk',
    'emergency': 'Emergency Risk',
    'high_risk': 'High-Risk Patient',
}

MED_CATEGORY_KEYWORDS = {
    'diabetes': ('insulin', 'metformin', 'glipizide', 'glyburide', 'sitagliptin', 'diabetes', 'sugar'),
    'hypertension': ('amlodipine', 'losartan', 'atenolol', 'telmesartan', 'bp', 'blood pressure', 'hypertension'),
    'heart': ('warfarin', 'aspirin', 'statin', 'clopidogrel', 'heart', 'cardiac', 'nitroglycerin', 'digoxin'),
    'kidney': ('dialysis', 'kidney', 'renal', 'furosemide', 'sevelamer'),
    'mental': ('sertraline', 'fluoxetine', 'escitalopram', 'anxiety', 'antidepressant', 'mental'),
}

DISEASE_RULES = {
    'diabetes': {
        'label': 'Diabetes',
        'medicine_priority': 'high',
        'consequences': {
            1: ['Temporary blood sugar fluctuation possible'],
            2: ['Blood sugar instability', 'Fatigue', 'Increased thirst'],
            3: ['Repeated sugar imbalance', 'Weakness', 'Dizziness'],
            5: ['Severe sugar imbalance', 'Vision issues', 'Dehydration', 'Emergency complication risk'],
        },
        'messages': {
            1: 'You missed your diabetes medicine. Please take it as soon as possible.',
            2: 'Repeated diabetes medicine negligence detected. Resume medicines immediately.',
            3: 'Your diabetes control may worsen if medicines continue to be missed.',
            5: 'Critical diabetes medicine negligence — seek medical guidance urgently.',
        },
    },
    'hypertension': {
        'label': 'High Blood Pressure',
        'medicine_priority': 'high',
        'consequences': {
            1: ['Mild BP fluctuation possible'],
            2: ['BP instability', 'Headache risk'],
            3: ['Blood pressure control may worsen', 'Dizziness', 'Headache'],
            5: ['Stroke risk elevation', 'Heart stress', 'Severe headache risk'],
        },
        'messages': {
            1: 'You missed your BP medicine. Take it promptly to maintain stable blood pressure.',
            2: 'Blood pressure control may worsen if medicines continue to be missed.',
            3: 'Repeated BP medicine misses — monitor blood pressure closely.',
            5: 'Critical BP medicine negligence — consult your doctor urgently.',
        },
    },
    'heart': {
        'label': 'Heart Disease',
        'medicine_priority': 'critical',
        'consequences': {
            1: ['Minor cardiac stress risk'],
            2: ['Irregular heartbeat risk', 'Chest discomfort possible'],
            3: ['Chest pain risk', 'Irregular heartbeat', 'Heart complication risk'],
            4: ['Serious cardiac complication risk', 'Emergency evaluation may be needed'],
        },
        'messages': {
            1: 'Heart medicine missed — take immediately.',
            2: 'Critical heart medicine repeatedly missed — do not skip doses.',
            3: 'Heart complication risk rising — consult doctor urgently.',
            4: 'Critical heart medicine negligence — seek urgent medical attention.',
        },
    },
    'kidney': {
        'label': 'Kidney Disease',
        'medicine_priority': 'critical',
        'consequences': {
            1: ['Reduced renal protection'],
            2: ['Toxin buildup risk', 'Fluid imbalance possible'],
            3: ['Kidney function stress', 'Swelling risk'],
            4: ['Emergency hospitalization risk', 'Severe fluid/toxin imbalance'],
        },
        'messages': {
            1: 'Kidney-related medicine missed — take as prescribed.',
            2: 'Kidney care compliance failing — resume treatment immediately.',
            3: 'Dialysis/medicine misses may cause serious complications.',
            4: 'Immediate medical attention recommended for kidney care failure.',
        },
    },
    'mental': {
        'label': 'Mental Health',
        'medicine_priority': 'medium',
        'consequences': {
            1: ['Mood fluctuation possible'],
            2: ['Anxiety or stress increase', 'Sleep disruption'],
            3: ['Mental health deterioration risk', 'Social withdrawal possible'],
        },
        'messages': {
            1: 'Mental health medicine missed — take when you can safely do so.',
            2: 'Repeated misses may affect mood stability — resume schedule.',
            3: 'Consider speaking with your doctor about adherence support.',
        },
    },
    'general': {
        'label': 'General Health',
        'medicine_priority': 'medium',
        'consequences': {
            1: ['Treatment effectiveness may reduce temporarily'],
            2: ['Symptoms may return or worsen'],
            3: ['Health recovery may stall', 'Fatigue and weakness possible'],
        },
        'messages': {
            1: 'You missed a scheduled medicine. Please take it as soon as possible.',
            2: 'Repeated medicine misses detected — resume your schedule.',
            3: 'Ongoing negligence may affect your recovery — consult your doctor.',
        },
    },
}

NOTIFY_TARGETS = {
    1: ['patient'],
    2: ['patient', 'caregiver'],
    3: ['patient', 'caregiver', 'doctor'],
    4: ['patient', 'caregiver', 'doctor', 'family', 'emergency_contact'],
}


def _patient_profile(patient):
    try:
        return patient.patient_profile
    except Exception:
        return None


def _disease_context(profile):
    if not profile:
        return {
            'has_diabetes': False, 'has_heart': False, 'has_kidney': False,
            'has_hypertension': False, 'has_mental': False,
            'conditions': [], 'multiplier': 1.0, 'primary': [],
        }
    text = ' '.join(filter(None, [
        profile.primary_diagnosis or '',
        profile.secondary_conditions or '',
        profile.chronic_diseases or '',
        profile.medical_history or '',
    ])).lower()
    diabetes = profile.diabetes not in ('', 'no', None) or any(
        k in text for k in ('diabetes', 'diabetic', 'sugar')
    )
    heart = any(k in text for k in ('heart', 'cardiac', 'cardio', 'coronary'))
    kidney = any(k in text for k in ('kidney', 'renal', 'dialysis'))
    hypertension = any(k in text for k in ('hypertension', 'blood pressure', ' bp '))
    mental = any(k in text for k in ('depression', 'anxiety', 'mental', 'psychiatric'))
    primary = []
    if diabetes:
        primary.append('diabetes')
    if hypertension:
        primary.append('hypertension')
    if heart:
        primary.append('heart')
    if kidney:
        primary.append('kidney')
    if mental:
        primary.append('mental')
    multiplier = 1.0
    if kidney:
        multiplier = max(multiplier, 1.35)
    if heart:
        multiplier = max(multiplier, 1.28)
    if diabetes:
        multiplier = max(multiplier, 1.20)
    if hypertension:
        multiplier = max(multiplier, 1.15)
    conditions = []
    for key in primary:
        conditions.append(DISEASE_RULES[key]['label'])
    if profile.primary_diagnosis and profile.primary_diagnosis not in conditions:
        conditions.insert(0, profile.primary_diagnosis[:80])
    return {
        'has_diabetes': diabetes,
        'has_heart': heart,
        'has_kidney': kidney,
        'has_hypertension': hypertension,
        'has_mental': mental,
        'conditions': conditions,
        'primary': primary or ['general'],
        'multiplier': multiplier,
    }


def _classify_medicine(med):
    name = (med.name or '').lower()
    for category, keywords in MED_CATEGORY_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return category
    return 'general'


def _consecutive_misses(logs_qs, limit=20):
    count = 0
    for log in logs_qs.order_by('-scheduled_time')[:limit]:
        if log.status == 'missed':
            count += 1
        elif log.status == 'taken':
            break
    return count


def _tier_for_count(count):
    if count >= 5:
        return 5
    if count >= 4:
        return 4
    if count >= 3:
        return 3
    if count >= 2:
        return 2
    return 1


def _pick_from_tier(mapping, count):
    tier = _tier_for_count(count)
    while tier >= 1:
        if tier in mapping:
            return mapping[tier]
        tier -= 1
    return list(mapping.values())[-1] if mapping else []


def _analyze_medicines(patient, since_recent, since_baseline, disease):
    insights = []
    reasons = []
    impacts = set()
    score_recent = 0
    score_baseline = 0
    worst_consecutive = 0
    worst_category = 'general'

    for med in Medicine.objects.filter(patient=patient, is_active=True):
        category = _classify_medicine(med)
        if category == 'general' and disease['primary']:
            for p in disease['primary']:
                if p in MED_CATEGORY_KEYWORDS:
                    category = p
                    break

        logs_recent = med.logs.filter(scheduled_time__date__gte=since_recent)
        logs_baseline = med.logs.filter(scheduled_time__date__gte=since_baseline)
        total_r = logs_recent.count()
        total_b = logs_baseline.count()
        if total_b == 0:
            continue

        missed_r = logs_recent.filter(status='missed').count()
        missed_b = logs_baseline.filter(status='missed').count()
        consecutive = _consecutive_misses(logs_baseline)
        rules = DISEASE_RULES.get(category, DISEASE_RULES['general'])
        priority = rules.get('medicine_priority', 'medium')

        if consecutive > worst_consecutive:
            worst_consecutive = consecutive
            worst_category = category

        mr = (missed_r / total_r) if total_r else 0
        mb = (missed_b / total_b) if total_b else 0
        med_score_r = min(100, int(mr * 100) + consecutive * 6)
        med_score_b = min(100, int(mb * 100) + consecutive * 4)
        if priority == 'critical' and consecutive >= 2:
            med_score_r = min(100, med_score_r + 25)
            med_score_b = min(100, med_score_b + 20)
        elif priority == 'high' and consecutive >= 3:
            med_score_r = min(100, med_score_r + 15)

        score_recent = max(score_recent, med_score_r)
        score_baseline = max(score_baseline, med_score_b)

        if consecutive >= 1 or missed_b:
            cons = _pick_from_tier(rules['consequences'], consecutive)
            msg = _pick_from_tier(rules['messages'], consecutive)
            if isinstance(cons, str):
                cons = [cons]
            if isinstance(msg, str):
                msg = msg
            insights.append({
                'medicine': med.name,
                'category': category,
                'category_label': rules['label'],
                'consecutive_misses': consecutive,
                'missed_30d': missed_b,
                'adherence_30d': int((total_b - missed_b) / total_b * 100),
                'predicted_risk': cons[0] if cons else 'Treatment effectiveness may reduce',
                'possible_complications': cons,
                'patient_message': msg,
                'severity': (
                    'critical' if consecutive >= 5 or (priority == 'critical' and consecutive >= 3)
                    else 'high' if consecutive >= 3 or (priority == 'critical' and consecutive >= 2)
                    else 'medium' if consecutive >= 2
                    else 'low'
                ),
                'priority': priority,
            })
            if consecutive >= 2:
                reasons.append(
                    f'Missed {med.name} {consecutive} consecutive time{"s" if consecutive != 1 else ""}'
                )
            elif missed_b:
                reasons.append(f'Missed {med.name} {missed_b} time{"s" if missed_b != 1 else ""} (30 days)')
            for c in cons:
                impacts.add(c)

    blended = int(score_recent * RECENT_WEIGHT + score_baseline * BASELINE_WEIGHT)
    return blended, reasons, list(impacts), insights, worst_consecutive, worst_category


def _analyze_refill_gaps(patient, disease):
    """Refill failure, partial refill, never-purchased, and zero-stock gap analysis."""
    from apps.medicines.inventory_service import (
        get_partial_refill_status, get_refill_gap_days, is_not_purchased_yet,
    )

    reasons = []
    impacts = set()
    insights = []
    score = 0
    weighted_points = 0

    for med in Medicine.objects.filter(patient=patient, is_active=True, prescription_status='active'):
        partial = get_partial_refill_status(med)
        category = _classify_medicine(med)
        rules = DISEASE_RULES.get(category, DISEASE_RULES['general'])

        if is_not_purchased_yet(med):
            weighted_points += 25
            score = min(100, score + 25)
            reasons.append(f'Patient has not purchased prescribed {med.name}')
            impacts.add(f'No medicine supply ({med.name})')
            cons = _pick_from_tier(rules['consequences'], 1)
            if isinstance(cons, str):
                cons = [cons]
            insights.append({
                'medicine': med.name,
                'type': 'never_purchased',
                'predicted_risk': cons[0] if cons else 'Treatment not started — medicine not purchased',
                'possible_complications': cons if isinstance(cons, list) else [cons],
            })
            continue

        gap = get_refill_gap_days(med)

        if gap >= 1:
            pts = min(RISK_POINT_WEIGHTS['no_refill_gap'], 10 + gap * 5)
            weighted_points += pts
            score = min(100, score + 15 + gap * 8)
            reasons.append(f'No refill for {med.name} — {gap} day{"s" if gap != 1 else ""} without stock')
            impacts.add(f'Treatment interruption risk ({med.name})')
            cons = _pick_from_tier(rules['consequences'], min(gap, 5))
            if isinstance(cons, str):
                cons = [cons]
            insights.append({
                'medicine': med.name,
                'refill_gap_days': gap,
                'type': 'refill_failure',
                'predicted_risk': cons[0] if cons else 'Treatment may be interrupted',
                'possible_complications': cons if isinstance(cons, list) else [cons],
            })

        if partial['is_partial']:
            weighted_points += RISK_POINT_WEIGHTS['partial_refill']
            score = min(100, score + 20)
            reasons.append(
                f'Partial refill: {med.name} — only {partial["purchased"]}/{partial["prescribed"]} units purchased'
            )
            impacts.add('Incomplete medicine supply — adherence at risk')

    return score, reasons, list(impacts), insights, weighted_points


def _compute_weighted_event_points(patient, since_baseline, med_insights, worst_consec, refill_points):
    """Dynamic point-based risk bump from discrete events."""
    points = refill_points
    logs = MedicineLog.objects.filter(
        patient=patient, scheduled_time__date__gte=since_baseline, status='missed',
    ).select_related('medicine')
    missed_count = logs.count()
    if missed_count:
        points += min(30, missed_count * RISK_POINT_WEIGHTS['missed_medicine'])

    if worst_consec >= 2:
        points += RISK_POINT_WEIGHTS['consecutive_miss'] * min(worst_consec - 1, 3)

    for ins in med_insights:
        if ins.get('priority') == 'critical' and ins.get('consecutive_misses', 0) >= 1:
            points += RISK_POINT_WEIGHTS['critical_medicine_miss']
            break

    missed_apts = Appointment.objects.filter(
        patient=patient,
        appointment_date__gte=since_baseline,
        status__in=('timeout', 'rejected', 'doctor_unavailable', 'no_show'),
    ).count()
    if missed_apts:
        points += min(40, missed_apts * RISK_POINT_WEIGHTS['appointment_missed'])

    missed_act = ActivityLog.objects.filter(
        patient=patient, scheduled_time__date__gte=since_baseline, status='missed',
    ).count()
    if missed_act >= 3:
        points += RISK_POINT_WEIGHTS['activity_ignored']

    if not DailyHealthCheck.objects.filter(patient=patient, checked_at__date__gte=since_baseline).exists():
        points += RISK_POINT_WEIGHTS['no_health_update']

    return min(50, points)


def _build_health_consequence_alert(med_insights, refill_insights, disease):
    """Disease-aware health consequence message for patient/doctor/caregiver."""
    best = None
    for ins in med_insights:
        if ins.get('consecutive_misses', 0) >= 2:
            if not best or ins['consecutive_misses'] > best.get('consecutive_misses', 0):
                best = ins
    if not best and refill_insights:
        best = refill_insights[0]
    if not best:
        return None

    label = best.get('category_label') or disease.get('primary_label', 'Health')
    streak = best.get('consecutive_misses') or best.get('refill_gap_days', 0)
    complications = best.get('possible_complications') or []
    if not complications and best.get('predicted_risk'):
        complications = [best['predicted_risk']]

    return {
        'title': 'Health Alert',
        'medicine': best.get('medicine', ''),
        'condition': label,
        'days': streak,
        'message': best.get('patient_message') or (
            f'You missed {label.lower()} medicines for {streak} consecutive days.'
            if streak else f'Refill gap detected for {best.get("medicine", "medicine")}.'
        ),
        'possible_effects': complications[:6],
        'urgency': best.get('severity', 'medium'),
    }


def _analyze_activities(patient, since_recent, since_baseline, disease):
    reasons = []
    impacts = set()
    score_recent = 0
    score_baseline = 0
    critical_miss = False

    for window, since, attr in (
        ('recent', since_recent, 'score_recent'),
        ('baseline', since_baseline, 'score_baseline'),
    ):
        logs = ActivityLog.objects.filter(
            patient=patient, scheduled_time__date__gte=since,
        ).select_related('activity')
        total = logs.count()
        if total == 0:
            continue
        missed = logs.filter(status='missed')
        missed_count = missed.count()
        miss_rate = missed_count / total
        s = int(min(100, miss_rate * 100))

        dialysis = missed.filter(activity__activity_type='dialysis').count()
        if dialysis:
            s = 100
            critical_miss = True
            reasons.append(f'Dialysis session missed {dialysis} time{"s" if dialysis != 1 else ""} — critical')
            impacts.update(['Toxin buildup risk', 'Fluid imbalance', 'Emergency hospitalization risk'])

        rehab = missed.filter(
            activity__activity_type__in=('physiotherapy', 'walking', 'exercise', 'yoga'),
        ).count()
        if rehab >= 3:
            s = min(100, s + 20)
            reasons.append(f'Walk/rehab activity skipped {rehab} times')
            impacts.add('Reduced mobility and increased fatigue')

        if window == 'recent':
            score_recent = s
        else:
            score_baseline = s
            if missed_count and not dialysis:
                reasons.append(
                    f'Missed {missed_count} scheduled activit{"ies" if missed_count != 1 else "y"} (30 days)'
                )
            if disease['has_kidney'] and missed_count:
                impacts.add('Renal care compliance failure')

    blended = int(score_recent * RECENT_WEIGHT + score_baseline * BASELINE_WEIGHT)
    if critical_miss:
        blended = max(blended, 85)
    return blended, reasons, list(impacts), critical_miss


def _analyze_appointments(patient, since_recent, since_baseline, disease):
    reasons = []
    impacts = set()
    scores = []

    for since in (since_recent, since_baseline):
        apts = Appointment.objects.filter(patient=patient, appointment_date__gte=since)
        total = apts.count()
        if not total:
            scores.append(0)
            continue
        missed = apts.filter(status__in=('timeout', 'rejected', 'doctor_unavailable')).count()
        cancelled = apts.filter(status__in=('cancelled', 'cancelled_by_patient', 'cancelled_by_doctor')).count()
        completed = apts.filter(status__in=('completed', 'ended')).count()
        s = int(min(100, (missed + cancelled) / total * 100))
        if apts.filter(is_emergency=True, status='timeout').exists():
            s = min(100, s + 30)
        if completed == 0 and total >= 2:
            s = min(100, s + 15)
        scores.append(s)

    if len(scores) == 2:
        blended = int(scores[0] * RECENT_WEIGHT + scores[1] * BASELINE_WEIGHT)
    else:
        blended = scores[0] if scores else 0

    apts30 = Appointment.objects.filter(patient=patient, appointment_date__gte=since_baseline)
    missed = apts30.filter(status__in=('timeout', 'rejected', 'doctor_unavailable')).count()
    cancelled = apts30.filter(status__in=('cancelled', 'cancelled_by_patient', 'cancelled_by_doctor')).count()
    if missed:
        reasons.append(f'{missed} missed/timeout appointment{"s" if missed != 1 else ""}')
    if cancelled:
        reasons.append(f'{cancelled} cancelled appointment{"s" if cancelled != 1 else ""}')
    if blended >= 40:
        impacts.add('Health monitoring gaps may allow deterioration')
    if disease['has_heart'] and blended >= 30:
        impacts.add('Cardiac follow-up negligence increases complication risk')
    if disease['has_hypertension'] and missed:
        impacts.add('BP monitoring gaps may worsen blood pressure control')

    return blended, reasons, list(impacts)


def _analyze_health(patient, since_recent, since_baseline):
    reasons = []
    impacts = set()
    scores = []

    for since in (since_recent, since_baseline):
        checks = DailyHealthCheck.objects.filter(patient=patient, checked_at__date__gte=since)
        if not checks.exists():
            scores.append(0)
            continue
        not_good = checks.filter(feeling='not_good').count()
        total = checks.count()
        s = int(min(100, (not_good / total) * 100 + not_good * 8))
        symptom_hits = {}
        for check in checks:
            for sym in (check.symptoms or []):
                key = str(sym).lower().strip()
                symptom_hits[key] = symptom_hits.get(key, 0) + 1
            notes = (check.notes or '').lower()
            for sym in ('chest pain', 'dizziness', 'breathlessness', 'anxiety', 'stress'):
                if sym in notes:
                    s = min(100, s + 10)
        scores.append(s)

    blended = int(scores[0] * RECENT_WEIGHT + scores[1] * BASELINE_WEIGHT) if len(scores) == 2 else (scores[0] if scores else 0)

    checks = DailyHealthCheck.objects.filter(patient=patient, checked_at__date__gte=since_baseline)
    not_good = checks.filter(feeling='not_good').count()
    if not_good >= 2:
        reasons.append(f'Poor health reported {not_good} times in check-ins')
        impacts.add('General health deterioration pattern detected')
    for check in checks:
        for sym in (check.symptoms or []):
            key = str(sym).lower()
            if key in ('chest pain', 'breathlessness', 'chest_pain'):
                impacts.add('Cardiovascular symptoms require medical evaluation')
                break

    mental_hits = sum(
        1 for c in checks
        for s in (c.symptoms or [])
        if str(s).lower() in ('anxiety', 'stress', 'depression', 'insomnia')
    )
    if mental_hits >= 2:
        reasons.append('Repeated mental health symptoms in questionnaires')
        impacts.add('Mental health deterioration risk')

    return blended, reasons, list(impacts)


def _analyze_emergency(patient, since_baseline):
    emergencies = Appointment.objects.filter(
        patient=patient, is_emergency=True, created_at__date__gte=since_baseline,
    )
    count = emergencies.count()
    if not count:
        return 0, [], []
    score = min(100, count * 25)
    timeouts = emergencies.filter(status='timeout').count()
    if timeouts:
        score = min(100, score + timeouts * 15)
    alerts = HealthRiskAlert.objects.filter(patient=patient, sent_at__date__gte=since_baseline).count()
    score = min(100, score + alerts * 5)
    reasons = [f'{count} emergency/SOS event{"s" if count != 1 else ""} in period']
    impacts = ['Frequent emergencies indicate unstable baseline health'] if count >= 2 else []
    return score, reasons, impacts


def _analyze_negligence(patient, since_baseline):
    score = 0
    reasons = []
    impacts = []

    med_logs = MedicineLog.objects.filter(patient=patient, scheduled_time__date__gte=since_baseline)
    consecutive = _consecutive_misses(med_logs)
    if consecutive >= 3:
        score += min(40, consecutive * 8)
        reasons.append(f'Ignored medicine schedule — {consecutive} consecutive misses')

    act_missed = ActivityLog.objects.filter(
        patient=patient, status='missed', scheduled_time__date__gte=since_baseline,
    ).count()
    if act_missed >= 3:
        score += min(30, act_missed * 4)
        reasons.append(f'Ignored {act_missed} activity reminders')

    if MissedAlertLog.objects.filter(patient=patient, sent_at__date__gte=since_baseline).exists():
        score += 10

    if patient.last_activity:
        days_inactive = (timezone.now() - patient.last_activity).days
        if days_inactive >= 3:
            score += min(25, days_inactive * 5)
            reasons.append(f'Low app engagement — inactive {days_inactive} days')
    else:
        score += 15
        reasons.append('No recent app activity recorded')

    if score >= 50:
        impacts.append('Serious compliance risk — patient may need caregiver intervention')
    return min(100, score), reasons, impacts


def _recovery_factor(patient, since_recent):
    """Reduce score when recent 7-day behaviour improves vs prior week."""
    today = date.today()
    prev_start = today - timedelta(days=14)
    prev_end = today - timedelta(days=7)

    def adherence_pct(start, end):
        logs = MedicineLog.objects.filter(
            patient=patient,
            scheduled_time__date__gte=start,
            scheduled_time__date__lt=end,
        )
        total = logs.count()
        if not total:
            return None
        return logs.filter(status='taken').count() / total

    recent = adherence_pct(since_recent, today + timedelta(days=1))
    prior = adherence_pct(prev_start, prev_end)
    if recent is None or prior is None:
        return 0
    improvement = recent - prior
    if improvement >= 0.15:
        return -18
    if improvement >= 0.08:
        return -10
    if recent >= 0.9 and prior < 0.7:
        return -12
    return 0


def _determine_escalation(level, worst_consecutive, medicine_insights, dialysis_critical, disease):
    if dialysis_critical or (level == 'critical'):
        return 4
    critical_meds = [i for i in medicine_insights if i.get('priority') == 'critical' and i.get('consecutive_misses', 0) >= 3]
    if critical_meds or (level == 'critical' and worst_consecutive >= 2):
        return 4
    if level == 'high' or worst_consecutive >= 4:
        return 3
    if worst_consecutive >= 2 or level == 'medium':
        return 2
    return 1


def _level_from_score(score):
    if score <= 25:
        return 'low'
    if score <= 50:
        return 'medium'
    if score <= 75:
        return 'high'
    return 'critical'


def _classify_risk_types(components, total, disease):
    types = []
    if components.get('medicine', 0) >= 35:
        types.append('medication')
    if components.get('activity', 0) >= 35:
        types.append('physical')
    if components.get('health', 0) >= 35:
        types.append('deterioration')
    if components.get('appointment', 0) >= 30:
        types.append('appointment')
    if components.get('health', 0) >= 25 and disease.get('has_mental'):
        types.append('mental')
    if components.get('activity', 0) >= 25:
        types.append('lifestyle')
    if components.get('emergency', 0) >= 20:
        types.append('emergency')
    if total >= 51:
        types.append('high_risk')
    return list(dict.fromkeys(types))


def _build_patient_message(level, medicine_insights, activity_impacts, disease):
    if medicine_insights:
        primary = max(medicine_insights, key=lambda x: x.get('consecutive_misses', 0))
        if primary.get('patient_message'):
            return primary['patient_message']
    if level == 'low':
        return 'You are maintaining good health. Keep following your care plan.'
    if activity_impacts and 'Emergency hospitalization risk' in activity_impacts:
        return 'Critical activity (dialysis) missed — immediate medical attention recommended.'
    if disease.get('has_diabetes'):
        return 'Please follow your diabetes medicines and monitor blood sugar regularly.'
    if disease.get('has_hypertension'):
        return 'Blood pressure control depends on consistent medicine adherence.'
    return 'Please follow medicines and activities regularly to reduce health risk.'


def _build_prediction_summary(medicine_insights, impacts, level):
    parts = []
    if medicine_insights:
        top = max(medicine_insights, key=lambda x: x.get('consecutive_misses', 0))
        parts.append(top.get('predicted_risk', ''))
    for imp in impacts[:3]:
        if imp not in parts:
            parts.append(imp)
    if level in ('high', 'critical') and not parts:
        parts.append('Health deterioration risk is elevated based on recent behaviour.')
    return ' · '.join(p for p in parts if p)[:500]


class DynamicRiskEngineService:
    """Real-time dynamic healthcare risk prediction engine."""

    @classmethod
    def analyze(cls, patient, trigger_medicine=None):
        if isinstance(patient, int):
            patient = CustomUser.objects.get(pk=patient)

        today = date.today()
        since_recent = today - timedelta(days=RECENT_WINDOW_DAYS)
        since_baseline = today - timedelta(days=BASELINE_WINDOW_DAYS)
        profile = _patient_profile(patient)
        disease = _disease_context(profile)

        med_s, med_r, med_i, med_insights, worst_consec, worst_cat = _analyze_medicines(
            patient, since_recent, since_baseline, disease,
        )
        refill_s, refill_r, refill_i, refill_insights, refill_pts = _analyze_refill_gaps(patient, disease)
        act_s, act_r, act_i, dialysis_critical = _analyze_activities(
            patient, since_recent, since_baseline, disease,
        )
        apt_s, apt_r, apt_i = _analyze_appointments(patient, since_recent, since_baseline, disease)
        hlth_s, hlth_r, hlth_i = _analyze_health(patient, since_recent, since_baseline)
        emrg_s, emrg_r, emrg_i = _analyze_emergency(patient, since_baseline)
        neg_s, neg_r, neg_i = _analyze_negligence(patient, since_baseline)

        components = {
            'medicine': max(med_s, refill_s), 'activity': act_s, 'appointment': apt_s,
            'health': hlth_s, 'emergency': emrg_s, 'negligence': neg_s,
        }

        weighted = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
        total = int(min(100, round(weighted * disease['multiplier'])))
        total += _recovery_factor(patient, since_recent)
        event_points = _compute_weighted_event_points(
            patient, since_baseline, med_insights, worst_consec, refill_pts,
        )
        total += event_points
        total = max(0, min(100, total))

        if dialysis_critical:
            total = max(total, 80)
        if worst_consec >= 5 and DISEASE_RULES.get(worst_cat, {}).get('medicine_priority') == 'critical':
            total = max(total, 85)
        elif worst_consec >= 5:
            total = max(total, 70)

        all_reasons = list(dict.fromkeys(med_r + refill_r + act_r + apt_r + hlth_r + emrg_r + neg_r))
        all_impacts = list(dict.fromkeys(med_i + refill_i + act_i + apt_i + hlth_i + emrg_i + neg_i))
        level = _level_from_score(total)
        risk_types = _classify_risk_types(components, total, disease)
        escalation = _determine_escalation(level, worst_consec, med_insights, dialysis_critical, disease)

        actions = []
        if 'medication' in risk_types:
            actions.append('Take all prescribed medicines on schedule immediately')
        if 'physical' in risk_types:
            actions.append('Complete scheduled activities and rehab exercises')
        if 'appointment' in risk_types:
            actions.append('Book and attend doctor follow-up appointments')
        if level in ('high', 'critical'):
            actions.append('Consult your doctor promptly')
        if level == 'critical' or dialysis_critical:
            actions.append('Seek immediate medical attention if symptoms worsen')
        if disease.get('has_diabetes'):
            actions.append('Monitor blood sugar regularly')
        if disease.get('has_hypertension'):
            actions.append('Monitor blood pressure daily')
        if not actions:
            actions.append('Maintain current healthy routine')

        patient_message = _build_patient_message(level, med_insights, all_impacts, disease)
        prediction_summary = _build_prediction_summary(med_insights, all_impacts, level)
        health_consequence = _build_health_consequence_alert(med_insights, refill_insights, disease)

        rolling = {
            'recent_7d': {k: components[k] for k in components},
            'baseline_30d_blend': components,
            'recovery_applied': _recovery_factor(patient, since_recent),
            'event_weighted_points': event_points,
        }

        dynamic_analysis = {
            'predictions': all_impacts[:10],
            'prediction_summary': prediction_summary,
            'patient_message': patient_message,
            'health_consequence': health_consequence,
            'escalation_level': escalation,
            'notify_targets': NOTIFY_TARGETS.get(escalation, ['patient']),
            'medicine_insights': med_insights[:8],
            'refill_insights': refill_insights[:5],
            'worst_medicine_streak': worst_consec,
            'worst_category': worst_cat,
            'dialysis_critical': dialysis_critical,
            'rolling_analysis': rolling,
            'why_risk_increased': all_reasons[:10],
            'weighted_points': event_points,
            'doctor_intervention': (
                med_insights[0] if med_insights and level in ('high', 'critical') else None
            ),
        }

        component_scores = {
            k: {'score': components[k], 'weight_pct': int(WEIGHTS[k] * 100)}
            for k in WEIGHTS
        }

        level_messages = {
            'low': patient_message,
            'medium': patient_message,
            'high': patient_message,
            'critical': patient_message,
        }

        return {
            'score': total,
            'level': level,
            'level_message': level_messages[level],
            'risk_types': risk_types,
            'risk_type_labels': [RISK_TYPE_LABELS.get(t, t) for t in risk_types],
            'reasons': all_reasons[:12],
            'health_impacts': all_impacts[:10],
            'recommended_actions': actions[:6],
            'component_scores': component_scores,
            'factors': {f'{k}_risk': f'{components[k]}/100' for k in WEIGHTS},
            'disease_context': disease,
            'dynamic_analysis': dynamic_analysis,
            'escalation_level': escalation,
        }
