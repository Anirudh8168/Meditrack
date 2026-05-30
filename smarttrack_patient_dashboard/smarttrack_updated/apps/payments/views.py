from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.conf import settings

from apps.payments.models import ConsultationPayment
from apps.payments.services import (
    create_razorpay_order,
    verify_razorpay_payment,
    mark_payment_paid,
    razorpay_enabled,
    doctor_earnings_summary,
    initiate_payment,
    verify_demo_payment,
    cancel_payment,
)
from apps.payments.receipt_pdf import build_payment_receipt_pdf
from apps.caregiver.access import get_active_patient_context
from apps.caregiver.models import CaregiverPatientAssignment


def _can_pay(user, payment, ctx=None):
    if payment.payment_status == 'paid':
        return False
    if payment.payment_status not in ('pending', 'failed', 'processing'):
        return False
    if user == payment.patient:
        return True
    if user.role == 'caregiver':
        return CaregiverPatientAssignment.objects.filter(
            caregiver=user, patient=payment.patient, status='active',
        ).exists()
    return False


def _payment_access(user, payment):
    if user.role == 'admin' or user.is_superuser:
        return True
    if user == payment.patient or user == payment.doctor:
        return True
    if user.role == 'caregiver':
        return CaregiverPatientAssignment.objects.filter(
            caregiver=user, patient=payment.patient, status='active',
        ).exists()
    return False


@login_required
def payment_history(request):
    user = request.user
    ctx = get_active_patient_context(request)

    if user.role == 'patient':
        payments = ConsultationPayment.objects.filter(patient=user)
    elif user.role == 'doctor':
        payments = ConsultationPayment.objects.filter(doctor=user)
    elif user.role == 'caregiver' and ctx.get('patient'):
        payments = ConsultationPayment.objects.filter(patient=ctx['patient'])
    elif user.role == 'caregiver':
        pids = CaregiverPatientAssignment.objects.filter(
            caregiver=user, status='active',
        ).values_list('patient_id', flat=True)
        payments = ConsultationPayment.objects.filter(patient_id__in=pids)
    elif user.role == 'admin' or user.is_superuser:
        payments = ConsultationPayment.objects.all()
    else:
        payments = ConsultationPayment.objects.none()

    status_filter = request.GET.get('status', '')
    valid_statuses = ('pending', 'processing', 'paid', 'failed', 'refunded', 'cancelled')
    if status_filter in valid_statuses:
        payments = payments.filter(payment_status=status_filter)

    return render(request, 'dashboard/payments/history.html', {
        'payments': payments.select_related('patient', 'doctor', 'appointment')[:100],
        'status_filter': status_filter,
        'caregiver_mode': ctx.get('caregiver_mode', False),
    })


@login_required
def pay_consultation(request, payment_id):
    """Step 0 — consultation summary; payment method modal (no instant charge)."""
    payment = get_object_or_404(
        ConsultationPayment.objects.select_related('appointment', 'doctor', 'patient'),
        payment_id=payment_id,
    )
    ctx = get_active_patient_context(request)
    if not _can_pay(request.user, payment, ctx):
        if payment.payment_status == 'paid':
            return redirect('payment_success', payment_id=payment.payment_id)
        messages.error(request, 'You cannot pay for this consultation.')
        return redirect('/appointments/')

    if payment.payment_status == 'processing':
        return redirect('payment_verify', payment_id=payment.payment_id)

    if payment.payment_status == 'paid':
        return redirect('payment_success', payment_id=payment.payment_id)

    create_razorpay_order(payment)
    apt = payment.appointment
    duration = apt.get_duration() if hasattr(apt, 'get_duration') else ''

    try:
        doctor_photo = payment.doctor.doctor_profile.profile_photo.url if payment.doctor.doctor_profile.profile_photo else None
    except Exception:
        doctor_photo = None

    return render(request, 'dashboard/payments/pay.html', {
        'payment': payment,
        'appointment': apt,
        'duration': duration,
        'doctor_photo': doctor_photo,
        'razorpay_enabled': razorpay_enabled(),
        'payment_methods': [
            ('upi', 'UPI', 'fa-mobile-alt'),
            ('card', 'Credit/Debit Card', 'fa-credit-card'),
            ('netbanking', 'Net Banking', 'fa-university'),
            ('wallet', 'Wallet', 'fa-wallet'),
        ],
    })


@login_required
@require_POST
def initiate_payment_view(request, payment_id):
    """Step 1 — select payment method and proceed to verification."""
    payment = get_object_or_404(ConsultationPayment, payment_id=payment_id)
    ctx = get_active_patient_context(request)
    if not _can_pay(request.user, payment, ctx):
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    method = request.POST.get('payment_method', '')
    if razorpay_enabled() and method == 'razorpay':
        create_razorpay_order(payment)
        return JsonResponse({
            'success': True,
            'razorpay': True,
            'key': getattr(settings, 'RAZORPAY_KEY_ID', ''),
            'order_id': payment.gateway_order_id,
            'amount_paise': int(payment.total_amount * 100),
        })

    ok, msg = initiate_payment(payment, method, initiated_by=request.user)
    if ok:
        return JsonResponse({
            'success': True,
            'redirect': f'/payments/verify/{payment.payment_id}/',
        })
    return JsonResponse({'success': False, 'message': msg})


@login_required
def payment_verify(request, payment_id):
    """Step 2 — secure OTP/PIN verification screen."""
    payment = get_object_or_404(
        ConsultationPayment.objects.select_related('appointment', 'doctor', 'patient'),
        payment_id=payment_id,
    )
    ctx = get_active_patient_context(request)
    if not _can_pay(request.user, payment, ctx) and payment.payment_status != 'processing':
        if payment.payment_status == 'paid':
            return redirect('payment_success', payment_id=payment.payment_id)
        messages.error(request, 'Payment session expired.')
        return redirect('pay_consultation', payment_id=payment.payment_id)

    if payment.payment_status == 'paid':
        return redirect('payment_success', payment_id=payment.payment_id)

    if payment.payment_status not in ('processing', 'pending', 'failed'):
        return redirect('pay_consultation', payment_id=payment.payment_id)

    if payment.payment_status in ('pending', 'failed') and request.method == 'GET':
        return redirect('pay_consultation', payment_id=payment.payment_id)

    return render(request, 'dashboard/payments/verify.html', {
        'payment': payment,
        'appointment': payment.appointment,
        'is_upi': payment.payment_method == 'upi',
    })


@login_required
@require_POST
def verify_payment(request, payment_id):
    """Step 3 — verify OTP/PIN or Razorpay signature."""
    payment = get_object_or_404(ConsultationPayment, payment_id=payment_id)
    ctx = get_active_patient_context(request)
    if not _can_pay(request.user, payment, ctx) and payment.payment_status == 'processing':
        if payment.paid_by != request.user and request.user != payment.patient:
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    if razorpay_enabled() and request.POST.get('razorpay_payment_id'):
        pid = request.POST.get('razorpay_payment_id')
        oid = request.POST.get('razorpay_order_id')
        sig = request.POST.get('razorpay_signature')
        ok, msg = verify_razorpay_payment(payment, pid, oid, sig)
        if ok:
            payment.paid_by = request.user
            payment.verified = True
            payment.otp_verified = True
            if not payment.receipt_id:
                from apps.payments.services import generate_receipt_id
                payment.receipt_id = generate_receipt_id()
            payment.save(update_fields=['paid_by', 'verified', 'otp_verified', 'receipt_id'])
        return JsonResponse({
            'success': ok,
            'message': msg,
            'redirect': f'/payments/success/{payment.payment_id}/',
        })

    otp = request.POST.get('otp', '') or request.POST.get('upi_pin', '')
    ok, msg = verify_demo_payment(payment, otp, paid_by=request.user)
    return JsonResponse({
        'success': ok,
        'message': msg,
        'redirect': f'/payments/success/{payment.payment_id}/' if ok else None,
        'retry_url': f'/payments/pay/{payment.payment_id}/' if not ok else None,
    })


@login_required
@require_POST
def cancel_payment_view(request, payment_id):
    payment = get_object_or_404(ConsultationPayment, payment_id=payment_id)
    ctx = get_active_patient_context(request)
    if not _can_pay(request.user, payment, ctx):
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
    ok, msg = cancel_payment(payment)
    return JsonResponse({'success': ok, 'message': msg, 'redirect': f'/appointments/detail/{payment.appointment_id}/'})


@login_required
def payment_success(request, payment_id):
    payment = get_object_or_404(
        ConsultationPayment.objects.select_related('doctor', 'patient', 'appointment'),
        payment_id=payment_id,
    )
    if not _payment_access(request.user, payment):
        return redirect('/dashboard/')
    if payment.payment_status != 'paid' or not payment.verified:
        messages.warning(request, 'Payment not yet verified.')
        return redirect('pay_consultation', payment_id=payment.payment_id)
    return render(request, 'dashboard/payments/success.html', {'payment': payment})


@login_required
def download_receipt(request, payment_id):
    payment = get_object_or_404(ConsultationPayment, payment_id=payment_id)
    if not _payment_access(request.user, payment):
        return HttpResponse('Unauthorized', status=403)
    if payment.payment_status != 'paid' or not payment.verified:
        messages.error(request, 'Receipt available only after verified payment.')
        return redirect('payment_history')

    pdf = build_payment_receipt_pdf(payment)
    rid = payment.receipt_id or payment.payment_id
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{rid}.pdf"'
    return response


@login_required
def doctor_earnings(request):
    if request.user.role != 'doctor':
        return redirect('/dashboard/')
    summary = doctor_earnings_summary(request.user)
    recent = ConsultationPayment.objects.filter(doctor=request.user).select_related(
        'patient', 'appointment',
    )[:20]
    return render(request, 'dashboard/doctor/earnings.html', {
        'summary': summary,
        'recent_payments': recent,
    })
