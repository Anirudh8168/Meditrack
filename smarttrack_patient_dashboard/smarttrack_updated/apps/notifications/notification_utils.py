"""Date filtering and search helpers for notification lists."""
from datetime import date, timedelta
from typing import Optional, Tuple
from urllib.parse import urlencode

from django.db.models import Q
from django.http import HttpRequest

from .models import Notification


def resolve_notification_date_range(
    request: HttpRequest,
    today: Optional[date] = None,
) -> Tuple[date, date, str]:
    """
    Returns (date_from, date_to, preset_key).
    Default: today only.
    """
    today = today or date.today()
    preset = (request.GET.get('preset') or 'today').strip().lower()
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
        last_day_prev = first_this - timedelta(days=1)
        return last_day_prev.replace(day=1), last_day_prev, 'lastmonth'
    if preset == 'today':
        return today, today, 'today'

    return today, today, 'today'


def notifications_in_date_range(qs, date_from: date, date_to: date):
    """Filter queryset to notifications whose created_at falls on date_from..date_to (inclusive)."""
    return qs.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )


def apply_notification_search(qs, search: str):
    if not search:
        return qs
    search = search.strip()
    type_q = Q()
    for val, label in Notification.TYPE_CHOICES:
        if search.lower() in label.lower() or search.lower() in val:
            type_q |= Q(notification_type=val)
    return qs.filter(
        Q(title__icontains=search)
        | Q(message__icontains=search)
        | Q(notification_type__icontains=search)
        | type_q
    )


def build_notification_filter_query(request: HttpRequest) -> str:
    """Query string for pagination links (preserves active filters)."""
    params = {}
    for key in ('preset', 'from_date', 'to_date', 'type', 'q', 'show'):
        val = request.GET.get(key, '').strip()
        if val:
            params[key] = val
    if not params.get('preset') and not params.get('from_date'):
        params['preset'] = 'today'
    return urlencode(params)


def today_notifications_for_user(user, limit: Optional[int] = 5, unread_only: bool = False):
    from .services import get_notifications_for_user

    today = date.today()
    qs = notifications_in_date_range(get_notifications_for_user(user), today, today)
    if unread_only:
        qs = qs.filter(is_read=False)
    qs = qs.order_by('-created_at')
    if limit is not None:
        return qs[:limit]
    return qs
