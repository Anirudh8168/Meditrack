from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0007_appointment_emergency_events'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='emergency_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('pending', 'Pending'),
                    ('accepted', 'Accepted'),
                    ('rejected', 'Rejected'),
                    ('timed_out', 'Timed Out'),
                ],
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='appointment',
            name='responded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='doctor_response',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='appointment',
            name='missed_reason',
            field=models.TextField(blank=True),
        ),
    ]
