from django.db import migrations, models
import django.db.models.deletion


def backfill_reminder_tracking(apps, schema_editor):
    ReminderTracking = apps.get_model('medicines', 'ReminderTracking')
    MedicineLog = apps.get_model('medicines', 'MedicineLog')
    ActivityLog = apps.get_model('medicines', 'ActivityLog')

    for log in MedicineLog.objects.filter(status='scheduled'):
        next_at = log.snoozed_until or log.scheduled_time
        ReminderTracking.objects.get_or_create(
            reference_type='medicine',
            reference_id=log.id,
            defaults={
                'patient_id': log.patient_id,
                'scheduled_datetime': log.scheduled_time,
                'next_popup_at': next_at,
                'last_popup_at': log.last_popup_at,
                'current_reminder_count': log.reminder_count or 0,
                'status': 'snoozed' if log.snoozed_until else 'pending',
            },
        )

    for log in ActivityLog.objects.filter(status='scheduled'):
        next_at = log.snoozed_until or log.scheduled_time
        ReminderTracking.objects.get_or_create(
            reference_type='activity',
            reference_id=log.id,
            defaults={
                'patient_id': log.patient_id,
                'scheduled_datetime': log.scheduled_time,
                'next_popup_at': next_at,
                'last_popup_at': log.last_popup_at,
                'current_reminder_count': log.reminder_count or 0,
                'status': 'snoozed' if log.snoozed_until else 'pending',
            },
        )

    for log in MedicineLog.objects.filter(status='taken'):
        ReminderTracking.objects.get_or_create(
            reference_type='medicine',
            reference_id=log.id,
            defaults={
                'patient_id': log.patient_id,
                'scheduled_datetime': log.scheduled_time,
                'next_popup_at': log.scheduled_time,
                'status': 'completed',
            },
        )

    for log in MedicineLog.objects.filter(status='missed'):
        ReminderTracking.objects.get_or_create(
            reference_type='medicine',
            reference_id=log.id,
            defaults={
                'patient_id': log.patient_id,
                'scheduled_datetime': log.scheduled_time,
                'next_popup_at': log.scheduled_time,
                'status': 'missed',
            },
        )

    for log in ActivityLog.objects.filter(status__in=('completed', 'in_progress')):
        ReminderTracking.objects.get_or_create(
            reference_type='activity',
            reference_id=log.id,
            defaults={
                'patient_id': log.patient_id,
                'scheduled_datetime': log.scheduled_time,
                'next_popup_at': log.scheduled_time,
                'status': 'completed',
            },
        )

    for log in ActivityLog.objects.filter(status='missed'):
        ReminderTracking.objects.get_or_create(
            reference_type='activity',
            reference_id=log.id,
            defaults={
                'patient_id': log.patient_id,
                'scheduled_datetime': log.scheduled_time,
                'next_popup_at': log.scheduled_time,
                'status': 'missed',
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_auth_user_architecture'),
        ('medicines', '0015_medicine_log_reminder_state'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReminderTracking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference_type', models.CharField(choices=[('medicine', 'Medicine'), ('activity', 'Activity')], max_length=20)),
                ('reference_id', models.PositiveIntegerField(help_text='MedicineLog.id or ActivityLog.id')),
                ('scheduled_datetime', models.DateTimeField()),
                ('current_reminder_count', models.IntegerField(default=0)),
                ('last_popup_at', models.DateTimeField(blank=True, null=True)),
                ('next_popup_at', models.DateTimeField()),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('snoozed', 'Snoozed'), ('completed', 'Completed'), ('missed', 'Missed')], default='pending', max_length=20)),
                ('ignored_count', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reminder_trackings', to='accounts.customuser')),
            ],
            options={
                'db_table': 'reminder_tracking',
            },
        ),
        migrations.AddIndex(
            model_name='remindertracking',
            index=models.Index(fields=['patient', 'status', 'next_popup_at'], name='reminder_tr_patient_6a8b0d_idx'),
        ),
        migrations.AddIndex(
            model_name='remindertracking',
            index=models.Index(fields=['reference_type', 'reference_id'], name='reminder_tr_referen_8c4f2a_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='remindertracking',
            unique_together={('reference_type', 'reference_id')},
        ),
        migrations.RunPython(backfill_reminder_tracking, migrations.RunPython.noop),
    ]
