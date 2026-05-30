from django.core.management.base import BaseCommand

from apps.payments.services import send_payment_reminders


class Command(BaseCommand):
    help = 'Send reminder notifications for pending consultation payments (default: 24h after creation).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Minimum hours since payment was created before sending reminder (default: 24)',
        )

    def handle(self, *args, **options):
        hours = options['hours']
        count = send_payment_reminders(hours=hours)
        self.stdout.write(self.style.SUCCESS(f'Sent {count} payment reminder(s) (>{hours}h pending).'))
