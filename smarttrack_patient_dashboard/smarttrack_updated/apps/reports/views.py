from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from datetime import date, timedelta
from .models import Report
from apps.accounts.models import CustomUser
from apps.medicines.models import RiskScore
from apps.medicines.risk_calculation_service import RiskCalculationService
from apps.notifications.utils import notify_user


@login_required
def generate_report(request, patient_id):
    if request.user.role != 'doctor':
        messages.error(request, 'Only doctors can generate reports.')
        return redirect('/dashboard/doctor/')

    patient = get_object_or_404(CustomUser, id=patient_id, role='patient')
    today = date.today()
    payload = RiskCalculationService.build_report_payload(patient, doctor=request.user, days=30)
    risk = payload['risk']

    taken = sum(m['taken'] for m in payload['medicines'])
    total = sum(m['total'] for m in payload['medicines'])
    missed = sum(m['missed'] for m in payload['medicines'])
    adherence_pct = int(taken / total * 100) if total > 0 else 100

    summary_lines = [
        f"30-day clinical report for {patient.get_full_name()}.",
        f"Overall medicine adherence: {adherence_pct}%.",
        f"Risk level: {risk['level'].upper()} ({risk['score']}/100).",
    ]
    if risk.get('types'):
        summary_lines.append('Risk types: ' + ', '.join(risk['types']))

    ai_parts = [
        f"Clinical assessment for {patient.get_full_name()} covering the last 30 days.",
        f"Medication adherence stands at {adherence_pct}% with {missed} missed doses recorded.",
    ]
    if risk.get('reasons'):
        ai_parts.append('Primary concerns: ' + '; '.join(risk['reasons'][:4]))
    if risk.get('impacts'):
        ai_parts.append('Potential health impacts: ' + '; '.join(risk['impacts'][:3]))
    ai_analysis = ' '.join(ai_parts)

    recs = risk.get('actions') or ['Maintain current treatment plan']
    report = Report.objects.create(
        patient=patient,
        doctor=request.user,
        title=f"Clinical Health Report — {patient.get_full_name()} — {today.strftime('%B %Y')}",
        summary=' '.join(summary_lines),
        ai_analysis=ai_analysis,
        recommendations='\n'.join(f'• {r}' for r in recs),
        risk_level=risk['level'],
        risk_score=risk['score'],
        adherence_pct=adherence_pct,
        status='sent',
        report_data=payload,
    )

    notify_user(
        user=patient,
        title='New Health Report Available',
        message=f'Dr. {request.user.get_full_name()} has generated a clinical health report for you.',
        notification_type='report',
        priority='medium',
        category=f'report_{report.id}',
        related_id=report.id,
    )
    messages.success(request, 'Clinical health report generated and sent to patient!')
    return redirect(f'/reports/{report.id}/')


@login_required
def report_detail(request, report_id):
    report = get_object_or_404(Report, id=report_id)
    user = request.user

    authorized = False
    if user == report.patient or user == report.doctor:
        authorized = True
    elif user.role == 'caregiver':
        from apps.caregiver.models import CaregiverPatientAssignment
        if CaregiverPatientAssignment.objects.filter(
            caregiver=user, patient=report.patient, status='active',
        ).exists():
            authorized = True

    if not authorized:
        messages.error(request, 'Access denied.')
        return redirect('/dashboard/')

    if user == report.patient and report.status == 'sent':
        report.status = 'viewed'
        report.save()

    payload = report.report_data or {}
    return render(request, 'dashboard/report_detail.html', {
        'report': report,
        'payload': payload,
    })


@login_required
def report_list(request):
    from apps.caregiver.access import get_active_patient_context

    user = request.user
    ctx = get_active_patient_context(request)

    if user.role == 'patient':
        reports = Report.objects.filter(patient=user)
    elif user.role == 'doctor':
        reports = Report.objects.filter(doctor=user)
    elif user.role == 'caregiver' and ctx['caregiver_mode'] and ctx['patient']:
        reports = Report.objects.filter(patient=ctx['patient'])
    elif user.role == 'caregiver':
        from apps.caregiver.models import CaregiverPatientAssignment
        patients = CaregiverPatientAssignment.objects.filter(
            caregiver=user, status='active',
        ).values_list('patient_id', flat=True)
        reports = Report.objects.filter(patient_id__in=patients)
    else:
        reports = Report.objects.none()

    return render(request, 'dashboard/report_list.html', {
        'reports': reports,
        'caregiver_mode': ctx['caregiver_mode'],
        'acting_patient': ctx['patient'] if ctx['caregiver_mode'] else None,
    })


@login_required
def download_report_pdf(request, report_id):
    report = get_object_or_404(Report, id=report_id)
    if request.user != report.patient and request.user != report.doctor:
        return HttpResponse('Unauthorized', status=403)
    try:
        import io
        from reportlab.platypus import SimpleDocTemplate
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from apps.reports.pdf_utils import build_clinical_pdf

        payload = report.report_data or RiskCalculationService.build_report_payload(
            report.patient, doctor=report.doctor,
        )
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            rightMargin=1.5 * cm, leftMargin=1.5 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        )
        story, _ = build_clinical_pdf(report, payload)
        doc.build(story)
        buf.seek(0)
        response = HttpResponse(buf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="clinical_report_{report.id}.pdf"'
        return response
    except ImportError:
        return HttpResponse(
            'PDF generation requires reportlab. Install: pip install reportlab',
            content_type='text/plain',
        )
