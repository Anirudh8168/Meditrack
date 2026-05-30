"""Bridge between auth_user (login-only) and role profile tables."""
import random
import string
from datetime import date

from django.db.models import Q


def generate_public_id(role):
    prefix = {'patient': 'PAT', 'doctor': 'DOC', 'admin': 'ADM', 'caregiver': 'CGV', 'family': 'FAM'}.get(role, 'USR')
    suffix = ''.join(random.choices(string.digits, k=6))
    return f'{prefix}{suffix}'


def get_role_profile(user):
    if not user or not getattr(user, 'is_authenticated', True):
        return None
    role = getattr(user, 'role', None)
    try:
        if role == 'patient':
            return user.patient_profile
        if role == 'doctor':
            return user.doctor_profile
        if role == 'caregiver':
            return user.caregiver_profile
        if role == 'family':
            return getattr(user, 'family_member_profile', None)
    except Exception:
        return None
    return None


def get_user_public_id(user):
    if not user:
        return ''
    profile = get_role_profile(user)
    if profile:
        for attr in ('patient_id', 'doctor_id', 'cg_id', 'family_id'):
            val = getattr(profile, attr, None)
            if val:
                return val
    legacy = getattr(user, '_legacy_unique_id', None)
    if legacy:
        return legacy
    return getattr(user, 'username', '') or str(user.pk)


def get_user_phone(user):
    profile = get_role_profile(user)
    if profile:
        for attr in ('phone_number', 'phone', 'alternate_number'):
            val = getattr(profile, attr, None)
            if val:
                return val
    return getattr(user, '_legacy_phone', '') or ''


def set_user_phone(user, value):
    profile = get_role_profile(user)
    if profile:
        if hasattr(profile, 'phone_number'):
            profile.phone_number = value
        elif hasattr(profile, 'phone'):
            profile.phone = value
        profile.save(update_fields=[f for f in ('phone_number', 'phone') if hasattr(profile, f)])


def get_profile_first_name(user):
    profile = get_role_profile(user)
    if profile:
        if getattr(profile, 'first_name', None):
            return profile.first_name
        if getattr(profile, 'full_name', None):
            parts = profile.full_name.split(' ', 1)
            return parts[0]
    return user.first_name or ''


def get_profile_last_name(user):
    profile = get_role_profile(user)
    if profile:
        if getattr(profile, 'last_name', None):
            return profile.last_name
        if getattr(profile, 'full_name', None):
            parts = profile.full_name.split(' ', 1)
            return parts[1] if len(parts) > 1 else ''
    return user.last_name or ''


def get_user_full_name(user):
    profile = get_role_profile(user)
    if profile and getattr(profile, 'full_name', None):
        return profile.full_name.strip()
    first = get_profile_first_name(user)
    last = get_profile_last_name(user)
    return f'{first} {last}'.strip() or user.username


def is_profile_completed(user):
    if not user or user.role == 'admin':
        return True
    profile = get_role_profile(user)
    if profile:
        if hasattr(profile, 'onboarding_completed'):
            return bool(profile.onboarding_completed)
        if hasattr(profile, 'step_completed'):
            return profile.step_completed >= 3
    return bool(getattr(user, '_legacy_profile_completed', False))


def set_profile_completed(user, value=True):
    profile = get_role_profile(user)
    if profile:
        if hasattr(profile, 'onboarding_completed'):
            profile.onboarding_completed = value
            profile.save(update_fields=['onboarding_completed'])
        elif hasattr(profile, 'step_completed') and value:
            profile.step_completed = max(profile.step_completed or 0, 3)
            profile.save(update_fields=['step_completed'])


def ensure_role_profile(user, **defaults):
    """Create role profile stub on signup if missing."""
    from apps.profiles.models import PatientProfile, DoctorProfile
    from apps.caregiver.models import CaregiverProfile
    from apps.family.models import FamilyMemberProfile

    profile = get_role_profile(user)
    if profile:
        return profile

    public_id = generate_public_id(user.role)
    if user.role == 'patient':
        while PatientProfile.objects.filter(patient_id=public_id).exists():
            public_id = generate_public_id('patient')
        return PatientProfile.objects.create(
            user=user,
            patient_id=public_id,
            first_name=defaults.get('first_name', user.first_name or ''),
            last_name=defaults.get('last_name', user.last_name or ''),
            phone_number=defaults.get('phone', ''),
        )
    if user.role == 'doctor':
        while DoctorProfile.objects.filter(doctor_id=public_id).exists():
            public_id = generate_public_id('doctor')
        full = f"{defaults.get('first_name', user.first_name or '')} {defaults.get('last_name', user.last_name or '')}".strip()
        return DoctorProfile.objects.create(
            user=user,
            doctor_id=public_id,
            full_name=full or user.username,
            phone=defaults.get('phone', ''),
        )
    if user.role == 'caregiver':
        while CaregiverProfile.objects.filter(cg_id=public_id).exists():
            public_id = generate_public_id('caregiver')
        full = f"{defaults.get('first_name', user.first_name or '')} {defaults.get('last_name', user.last_name or '')}".strip()
        return CaregiverProfile.objects.create(
            user=user,
            cg_id=public_id,
            full_name=full or user.username,
            phone=defaults.get('phone', ''),
        )
    if user.role == 'family':
        while FamilyMemberProfile.objects.filter(family_id=public_id).exists():
            public_id = generate_public_id('family')
        full = f"{defaults.get('first_name', user.first_name or '')} {defaults.get('last_name', user.last_name or '')}".strip()
        return FamilyMemberProfile.objects.create(
            user=user,
            family_id=public_id,
            full_name=full or user.username,
            phone=defaults.get('phone', ''),
        )
    return None


def sync_user_name_cache(user):
    """Keep Django auth name fields in sync for admin/search (cache only)."""
    first = get_profile_first_name(user)
    last = get_profile_last_name(user)
    if user.first_name != first or user.last_name != last:
        user.first_name = first
        user.last_name = last
        user.save(update_fields=['first_name', 'last_name'])


def sync_patient_risk_cache(patient_user):
    """Copy latest risk score onto patient_profile for quick access."""
    try:
        profile = patient_user.patient_profile
        risk = patient_user.risk_score
        profile.risk_score = risk.score
        profile.risk_level = risk.level
        profile.save(update_fields=['risk_score', 'risk_level'])
    except Exception:
        pass


def profile_completed_q():
    """ORM filter for users with completed onboarding (replaces user.profile_completed)."""
    from apps.profiles.models import PatientProfile, DoctorProfile
    from apps.caregiver.models import CaregiverProfile
    from apps.family.models import FamilyMemberProfile

    return (
        Q(role='admin')
        | Q(role='patient', patient_profile__onboarding_completed=True)
        | Q(role='doctor', doctor_profile__onboarding_completed=True)
        | Q(role='caregiver', caregiver_profile__onboarding_completed=True)
        | Q(role='family', family_member_profile__onboarding_completed=True)
        | Q(role='patient', patient_profile__step_completed__gte=3)
        | Q(role='doctor', doctor_profile__step_completed__gte=3)
    )


def compute_age(dob):
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
