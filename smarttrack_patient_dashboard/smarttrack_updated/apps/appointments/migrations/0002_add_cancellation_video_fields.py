from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='cancelled_by',
            field=models.CharField(
                blank=True, max_length=10,
                choices=[('patient', 'Patient'), ('doctor', 'Doctor'), ('system', 'System')],
                default='',
            ),
        ),
        migrations.AddField(
            model_name='appointment',
            name='cancellation_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='appointment',
            name='cancelled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='appointment',
            name='video_link',
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='appointment',
            name='video_session_id',
            field=models.CharField(blank=True, max_length=100, default=''),
        ),
        migrations.AddField(
            model_name='appointment',
            name='is_emergency',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='appointment',
            name='emergency_notes',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='appointment',
            name='appointment_type',
            field=models.CharField(
                max_length=20, default='in_person',
                choices=[('in_person', 'In Person'), ('video', 'Video Call'), ('emergency_video', 'Emergency Video')],
            ),
        ),
        migrations.CreateModel(
            name='DoctorSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day_of_week', models.CharField(
                    max_length=10,
                    choices=[('monday', 'Monday'), ('tuesday', 'Tuesday'), ('wednesday', 'Wednesday'),
                             ('thursday', 'Thursday'), ('friday', 'Friday'), ('saturday', 'Saturday'), ('sunday', 'Sunday')],
                )),
                ('start_time', models.TimeField()),
                ('end_time', models.TimeField()),
                ('slot_duration_minutes', models.IntegerField(default=30)),
                ('max_appointments', models.IntegerField(default=10)),
                ('is_available', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('doctor', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='schedules',
                    to='accounts.customuser',
                )),
            ],
            options={'ordering': ['day_of_week', 'start_time']},
        ),
    ]
