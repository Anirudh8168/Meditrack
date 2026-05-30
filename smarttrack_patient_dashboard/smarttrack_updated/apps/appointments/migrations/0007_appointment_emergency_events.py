from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0006_appointment_approval_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='emergency_events',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
