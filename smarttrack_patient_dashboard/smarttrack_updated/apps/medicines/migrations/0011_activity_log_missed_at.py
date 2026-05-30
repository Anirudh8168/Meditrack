from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0010_activity_log_start_proof'),
    ]

    operations = [
        migrations.AddField(
            model_name='activitylog',
            name='missed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
