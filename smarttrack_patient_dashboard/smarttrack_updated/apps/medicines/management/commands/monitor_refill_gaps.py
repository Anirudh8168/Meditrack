"""Daily refill-gap monitoring — flags zero-stock gaps and recalculates risk."""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.medicines.inventory_service import daily_refill_gap_monitor
from apps.medicines.views import calculate_risk_score
from apps.notifications.utils import notify_user


class Command(BaseCommand):
    help = 'Monitor medicine refill gaps and update patient risk scores'

    def handle(self, *args, **options):
        today = timezone.localdate()
        patients = CustomUser.objects.filter(role='patient', is_active=True)
        updated = 0
        for patient in patients:
            bumps = daily_refill_gap_monitor(patient)
            if not bumps:
                continue
            calculate_risk_score(patient)
            updated += 1
            worst = max(bumps, key=lambda b: b['gap_days'])
            if worst['gap_days'] >= 3:
                notify_user(
                    patient,
                    title='⚠️ Medicine Refill Overdue',
                    message=(
                        f'"{worst["medicine"]}" has been out of stock for {worst["gap_days"]} days. '
                        'Please refill immediately.'
                    ),
                    notification_type='alert',
                    priority='high',
                    category=f'refill_gap_{patient.id}_{worst["medicine"]}',
                )
        self.stdout.write(self.style.SUCCESS(
            f'Refill gap monitor complete ({today}) — {updated} patient(s) updated'
        ))
