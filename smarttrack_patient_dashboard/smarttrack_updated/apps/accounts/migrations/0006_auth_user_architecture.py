from django.db import migrations, models


def migrate_auth_to_profiles(apps, schema_editor):
    User = apps.get_model('accounts', 'CustomUser')
    PatientProfile = apps.get_model('profiles', 'PatientProfile')
    DoctorProfile = apps.get_model('profiles', 'DoctorProfile')
    CaregiverProfile = apps.get_model('caregiver', 'CaregiverProfile')

    for user in User.objects.all():
        if user.role == 'patient':
            profile, _ = PatientProfile.objects.get_or_create(user=user)
            if getattr(user, 'unique_id', None):
                profile.patient_id = user.unique_id
            profile.first_name = user.first_name or profile.first_name
            profile.last_name = user.last_name or profile.last_name
            if getattr(user, 'phone', None):
                profile.phone_number = user.phone
            if getattr(user, 'profile_completed', False):
                profile.onboarding_completed = True
                profile.step_completed = max(profile.step_completed or 0, 3)
            profile.save()
        elif user.role == 'doctor':
            profile, _ = DoctorProfile.objects.get_or_create(user=user)
            if getattr(user, 'unique_id', None):
                profile.doctor_id = user.unique_id
            profile.full_name = f'{user.first_name} {user.last_name}'.strip() or profile.full_name
            if getattr(user, 'phone', None):
                profile.phone = user.phone
            if getattr(user, 'profile_completed', False):
                profile.onboarding_completed = True
                profile.step_completed = max(profile.step_completed or 0, 3)
            profile.save()
        elif user.role == 'caregiver':
            profile, _ = CaregiverProfile.objects.get_or_create(user=user)
            if getattr(user, 'unique_id', None):
                profile.cg_id = user.unique_id
            profile.full_name = f'{user.first_name} {user.last_name}'.strip() or profile.full_name
            if getattr(user, 'phone', None):
                profile.phone = user.phone
            if getattr(user, 'profile_completed', False):
                profile.onboarding_completed = True
            profile.save()


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0005_profile_architecture'),
        ('caregiver', '0006_caregiver_profile_architecture'),
        ('accounts', '0005_preferred_language'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='otp_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterModelTable(
            name='customuser',
            table='auth_user',
        ),
        migrations.AlterModelTable(
            name='otprecord',
            table='auth_otp_record',
        ),
        migrations.RunPython(migrate_auth_to_profiles, migrations.RunPython.noop),
        migrations.RemoveField(model_name='customuser', name='phone'),
        migrations.RemoveField(model_name='customuser', name='unique_id'),
        migrations.RemoveField(model_name='customuser', name='profile_completed'),
        migrations.RemoveField(model_name='customuser', name='preferred_language'),
    ]
