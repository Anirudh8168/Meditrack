"""Consultation payment services — fees, Razorpay, pending payment creation."""
from decimal import Decimal
import re
import uuid

from django.conf import settings
from django.utils import timezone

from apps.payments.models import ConsultationPayment
from apps.notifications.utils import notify_user

DEMO_VALID_OTP = '123456'


def generate_receipt_id():
    year = timezone.now().year
    prefix = f'REC-{year}-'
    last = ConsultationPayment.objects.filter(
        receipt_id__startswith=prefix,
    ).order_by('-receipt_id').values_list('receipt_id', flat=True).first()
    if last:
        try:
            seq = int(last.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = ConsultationPayment.objects.filter(receipt_id__startswith=prefix).count() + 1
    else:
        seq = 1
    return f'{prefix}{seq:04d}'


def generate_transaction_id(payment):
    return f'TXN{uuid.uuid4().hex[:8].upper()}'


def initiate_payment(payment, payment_method, initiated_by=None):
    """Step 1 — patient selects method; move to processing."""
    if not payment.is_payable:
        return False, 'Payment cannot be initiated'
    valid_methods = dict(ConsultationPayment.METHOD_CHOICES)
    if payment_method not in valid_methods:
        return False, 'Invalid payment method'
    payment.payment_method = payment_method
    payment.payment_status = 'processing'
    payment.failure_reason = ''
    if initiated_by:
        payment.paid_by = initiated_by
    payment.save(update_fields=['payment_method', 'payment_status', 'failure_reason', 'paid_by'])
    return True, 'Proceed to verification'


def verify_demo_payment(payment, otp_or_pin, paid_by=None):
    """
    Step 2 — demo gateway OTP/PIN verification.
    Accepts OTP 123456 or any 6-digit code; UPI PIN 4–6 digits.
    """
    if payment.payment_status not in ('processing', 'pending', 'failed'):
        return False, 'Invalid payment state'

    code = (otp_or_pin or '').strip()
    if payment.payment_method == 'upi':
        if not re.match(r'^\d{4,6}$', code):
            return mark_payment_failed(payment, 'Invalid UPI PIN. Enter 4–6 digits.')
    else:
        if not re.match(r'^\d{6}$', code):
            return mark_payment_failed(payment, 'Invalid OTP. Enter 6 digits.')
        if code != DEMO_VALID_OTP:
            return mark_payment_failed(payment, 'OTP verification failed. Demo OTP: 123456')

    return mark_payment_paid(
        payment,
        transaction_id=generate_transaction_id(payment),
        payment_method=payment.payment_method or 'demo',
        paid_by=paid_by,
        verified=True,
        otp_verified=True,
    )


def mark_payment_failed(payment, reason='Payment verification failed'):
    payment.payment_status = 'failed'
    payment.failure_reason = reason
    payment.verified = False
    payment.otp_verified = False
    payment.save(update_fields=['payment_status', 'failure_reason', 'verified', 'otp_verified'])
    notify_user(
        user=payment.patient,
        title='❌ Payment Failed',
        message=f'Payment of ₹{payment.amount} could not be completed. {reason}',
        notification_type='appointment',
        priority='high',
        category=f'pay_failed_{payment.payment_id}',
        related_id=payment.appointment_id,
    )
    return False, reason


def cancel_payment(payment, reason='Cancelled by user'):
    if payment.payment_status not in ('pending', 'processing', 'failed'):
        return False, 'Cannot cancel this payment'
    payment.payment_status = 'cancelled'
    payment.failure_reason = reason
    payment.save(update_fields=['payment_status', 'failure_reason'])
    return True, 'Payment cancelled'


def requires_online_payment(appointment):
    return appointment.appointment_type in ('video', 'emergency_video')


def get_doctor_fee(doctor, appointment_type):
    """Return consultation fee for appointment type (None for in-person)."""
    if appointment_type == 'in_person':
        return None
    try:
        profile = doctor.doctor_profile
    except Exception:
        profile = None
    if not profile:
        default = Decimal('500') if appointment_type == 'video' else Decimal('1000')
        return default

    if appointment_type == 'emergency_video':
        fee = profile.emergency_video_fee or profile.video_consultation_fee or profile.consultation_fee
        return fee or Decimal('1000')
    if appointment_type == 'video':
        fee = profile.video_consultation_fee or profile.consultation_fee
        return fee or Decimal('500')
    return profile.consultation_fee


def create_pending_payment(appointment, paid_by_user=None, caregiver_user=None):
    """
    Create pending payment after video/emergency consultation completes.
    Idempotent — returns existing payment if already created.
    """
    if not requires_online_payment(appointment):
        return None
    if appointment.status not in ('completed', 'ended'):
        return None

    existing = ConsultationPayment.objects.filter(appointment=appointment).first()
    if existing:
        return existing

    amount = get_doctor_fee(appointment.doctor, appointment.appointment_type)
    if not amount or amount <= 0:
        amount = Decimal('500')

    payment_type = 'emergency_video' if appointment.appointment_type == 'emergency_video' else 'video'

    payment = ConsultationPayment.objects.create(
        patient=appointment.patient,
        doctor=appointment.doctor,
        appointment=appointment,
        paid_by=paid_by_user,
        caregiver=caregiver_user if caregiver_user and caregiver_user.role == 'caregiver' else None,
        amount=amount,
        payment_type=payment_type,
        appointment_type=appointment.appointment_type,
        payment_status='pending',
    )

    notify_user(
        user=appointment.patient,
        title='💳 Consultation Payment Due',
        message=(
            f'Your {payment.appointment_type_display} with Dr. {appointment.doctor.get_full_name()} '
            f'is complete. Please pay ₹{amount} for the consultation.'
        ),
        notification_type='appointment',
        priority='medium',
        category=f'pay_pending_{payment.payment_id}',
        related_id=appointment.id,
    )
    return payment


def razorpay_enabled():
    return bool(getattr(settings, 'RAZORPAY_KEY_ID', '') and getattr(settings, 'RAZORPAY_KEY_SECRET', ''))


def create_razorpay_order(payment):
    """Create Razorpay order; returns order dict or None in demo mode."""
    if not razorpay_enabled():
        return None
    import razorpay
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    amount_paise = int(payment.total_amount * 100)
    order = client.order.create({
        'amount': amount_paise,
        'currency': payment.currency,
        'receipt': payment.payment_id,
        'notes': {
            'appointment_id': str(payment.appointment_id),
            'patient_id': str(payment.patient_id),
            'doctor_id': str(payment.doctor_id),
        },
    })
    payment.gateway_order_id = order['id']
    payment.save(update_fields=['gateway_order_id'])
    return order


def verify_razorpay_payment(payment, razorpay_payment_id, razorpay_order_id, razorpay_signature):
    if not razorpay_enabled():
        return False, 'Payment gateway not configured'
    import razorpay
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature,
        })
    except Exception as e:
        payment.payment_status = 'failed'
        payment.failure_reason = str(e)
        payment.save(update_fields=['payment_status', 'failure_reason'])
        return False, str(e)
    return mark_payment_paid(
        payment,
        transaction_id=razorpay_payment_id,
        payment_method='razorpay',
        paid_by=None,
        verified=True,
        otp_verified=True,
    )


def mark_payment_paid(payment, transaction_id, payment_method='razorpay', paid_by=None, verified=False, otp_verified=False):
    if payment.payment_status == 'paid':
        return True, 'Already paid'
    payment.payment_status = 'paid'
    payment.transaction_id = transaction_id or generate_transaction_id(payment)
    payment.payment_method = payment_method
    payment.paid_at = timezone.now()
    payment.verified = verified or payment_method == 'razorpay'
    payment.otp_verified = otp_verified or payment_method == 'razorpay'
    if not payment.receipt_id:
        payment.receipt_id = generate_receipt_id()
    if paid_by:
        payment.paid_by = paid_by
    payment.save()

    notify_user(
        user=payment.patient,
        title='✅ Payment Successful',
        message=f'₹{payment.amount} paid for consultation with Dr. {payment.doctor.get_full_name()}.',
        notification_type='appointment',
        priority='low',
        category=f'pay_done_{payment.payment_id}',
        related_id=payment.appointment_id,
    )
    notify_user(
        user=payment.doctor,
        title='💰 Consultation Payment Received',
        message=f'₹{payment.amount} received from {payment.patient.get_full_name()}.',
        notification_type='appointment',
        priority='medium',
        category=f'pay_received_{payment.payment_id}',
        related_id=payment.appointment_id,
    )
    return True, 'Payment successful'


def send_payment_reminders(hours=24):
    """Notify patients with pending payments older than `hours`."""
    cutoff = timezone.now() - timezone.timedelta(hours=hours)
    pending = ConsultationPayment.objects.filter(
        payment_status='pending',
        created_at__lte=cutoff,
        reminder_sent_at__isnull=True,
    ).select_related('patient', 'doctor', 'appointment')

    count = 0
    for p in pending:
        notify_user(
            user=p.patient,
            title='⏰ Pending Consultation Payment',
            message=(
                f'You have a pending consultation payment of ₹{p.amount} '
                f'for your session with Dr. {p.doctor.get_full_name()}.'
            ),
            notification_type='appointment',
            priority='high',
            category=f'pay_reminder_{p.payment_id}',
            related_id=p.appointment_id,
        )
        p.reminder_sent_at = timezone.now()
        p.save(update_fields=['reminder_sent_at'])
        count += 1
    return count


def doctor_earnings_summary(doctor):
    """Earnings breakdown for doctor dashboard."""
    from django.db.models import Sum, Count, Q
    from datetime import date, timedelta

    today = date.today()
    week_start = today - timedelta(days=7)
    month_start = today.replace(day=1)

    base = ConsultationPayment.objects.filter(doctor=doctor)
    paid = base.filter(payment_status='paid')

    def sum_amount(qs):
        return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    return {
        'today': sum_amount(paid.filter(paid_at__date=today)),
        'week': sum_amount(paid.filter(paid_at__date__gte=week_start)),
        'month': sum_amount(paid.filter(paid_at__date__gte=month_start)),
        'pending_count': base.filter(payment_status__in=('pending', 'processing')).count(),
        'pending_amount': sum_amount(base.filter(payment_status__in=('pending', 'processing'))),
        'paid_count': paid.count(),
        'failed_count': base.filter(payment_status='failed').count(),
        'processing_count': base.filter(payment_status='processing').count(),
        'by_type': {
            'video': sum_amount(paid.filter(payment_type='video')),
            'emergency_video': sum_amount(paid.filter(payment_type='emergency_video')),
        },
    }
