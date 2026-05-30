from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0011_activity_log_missed_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='HealthRiskAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('risk_score', models.IntegerField(default=0)),
                ('risk_level', models.CharField(default='high', max_length=10)),
                ('escalation_level', models.IntegerField(default=3)),
                ('medicines_missed_count', models.IntegerField(default=0)),
                ('consecutive_misses', models.IntegerField(default=0)),
                ('reason', models.TextField(blank=True)),
                ('message', models.TextField()),
                ('doctor_name', models.CharField(blank=True, max_length=150)),
                ('recipients', models.JSONField(default=list)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='health_risk_alerts', to='accounts.customuser')),
                ('trigger_medicine', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='risk_alerts', to='medicines.medicine')),
            ],
            options={
                'ordering': ['-sent_at'],
            },
        ),
    ]
