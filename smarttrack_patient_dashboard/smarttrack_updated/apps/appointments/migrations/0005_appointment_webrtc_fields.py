from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("appointments", "0004_appointment_call_ended_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="doctor_joined_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appointment",
            name="patient_joined_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appointment",
            name="webrtc_answer",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="appointment",
            name="webrtc_ice_doctor",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="appointment",
            name="webrtc_ice_patient",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="appointment",
            name="webrtc_offer",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
