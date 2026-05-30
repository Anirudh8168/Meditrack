"""Doctor-friendly PDF report builder for SmartTrack."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

PDF_LABELS = {
    'report_title': 'SmartTrack Clinical Health Report',
    'patient_summary': 'Patient Summary',
    'medicine_report': 'Medicine Adherence Report',
    'activity_report': 'Activity Report',
    'appointment_history': 'Appointment History',
    'questionnaire': 'Questionnaire Insights',
    'risk_analysis': 'Risk Analysis',
    'doctor_notes': 'Doctor Recommendation Area',
    'trend': 'Risk & Adherence Trends',
    'clinical_review': 'Clinical Summary',
    'recommendations': 'Recommended Actions',
    'patient': 'Patient',
    'doctor': 'Doctor',
    'date': 'Date',
    'adherence': 'Adherence',
    'health_risk': 'Risk Level',
}


def pdf_font_for_language(lang_code=None):
    return 'Helvetica'


def pdf_label(key):
    return PDF_LABELS.get(key, key.replace('_', ' ').title())


def _p(text, style):
    return Paragraph(str(text or '—').replace('\n', '<br/>'), style)


def build_clinical_pdf(report, payload):
    """Build full doctor-friendly PDF from report + payload dict."""
    body_font = pdf_font_for_language()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title', parent=styles['Title'], fontSize=16,
        textColor=colors.HexColor('#0F172A'), spaceAfter=4, fontName=body_font,
    )
    heading_style = ParagraphStyle(
        'Heading', parent=styles['Heading2'], fontSize=12,
        textColor=colors.HexColor('#1E40AF'), spaceBefore=10, spaceAfter=4, fontName=body_font,
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'], fontSize=9, leading=12, fontName=body_font,
    )
    small_style = ParagraphStyle(
        'Small', parent=body_style, fontSize=8, textColor=colors.HexColor('#64748B'),
    )

    story = []
    story.append(_p(pdf_label('report_title'), title_style))
    story.append(_p(report.title, heading_style))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#3B82F6')))
    story.append(Spacer(1, 0.25 * cm))

    pt = payload.get('patient', {})
    risk = payload.get('risk', {})
    info = [
        [pdf_label('patient'), pt.get('name', ''), 'ID', pt.get('id', '')],
        [pdf_label('doctor'), f"Dr. {payload.get('doctor', report.doctor.get_full_name())}", pdf_label('date'), report.created_at.strftime('%d %B %Y')],
        ['Conditions', ', '.join(pt.get('conditions') or []) or pt.get('primary_diagnosis', '—'), pdf_label('health_risk'), f"{risk.get('level', report.risk_level).upper()} ({risk.get('score', report.risk_score)}/100)"],
    ]
    t = Table(info, colWidths=[3 * cm, 6.5 * cm, 2.5 * cm, 4.5 * cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#EFF6FF')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#EFF6FF')),
        ('FONTNAME', (0, 0), (-1, -1), body_font),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#BFDBFE')),
        ('PADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.3 * cm))

    story.append(_p(pdf_label('medicine_report'), heading_style))
    med_rows = [['Medicine', 'Prescribed', 'Remaining', 'Taken', 'Missed', 'Adherence', 'Refill', 'Gap Days']]
    for m in payload.get('medicines', []):
        med_rows.append([
            m.get('name', ''),
            str(m.get('prescribed_quantity', '—')),
            str(m.get('remaining_stock', '—')),
            str(m.get('taken', 0)),
            str(m.get('missed', 0)),
            f"{m.get('adherence_pct', 0)}%",
            m.get('refill_status', '—'),
            str(m.get('refill_gap_days', 0)),
        ])
    if len(med_rows) > 1:
        mt = Table(med_rows, colWidths=[3 * cm, 2.5 * cm, 1.2 * cm, 1.2 * cm, 1.5 * cm, 2 * cm, 3 * cm])
        mt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E40AF')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), body_font),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ]))
        story.append(mt)
    else:
        story.append(_p('No medicine data for this period.', body_style))
    story.append(Spacer(1, 0.2 * cm))

    story.append(_p(pdf_label('activity_report'), heading_style))
    for a in payload.get('activities', []):
        story.append(_p(
            f"<b>{a.get('title')}</b> ({a.get('type')}) — {a.get('schedule')}<br/>"
            f"Completed: {a.get('completed')} · Missed: {a.get('missed')} · Adherence: {a.get('adherence_pct')}%",
            body_style,
        ))
    if not payload.get('activities'):
        story.append(_p('No scheduled activities in this period.', body_style))
    story.append(Spacer(1, 0.2 * cm))

    story.append(_p(pdf_label('appointment_history'), heading_style))
    apt = payload.get('appointments', {})
    story.append(_p(
        f"Booked: {apt.get('booked', 0)} · Completed: {apt.get('completed', 0)} · "
        f"Cancelled: {apt.get('cancelled', 0)} · Missed/Timeout: {apt.get('missed', 0)}",
        body_style,
    ))
    story.append(Spacer(1, 0.2 * cm))

    story.append(_p(pdf_label('questionnaire'), heading_style))
    q = payload.get('questionnaire', {})
    story.append(_p(
        f"Health checks: {q.get('total_checks', 0)} · Poor responses: {q.get('not_good', 0)}",
        body_style,
    ))
    for sym, cnt in (q.get('symptoms') or {}).items():
        story.append(_p(f"• {sym}: reported {cnt} time(s)", small_style))
    story.append(Spacer(1, 0.2 * cm))

    story.append(_p(pdf_label('risk_analysis'), heading_style))
    types = risk.get('types') or []
    story.append(_p(f"Risk Score: {risk.get('score', report.risk_score)}/100 — {risk.get('level', report.risk_level).upper()}", body_style))
    if risk.get('prediction_summary'):
        story.append(_p(f"<b>Prediction:</b> {risk.get('prediction_summary')}", body_style))
    if types:
        story.append(_p('Risk Types: ' + ', '.join(types), body_style))
    story.append(_p('<b>Why Risk Increased:</b>', body_style))
    for r in (risk.get('why_increased') or risk.get('reasons') or [])[:8]:
        story.append(_p(f'• {r}', small_style))
    story.append(_p('<b>Repeated Issues:</b>', body_style))
    for r in (risk.get('repeated_issues') or [])[:8]:
        story.append(_p(f'• {r}', small_style))
    story.append(_p('<b>Possible Health Outcomes:</b>', body_style))
    for imp in (risk.get('predictions') or risk.get('impacts') or [])[:6]:
        story.append(_p(f'• {imp}', small_style))
    if risk.get('medicine_insights'):
        story.append(_p('<b>Medicine Risk Analysis:</b>', body_style))
        for ins in risk.get('medicine_insights', [])[:5]:
            story.append(_p(
                f"• {ins.get('medicine')}: {ins.get('consecutive_misses', 0)} consecutive misses — "
                f"{ins.get('predicted_risk', '')}",
                small_style,
            ))
    hc = risk.get('health_consequence') or payload.get('risk', {}).get('health_consequence')
    if hc:
        story.append(_p('<b>Health Consequence Prediction:</b>', body_style))
        story.append(_p(f"{hc.get('message', '')}", body_style))
        for eff in (hc.get('possible_effects') or [])[:6]:
            story.append(_p(f'• {eff}', small_style))
    story.append(_p(
        f"<b>Activity adherence:</b> {payload.get('activity_adherence_pct', '—')}% · "
        f"<b>Appointment adherence:</b> {payload.get('appointment_adherence_pct', '—')}% · "
        f"<b>Caregiver support:</b> {payload.get('caregiver_status', '—')}",
        body_style,
    ))
    for gap in (payload.get('refill_gaps') or [])[:5]:
        story.append(_p(f"• Refill gap — {gap.get('medicine')}: {gap.get('gap_days')} days without stock", small_style))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p('<b>Doctor Recommendation:</b> Monitor adherence closely. Review predicted complications above.', body_style))
    story.append(Spacer(1, 0.15 * cm))

    story.append(_p(pdf_label('trend'), heading_style))
    trend = payload.get('trend_7') or []
    if trend:
        trend_txt = ' · '.join(f"{t['date']}: {t['score']}" for t in trend[-7:])
        story.append(_p(f'7-day risk trend: {trend_txt}', small_style))
    week = payload.get('week_adherence') or []
    if week:
        wtxt = ' · '.join(f"{w['week']}: {w['pct']}%" for w in week)
        story.append(_p(f'Weekly medicine adherence: {wtxt}', small_style))
    story.append(Spacer(1, 0.2 * cm))

    story.append(_p(pdf_label('recommendations'), heading_style))
    for line in (risk.get('actions') or report.recommendations.split('\n')):
        if str(line).strip():
            story.append(_p(f'• {str(line).strip().lstrip("•")}', body_style))
    story.append(Spacer(1, 0.3 * cm))

    story.append(_p(pdf_label('doctor_notes'), heading_style))
    story.append(_p(' ', body_style))
    story.append(Spacer(1, 1.5 * cm))
    story.append(HRFlowable(width='40%', thickness=0.5, color=colors.grey))
    story.append(_p('Doctor signature / notes', small_style))

    return story, body_font
