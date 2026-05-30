"""PDF receipt for consultation payments — generated only after verified payment."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable


def build_payment_receipt_pdf(payment):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle('T', parent=styles['Title'], fontSize=18, textColor=colors.HexColor('#0F172A'))
    body = ParagraphStyle('B', parent=styles['Normal'], fontSize=10, leading=14)
    small = ParagraphStyle('S', parent=body, fontSize=9, textColor=colors.HexColor('#64748B'))

    apt = payment.appointment
    receipt_id = payment.receipt_id or payment.payment_id
    story = [
        Paragraph('SMARTTRACK CONSULTATION RECEIPT', title),
        Spacer(1, 0.15 * cm),
        Paragraph('Official payment receipt for healthcare consultation', small),
        Spacer(1, 0.25 * cm),
        HRFlowable(width='100%', thickness=2, color=colors.HexColor('#2563EB')),
        Spacer(1, 0.4 * cm),
    ]

    rows = [
        ['Receipt ID', receipt_id],
        ['Transaction ID', payment.transaction_id or '—'],
        ['Patient', payment.patient.get_full_name()],
        ['Doctor', f'Dr. {payment.doctor.get_full_name()}'],
        ['Consultation Type', payment.appointment_type_display],
        ['Appointment Date', apt.appointment_date.strftime('%B %d, %Y')],
        ['Appointment Time', apt.appointment_time.strftime('%I:%M %p')],
        ['Consultation Fee', f'₹{payment.amount}'],
        ['Payment Method', payment.get_payment_method_display() or payment.payment_method or '—'],
        ['Payment Status', 'Paid'],
        ['Verified', 'Yes' if payment.verified else 'No'],
        ['Timestamp', payment.paid_at.strftime('%B %d, %Y %I:%M %p') if payment.paid_at else '—'],
    ]
    t = Table(rows, colWidths=[5.5 * cm, 11.5 * cm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#EFF6FF')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1E40AF')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#BFDBFE')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph(
        'This is a computer-generated receipt. No signature required.<br/>'
        'Thank you for using SmartTrack healthcare services.',
        small,
    ))

    doc.build(story)
    buf.seek(0)
    return buf
