from django.utils import timezone
from .models import Notification

def notify_user(user, title, message, notification_type='general', priority='low', category=None, related_id=None):
    """
    Create or update a notification.
    If a notification with the same category exists and is unread,
    we update its timestamp instead of creating a duplicate.
    """
    if category:
        existing = Notification.objects.filter(
            user=user,
            category=category,
            is_read=False
        ).first()

        if existing:
            existing.title = title
            existing.message = message
            existing.notification_type = notification_type
            existing.priority = priority
            existing.related_id = related_id
            existing.created_at = timezone.now()
            existing.save()
            return existing

    return Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        priority=priority,
        category=category,
        related_id=related_id
    )

def remove_notifications(user, category=None, category_contains=None, notification_type=None):
    """
    Remove specific notifications for a user.
    Can be filtered by category, category partial match, or type.
    """
    queryset = Notification.objects.filter(user=user)
    if category:
        queryset = queryset.filter(category=category)
    if category_contains:
        queryset = queryset.filter(category__contains=category_contains)
    if notification_type:
        queryset = queryset.filter(notification_type=notification_type)

    count = queryset.delete()
    return count

def cleanup_old_notifications(user=None):
    """
    Delete notifications to keep the system clean.
    - Read notifications older than 7 days are deleted.
    - Unread notifications older than 14 days are deleted.
    """
    now = timezone.now()
    read_cutoff = now - timezone.timedelta(days=7)
    unread_cutoff = now - timezone.timedelta(days=14)

    # Delete old read notifications
    read_qs = Notification.objects.filter(is_read=True, created_at__lt=read_cutoff)
    if user:
        read_qs = read_qs.filter(user=user)
    read_count = read_qs.delete()

    # Delete very old unread notifications (prevent ghost alerts)
    unread_qs = Notification.objects.filter(is_read=False, created_at__lt=unread_cutoff)
    if user:
        unread_qs = unread_qs.filter(user=user)
    unread_count = unread_qs.delete()

    return read_count + unread_count
