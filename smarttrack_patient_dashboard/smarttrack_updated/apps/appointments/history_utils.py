"""Appointment history: today dashboard slices + filtered history page."""
from datetime import date, timedelta
from typing import Optional, Tuple
from urllib.parse import quote

from django.http import HttpRequest

from apps.appointments.models import Appointment

UPCOMING_STATUSES = (
    'pending', 'pending_confirmation', 'pending_doctor_confirmation',
    'doctor_confirmed', 'patient_confirmed', 'confirmed', 'ongoing',
)

TERMINAL_STATUSES = (
    'completed', 'ended', 'rejected', 'timeout',
    'cancelled', 'cancelled_by_patient', 'cancelled_by_doctor',
)

# Old bare "cancelled" rows (test/debug data) — keep in DB, never show in UI.
LEGACY_CANCELLED_STATUS = 'cancelled'

MODERN_CANCELLED_STATUSES = ('cancelled_by_patient', 'cancelled_by_doctor')

HISTORY_CATEGORIES = {
    'emergency': {
        'title': 'Emergency Consultations',
        'today_title': "Today's Emergency Appointments",
        'icon': 'fa-bolt',
        'color': 'amber',
    },
    'video': {
        'title': 'Video Consultations',
        'today_title': "Today's Video Consultations",
        'icon': 'fa-video',
        'color': 'blue',
    },
    'completed': {
        'title': 'Completed Appointments',
        'today_title': "Today's Completed Appointments",
        'icon': 'fa-check-circle',
        'color': 'emerald',
    },
    'rejected': {
        'title': 'Rejected & Missed Appointments',
        'today_title': "Today's Rejected Appointments",
        'icon': 'fa-times-circle',
        'color': 'red',
    },
    'cancelled': {
        'title': 'Cancelled Appointments',
        'today_title': "Today's Cancelled Appointments",
        'icon': 'fa-ban',
        'color': 'slate',
        'history_only': True,
    },
    'past': {
        'title': 'Past Appointments',
        'today_title': "Today's Appointment History",
        'icon': 'fa-history',
        'color': 'violet',
    },
    'all': {
        'title': 'All Appointment History',
        'today_title': "Today's Appointments",
        'icon': 'fa-calendar-alt',
        'color': 'violet',
    },
}

DEFAULT_EMERGENCY_DRAFT = (
    'I noticed you attempted an emergency consultation. Are you okay? '
    'Please let me know if you need any help.'
)


def resolve_history_date_range(
    request: HttpRequest,
    today: Optional[date] = None,
) -> Tuple[date, date, str]:
    today = today or date.today()
    preset = (request.GET.get('preset') or 'all').strip().lower()
    from_str = request.GET.get('from_date', '').strip()
    to_str = request.GET.get('to_date', '').strip()

    if from_str and to_str:
        try:
            date_from = date.fromisoformat(from_str)
            date_to = date.fromisoformat(to_str)
            if date_from > date_to:
                date_from, date_to = date_to, date_from
            return date_from, date_to, 'custom'
        except ValueError:
            pass

    if preset == 'all':
        return date(2000, 1, 1), today + timedelta(days=365), 'all'
    if preset == 'yesterday':
        y = today - timedelta(days=1)
        return y, y, 'yesterday'
    if preset == 'last7':
        return today - timedelta(days=6), today, 'last7'
    if preset == 'month':
        return today.replace(day=1), today, 'month'
    if preset == 'lastmonth':
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev, 'lastmonth'
    if preset == 'today':
        return today, today, 'today'

    return today.replace(day=1), today, 'month'


def filter_by_date(qs, date_from: date, date_to: date):
    return qs.filter(
        appointment_date__gte=date_from,
        appointment_date__lte=date_to,
    )


def exclude_legacy_cancelled(qs):
    """Hide deprecated bare 'cancelled' rows (old test data); DB rows unchanged."""
    return qs.exclude(status=LEGACY_CANCELLED_STATUS)


def queryset_for_category(qs, category: str):
    """History queryset for a category (before date filter)."""
    category = category if category in HISTORY_CATEGORIES else 'all'
    qs = exclude_legacy_cancelled(qs).exclude(status__in=UPCOMING_STATUSES)

    if category == 'emergency':
        return qs.filter(
            appointment_type='emergency_video',
            is_emergency=True,
        )
    if category == 'video':
        return qs.filter(appointment_type='video')
    if category == 'completed':
        return qs.filter(status__in=('completed', 'ended'))
    if category == 'rejected':
        return qs.filter(status__in=('rejected', 'timeout'))
    if category == 'cancelled':
        return qs.filter(status__in=MODERN_CANCELLED_STATUSES)
    if category == 'past':
        return qs.exclude(
            appointment_type='emergency_video',
            is_emergency=True,
        ).exclude(
            status__in=('rejected', 'timeout', LEGACY_CANCELLED_STATUS, *MODERN_CANCELLED_STATUSES)
        )
    return qs


def order_history(qs):
    return qs.order_by('-appointment_date', '-appointment_time', '-updated_at')


def annotate_history_list(appointments, user):
    for apt in appointments:
        apt.role_status = apt.get_role_based_status(user)
        if user.role == 'doctor' and apt.is_emergency:
            apt.emergency_badge = apt.get_emergency_badge_for_doctor()
    return list(appointments)


def build_today_dashboard_sections(apts, user, today: date):
    """Today-only lists for dashboard (hide section when empty)."""
    from apps.appointments.emergency_utils import get_doctor_today_emergency_history

    base = exclude_legacy_cancelled(apts.filter(appointment_date=today))

    today_emergency = []
    if user.role == 'doctor':
        today_emergency = list(get_doctor_today_emergency_history(user, today))
        for apt in today_emergency:
            apt.role_status = apt.get_role_based_status(user)
            apt.emergency_badge = apt.get_emergency_badge_for_doctor()
    else:
        today_emergency = annotate_history_list(
            order_history(
                base.filter(
                    appointment_type='emergency_video',
                    is_emergency=True,
                ).exclude(status__in=UPCOMING_STATUSES)
            ),
            user,
        )

    today_emergency_consult = annotate_history_list(
        order_history(
            base.filter(
                appointment_type='emergency_video',
                is_emergency=True,
                status__in=TERMINAL_STATUSES,
            )
        ),
        user,
    )

    today_rejected = annotate_history_list(
        order_history(base.filter(status__in=('rejected', 'timeout'))),
        user,
    )

    today_cancelled = annotate_history_list(
        order_history(base.filter(status__in=MODERN_CANCELLED_STATUSES)),
        user,
    )

    today_completed = annotate_history_list(
        order_history(base.filter(status__in=('completed', 'ended'))),
        user,
    )

    today_video = annotate_history_list(
        order_history(
            base.filter(appointment_type='video').exclude(status__in=UPCOMING_STATUSES)
        ),
        user,
    )

    today_past = annotate_history_list(
        order_history(
            base.filter(appointment_type='in_person').exclude(status__in=UPCOMING_STATUSES)
        ),
        user,
    )

    return {
        'today_emergency': today_emergency,
        'today_emergency_consult': today_emergency_consult,
        'today_rejected': today_rejected,
        'today_cancelled': today_cancelled,
        'today_completed': today_completed,
        'today_video': today_video,
        'today_past': today_past,
    }


def history_page_url(category: str, preset: str = 'all') -> str:
    return f'/appointments/history/?category={category}&preset={preset}'


def message_contact_url(patient_id: int, draft: str = '') -> str:
    base = f'/messages/?with={patient_id}'
    if draft:
        return f'{base}&draft={quote(draft)}'
    return base


def build_history_filter_query(request: HttpRequest, category: str) -> str:
    from urllib.parse import urlencode
    params = {'category': category}
    for key in ('preset', 'from_date', 'to_date'):
        val = request.GET.get(key, '').strip()
        if val:
            params[key] = val
    if not params.get('preset') and not params.get('from_date'):
        params['preset'] = 'all'
    return urlencode(params)
