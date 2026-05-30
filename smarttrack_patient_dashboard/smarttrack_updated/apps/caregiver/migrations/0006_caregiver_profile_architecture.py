from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('caregiver', '0005_caregiver_dashboard_redesign'),
        ('accounts', '0005_preferred_language'),
    ]

    operations = [
        migrations.AlterModelTable(name='caregiverprofile', table='caregiver_profile'),
        migrations.AddField(
            model_name='caregiverprofile',
            name='cg_id',
            field=models.CharField(blank=True, max_length=20, unique=True, null=True),
        ),
        migrations.AddField(
            model_name='caregiverprofile',
            name='full_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='caregiverprofile',
            name='organization_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='caregiverprofile',
            name='assigned_patient',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='primary_caregiver_profile_link', to='accounts.customuser',
                limit_choices_to={'role': 'patient'},
            ),
        ),
        migrations.AddField(
            model_name='caregiverprofile',
            name='access_level',
            field=models.CharField(blank=True, default='standard', max_length=30),
        ),
        migrations.AddField(
            model_name='caregiverprofile',
            name='assignment_start_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='caregiverprofile',
            name='assignment_end_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='caregiverprofile',
            name='assignment_status',
            field=models.CharField(blank=True, default='active', max_length=15),
        ),
        migrations.AddField(
            model_name='caregiverprofile',
            name='onboarding_completed',
            field=models.BooleanField(default=False),
        ),
    ]
