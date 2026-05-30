from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0008_activity_log_snoozed_until'),
    ]

    operations = [
        migrations.AddField(
            model_name='activitylog',
            name='last_popup_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
