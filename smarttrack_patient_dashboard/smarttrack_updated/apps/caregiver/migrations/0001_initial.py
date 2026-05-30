from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CaregiverProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('caregiver_type', models.CharField(choices=[('hospital', 'Hospital Caregiver'), ('personal', 'Personal Caregiver')], default='personal', max_length=20)),
                ('relation', models.CharField(choices=[('nurse', 'Nurse'), ('hospital_staff', 'Hospital Staff'), ('family_member', 'Family Member'), ('friend', 'Friend'), ('hired', 'Hired Caregiver'), ('other', 'Other')], default='family_member', max_length=30)),
                ('license_number', models.CharField(blank=True, max_length=50)),
                ('hospital_name', models.CharField(blank=True, max_length=200)),
                ('phone', models.CharField(blank=True, max_length=20)),
                ('address', models.TextField(blank=True)),
                ('bio', models.TextField(blank=True)),
                ('profile_photo', models.ImageField(blank=True, null=True, upload_to='profiles/caregivers/')),
                ('is_available', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='caregiver_profile', to='accounts.customuser')),
            ],
        ),
        migrations.CreateModel(
            name='CaregiverPatientAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('active', 'Active'), ('inactive', 'Inactive'), ('pending', 'Pending')], default='pending', max_length=10)),
                ('notes', models.TextField(blank=True)),
                ('can_mark_medicines', models.BooleanField(default=True)),
                ('can_manage_appointments', models.BooleanField(default=True)),
                ('can_upload_reports', models.BooleanField(default=True)),
                ('can_log_activities', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('caregiver', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='caregiver_assignments', to='accounts.customuser')),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='caregiver_patient_assignments', to='accounts.customuser')),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='caregiver_assigned_by', to='accounts.customuser')),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('caregiver', 'patient')},
            },
        ),
    ]
