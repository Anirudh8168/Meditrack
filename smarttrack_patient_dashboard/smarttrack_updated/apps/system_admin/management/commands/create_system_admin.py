from django.core.management.base import BaseCommand
from apps.accounts.models import CustomUser


class Command(BaseCommand):
    help = 'Create a system admin user for SmartTrack custom admin panel'

    def add_arguments(self, parser):
        parser.add_argument('--email', default='admin@smarttrack.com')
        parser.add_argument('--password', default='Admin@123456')
        parser.add_argument('--first-name', default='System')
        parser.add_argument('--last-name', default='Admin')

    def handle(self, *args, **options):
        email = options['email'].lower()
        if CustomUser.objects.filter(email__iexact=email).exists():
            user = CustomUser.objects.get(email__iexact=email)
            user.role = 'admin'
            user.is_staff = True
            user.is_superuser = True
            user.set_password(options['password'])
            user.save()
            self.stdout.write(self.style.WARNING(f'Updated existing admin: {email}'))
        else:
            user = CustomUser.objects.create_user(
                username=email,
                email=email,
                password=options['password'],
                first_name=options['first_name'],
                last_name=options['last_name'],
                role='admin',
                is_staff=True,
                is_superuser=True,
            )
            self.stdout.write(self.style.SUCCESS(f'Created admin: {email} ({user.unique_id})'))
        self.stdout.write(f'Login at /system-admin/login/')
