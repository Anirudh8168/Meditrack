from django.core.management.base import BaseCommand
from apps.accounts.models import CustomUser
from apps.medicines.risk_calculation_service import RiskCalculationService


class Command(BaseCommand):
    help = 'Recalculate multi-factor risk scores for all active patients (daily cron).'

    def handle(self, *args, **options):
        patients = CustomUser.objects.filter(role='patient', is_active=True)
        count = 0
        for patient in patients:
            RiskCalculationService.calculate(patient)
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Recalculated risk for {count} patients.'))
