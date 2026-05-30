import re
import random
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import CustomUser, OTPRecord


def validate_password_strength(password):
    errors = []
    if len(password) < 8:
        errors.append("At least 8 characters")
    if not re.search(r'[A-Z]', password):
        errors.append("At least one uppercase letter")
    if not re.search(r'[a-z]', password):
        errors.append("At least one lowercase letter")
    if not re.search(r'\d', password):
        errors.append("At least one number")
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("At least one special character")
    return errors


def home(request):
    if request.user.is_authenticated:
        return redirect(request.user.get_dashboard_url())
    return render(request, 'home/index.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect(request.user.get_dashboard_url())
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        role = request.POST.get('role', '')
        try:
            user_obj = CustomUser.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)
            if user:
                if role and user.role != role:
                    messages.error(request, f'This account is registered as {user.get_role_display()}, not {role.title()}.')
                else:
                    login(request, user)
                    if not user.profile_completed and user.role != 'admin':
                        return redirect('/profile/complete/')
                    return redirect(user.get_dashboard_url())
            else:
                messages.error(request, 'Incorrect password. Please try again.')
        except CustomUser.DoesNotExist:
            messages.error(request, 'No account found with this email.')
    return render(request, 'auth/login.html')


def signup_view(request):
    if request.user.is_authenticated:
        return redirect(request.user.get_dashboard_url())
    selected_role = request.GET.get('role', 'patient')
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        role = request.POST.get('role', 'patient')
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        errors = []
        if not all([first_name, last_name, email, password]):
            errors.append('All fields are required.')
        if CustomUser.objects.filter(email=email).exists():
            errors.append('Email already registered. Please login.')
        if password != confirm_password:
            errors.append('Passwords do not match.')
        pw_errors = validate_password_strength(password)
        if pw_errors:
            errors.append('Password must have: ' + ', '.join(pw_errors))
        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'auth/signup.html', {
                'selected_role': role,
                'form_data': request.POST
            })
        username = email.split('@')[0]
        base = username
        counter = 1
        while CustomUser.objects.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1
        user = CustomUser.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
        )
        from apps.profiles.profile_bridge import ensure_role_profile
        ensure_role_profile(user, first_name=first_name, last_name=last_name, phone=phone)
        login(request, user)
        messages.success(request, f'Welcome, {first_name}! Please complete your profile.')
        return redirect('/profile/complete/')
    return render(request, 'auth/signup.html', {'selected_role': selected_role})


def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('/')


def forgot_password_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        try:
            user = CustomUser.objects.get(email=email)
            otp = str(random.randint(100000, 999999))
            OTPRecord.objects.create(user=user, email=email, otp=otp, purpose='password_reset')
            request.session['reset_email'] = email
            messages.success(request, f'OTP sent! [Dev Mode OTP: {otp}]')
            return redirect('/auth/verify-otp/')
        except CustomUser.DoesNotExist:
            messages.error(request, 'No account found with this email.')
    return render(request, 'auth/forgot_password.html')


def verify_otp_view(request):
    email = request.session.get('reset_email')
    if not email:
        return redirect('/auth/forgot-password/')
    if request.method == 'POST':
        otp = request.POST.get('otp', '').strip()
        record = OTPRecord.objects.filter(
            email=email, otp=otp, purpose='password_reset', is_used=False
        ).order_by('-created_at').first()
        if record:
            record.is_used = True
            record.save()
            request.session['otp_verified'] = True
            return redirect('/auth/reset-password/')
        else:
            messages.error(request, 'Invalid or expired OTP.')
    return render(request, 'auth/verify_otp.html', {'email': email})


def reset_password_view(request):
    if not request.session.get('otp_verified'):
        return redirect('/auth/forgot-password/')
    email = request.session.get('reset_email')
    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm = request.POST.get('confirm_password', '')
        if password != confirm:
            messages.error(request, 'Passwords do not match.')
        else:
            pw_errors = validate_password_strength(password)
            if pw_errors:
                messages.error(request, 'Password requirements not met: ' + ', '.join(pw_errors))
            else:
                try:
                    user = CustomUser.objects.get(email=email)
                    user.set_password(password)
                    user.otp_verified = True
                    user.save(update_fields=['password', 'otp_verified'])
                    del request.session['otp_verified']
                    del request.session['reset_email']
                    messages.success(request, 'Password reset successfully. Please login.')
                    return redirect('/auth/login/')
                except CustomUser.DoesNotExist:
                    messages.error(request, 'User not found.')
    return render(request, 'auth/reset_password.html')
