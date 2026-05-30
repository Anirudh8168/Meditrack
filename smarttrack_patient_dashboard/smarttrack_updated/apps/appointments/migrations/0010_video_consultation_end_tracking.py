from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_auth_user_architecture'),
        ('appointments', '0009_appointment_doctor_missed_alert_seen'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='call_duration_seconds',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='call_ended_by',
            field=models.CharField(blank=True, help_text='patient or doctor', max_length=10),
        ),
        migrations.AddField(
            model_name='appointment',
            name='video_call_status',
            field=models.CharField(
                blank=True,
                default='',
                help_text='not_started | active | ended',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='VideoConsultationHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('call_type', models.CharField(max_length=20)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('duration_seconds', models.PositiveIntegerField(default=0)),
                ('ended_by', models.CharField(blank=True, max_length=10)),
                ('completion_status', models.CharField(default='completed', max_length=30)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('appointment', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='consultation_history', to='appointments.appointment')),
                ('doctor', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='doctor_video_consultation_history', to='accounts.customuser')),
                ('patient', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='video_consultation_history', to='accounts.customuser')),
            ],
            options={
                'db_table': 'video_consultation_history',
                'ordering': ['-ended_at', '-created_at'],
            },
        ),
    ]
