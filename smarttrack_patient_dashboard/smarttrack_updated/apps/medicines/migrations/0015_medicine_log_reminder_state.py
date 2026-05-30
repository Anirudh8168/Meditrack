from django.db import migrations, models


def dedupe_medicine_logs(apps, schema_editor):
    MedicineLog = apps.get_model('medicines', 'MedicineLog')
    seen = {}
    for log in MedicineLog.objects.order_by('-taken_at', '-created_at', '-id'):
        key = (log.medicine_id, log.scheduled_time)
        if key in seen:
            log.delete()
        else:
            seen[key] = log.id


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0014_dynamic_risk_analysis'),
    ]

    operations = [
        migrations.AlterField(
            model_name='medicinelog',
            name='status',
            field=models.CharField(
                choices=[
                    ('scheduled', 'Scheduled'),
                    ('taken', 'Taken'),
                    ('missed', 'Missed'),
                    ('skipped', 'Skipped'),
                ],
                default='scheduled',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='medicinelog',
            name='reminder_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='medicinelog',
            name='snoozed_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicinelog',
            name='last_popup_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(dedupe_medicine_logs, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name='medicinelog',
            unique_together={('medicine', 'scheduled_time')},
        ),
    ]
