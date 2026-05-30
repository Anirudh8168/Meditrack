from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0001_initial'),
    ]

    operations = [
        # Add critical_stock_threshold to Medicine
        migrations.AddField(
            model_name='medicine',
            name='critical_stock_threshold',
            field=models.IntegerField(default=3),
        ),

        # Add marked_by to MedicineLog
        migrations.AddField(
            model_name='medicinelog',
            name='marked_by',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='marked_logs',
                to='accounts.customuser',
            ),
        ),

        # DailyHealthCheck model
        migrations.CreateModel(
            name='DailyHealthCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('feeling', models.CharField(
                    max_length=10,
                    choices=[('good', 'Good'), ('okay', 'Okay'), ('not_good', 'Not Good')],
                )),
                ('notes', models.TextField(blank=True)),
                ('symptoms', models.JSONField(default=list, blank=True)),
                ('checked_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='health_checks',
                    to='accounts.customuser',
                )),
            ],
            options={'ordering': ['-checked_at']},
        ),

        # FamilyContact model
        migrations.CreateModel(
            name='FamilyContact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('phone', models.CharField(max_length=20, blank=True)),
                ('email', models.EmailField(blank=True)),
                ('relation', models.CharField(
                    max_length=15, default='other',
                    choices=[('spouse', 'Spouse'), ('parent', 'Parent'), ('child', 'Child'),
                             ('sibling', 'Sibling'), ('friend', 'Friend'), ('caregiver', 'Caregiver'), ('other', 'Other')],
                )),
                ('is_primary', models.BooleanField(default=False)),
                ('notify_on_missed', models.BooleanField(default=True)),
                ('missed_count_threshold', models.IntegerField(default=3)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='family_contacts',
                    to='accounts.customuser',
                )),
            ],
            options={'ordering': ['-is_primary', 'name']},
        ),

        # MissedAlertLog model
        migrations.CreateModel(
            name='MissedAlertLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('alert_type', models.CharField(max_length=30, default='missed_medicine')),
                ('sent_to', models.JSONField(default=list)),
                ('message', models.TextField()),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='missed_alert_logs',
                    to='accounts.customuser',
                )),
                ('medicine', models.ForeignKey(
                    null=True, blank=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='missed_alerts',
                    to='medicines.medicine',
                )),
            ],
            options={'ordering': ['-sent_at']},
        ),
    ]
