from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0009_activity_log_last_popup_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='activitylog',
            name='start_proof_upload',
            field=models.FileField(blank=True, null=True, upload_to='activities/start_proof/'),
        ),
    ]
