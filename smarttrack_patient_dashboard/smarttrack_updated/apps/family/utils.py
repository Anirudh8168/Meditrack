from django.core.mail import send_mail
from django.conf import settings
from apps.notifications.utils import notify_user
from apps.family.models import FamilyMember

def send_family_alert(patient, alert_type, title, message, priority='high'):
    """
    Sends a real-time notification to all registered family members
    and logs alerts for unregistered family members.
    """
    family_members = FamilyMember.objects.filter(patient=patient)

    if not family_members.exists():
        return False

    success = False
    for member in family_members:
        # 1. Notify Registered Users
        if member.user:
            notify_user(
                user=member.user,
                title=title,
                message=message,
                notification_type='alert',
                priority=priority,
                category=f'family_alert_{alert_type}'
            )
            success = True

        # 2. Simulate SMS/Email for unregistered members
        # In a real system, this would integrate with Twilio or SendGrid
        if member.email:
            try:
                send_mail(
                    subject=f"🚨 {title}",
                    message=f"Alert for {patient.get_full_name()}: {message}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[member.email],
                    fail_silently=True,
                )
                success = True
            except Exception:
                pass

    return success
