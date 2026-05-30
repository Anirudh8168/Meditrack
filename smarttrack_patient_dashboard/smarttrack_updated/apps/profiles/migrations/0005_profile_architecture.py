from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0004_doctor_consultation_fees'),
        ('accounts', '0005_preferred_language'),
    ]

    operations = [
        migrations.AlterModelTable(name='patientprofile', table='patient_profile'),
        migrations.AlterModelTable(name='doctorprofile', table='doctor_profile'),
        migrations.AddField(
            model_name='patientprofile',
            name='patient_id',
            field=models.CharField(blank=True, max_length=20, unique=True, null=True),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='first_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='middle_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='last_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='phone_number',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='alternate_number',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='age_cached',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='medical_conditions',
            field=models.TextField(blank=True, help_text='Primary / secondary conditions summary'),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='emergency_contact_number',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='preferred_hospital',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='assigned_doctor',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_patients', to='accounts.customuser',
                limit_choices_to={'role': 'doctor'},
            ),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='risk_level',
            field=models.CharField(
                blank=True, choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')],
                default='low', max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='risk_score',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='patientprofile',
            name='onboarding_completed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='doctor_id',
            field=models.CharField(blank=True, max_length=20, unique=True, null=True),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='full_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='specialization',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='qualification',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='registration_number',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='emergency_fee',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='phone',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='clinic_address',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='availability_schedule',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='rating',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=3, null=True),
        ),
        migrations.AddField(
            model_name='doctorprofile',
            name='onboarding_completed',
            field=models.BooleanField(default=False),
        ),
    ]
