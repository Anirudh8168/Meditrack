from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0003_patientprofile_enable_sos'),
    ]

    operations = [
        migrations.AddField(
            model_name='doctorprofile',
            name='video_consultation_fee',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='emergency_video_fee',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
    ]
