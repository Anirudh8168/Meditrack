from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.timesince import timesince

from .models import Notification
from .notification_utils import (
    apply_notification_search,
    build_notification_filter_query,
    notifications_in_date_range,
    resolve_notification_date_range,
)
from .services import get_notifications_for_user, get_notifications_for_request


def _serialize_notification(n):
    return {
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'type': n.notification_type,
        'priority': n.priority,
        'category': n.category or '',
        'related_id': n.related_id,
        'is_read': n.is_read,
        'created_at': n.created_at.strftime('%b %d, %I:%M %p'),
        'time_ago': f'{timesince(n.created_at)} ago',
        'is_health_risk': bool(n.category and n.category.startswith('health_risk_')),
    }


@login_required
def notification_list(request):
    """Full notifications page — today by default; date range + search filters."""
    user = request.user
    today = date.today()
    notif_type = request.GET.get('type', '').strip()
    search = request.GET.get('q', '').strip()
    show = request.GET.get('show', 'all')  # all | unread

    date_from, date_to, notif_preset = resolve_notification_date_range(request, today)

    qs = get_notifications_for_request(request)
    qs = notifications_in_date_range(qs, date_from, date_to)

    if notif_type and notif_type in dict(Notification.TYPE_CHOICES):
        qs = qs.filter(notification_type=notif_type)
    qs = apply_notification_search(qs, search)
    if show == 'unread':
        qs = qs.filter(is_read=False)

    qs = qs.order_by('-created_at')
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    unread_count = get_notifications_for_request(request).filter(is_read=False).count()
    filter_query = build_notification_filter_query(request)

    return render(
        request,
        'dashboard/notifications.html',
        {
            'notifications': page_obj,
            'page_obj': page_obj,
            'unread_count': unread_count,
            'filter_type': notif_type,
            'filter_search': search,
            'filter_show': show,
            'type_choices': Notification.TYPE_CHOICES,
            'notif_preset': notif_preset,
            'notif_date_from': date_from,
            'notif_date_to': date_to,
            'today': today,
            'filter_query': filter_query,
            'empty_today': notif_preset == 'today' and not page_obj.object_list,
        },
    )


@login_required
def notification_feed(request):
    """JSON feed for the notification drawer (no layout HTML)."""
    user = request.user
    limit = min(int(request.GET.get('limit', 25)), 50)
    today = date.today()
    date_from, date_to, _ = resolve_notification_date_range(request, today)
    qs = notifications_in_date_range(get_notifications_for_request(request), date_from, date_to)
    qs = qs.order_by('-created_at')[:limit]
    unread_count = get_notifications_for_request(request).filter(is_read=False).count()
    latest_id = get_notifications_for_request(request).aggregate(m=Max('id'))['m'] or 0
    return JsonResponse(
        {
            'success': True,
            'notifications': [_serialize_notification(n) for n in qs],
            'unread_count': unread_count,
            'latest_id': latest_id,
        }
    )


@login_required
def mark_read(request, notif_id):
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'success': False}, status=405)
    updated = get_notifications_for_request(request).filter(id=notif_id).update(
        is_read=True
    )
    unread = get_notifications_for_request(request).filter(is_read=False).count()
    latest_id = (
        get_notifications_for_request(request).aggregate(m=Max('id'))['m'] or 0
    )
    return JsonResponse(
        {
            'success': bool(updated),
            'unread_count': unread,
            'latest_id': latest_id,
        }
    )


@login_required
def unread_count(request):
    count = get_notifications_for_request(request).filter(is_read=False).count()
    latest_id = (
        get_notifications_for_request(request).aggregate(m=Max('id'))['m'] or 0
    )
    return JsonResponse({'count': count, 'latest_id': latest_id})


@login_required
def poll_notifications(request):
    """Poll for new unread notifications since last seen id."""
    since_id = int(request.GET.get('since', 0))
    user = request.user
    base_qs = get_notifications_for_request(request)

    new_notifs = base_qs.filter(is_read=False, id__gt=since_id).order_by('-created_at')[:10]

    unread = base_qs.filter(is_read=False).count()
    latest_id = base_qs.aggregate(m=Max('id'))['m'] or 0

    from apps.messaging.models import Message

    unread_msgs = Message.objects.filter(receiver=user, is_read=False).count()

    return JsonResponse(
        {
            'notifications': [_serialize_notification(n) for n in new_notifs],
            'unread_count': unread,
            'unread_messages': unread_msgs,
            'latest_id': latest_id,
        }
    )


@login_required
def mark_all_read(request):
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'success': False}, status=405)
    get_notifications_for_request(request).filter(is_read=False).update(is_read=True)
    latest_id = (
        get_notifications_for_request(request).aggregate(m=Max('id'))['m'] or 0
    )
    return JsonResponse({'success': True, 'unread_count': 0, 'latest_id': latest_id})
