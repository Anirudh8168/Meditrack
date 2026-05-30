from django.db.models import Max

from .services import get_notifications_for_user, get_notifications_for_request


def notification_context(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    base = get_notifications_for_request(request)
    unread_count = base.filter(is_read=False).count()
    latest_id = base.aggregate(m=Max('id'))['m'] or 0
    return {
        'unread_count': unread_count,
        'latest_notification_id': latest_id,
    }
