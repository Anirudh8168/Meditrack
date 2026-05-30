from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('family', '0001_initial'),
        ('accounts', '0005_preferred_language'),
    ]

    operations = [
        migrations.AlterModelTable(name='familymember', table='family_member_contact'),
        migrations.AddField(
            model_name='familymember',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.CreateModel(
            name='FamilyMemberProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('family_id', models.CharField(blank=True, max_length=20, unique=True)),
                ('full_name', models.CharField(blank=True, max_length=200)),
                ('relation', models.CharField(blank=True, max_length=50)),
                ('phone', models.CharField(blank=True, max_length=20)),
                ('permissions', models.JSONField(blank=True, default=dict)),
                ('profile_photo', models.ImageField(blank=True, null=True, upload_to='profiles/family/')),
                ('onboarding_completed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('linked_patient', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='linked_family_profiles', to='accounts.customuser',
                    limit_choices_to={'role': 'patient'},
                )),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='family_member_profile', to='accounts.customuser',
                )),
            ],
            options={'db_table': 'family_member_profile'},
        ),
    ]
