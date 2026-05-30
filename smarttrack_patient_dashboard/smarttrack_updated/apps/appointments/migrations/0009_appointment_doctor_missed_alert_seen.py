from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0008_emergency_timeout_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='doctor_missed_alert_seen',
            field=models.BooleanField(default=False),
        ),
    ]
