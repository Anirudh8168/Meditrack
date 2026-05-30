from django.db import migrations, models
import django.db.models.deletion


def dedupe_risk_scores(apps, schema_editor):
    RiskScore = apps.get_model('medicines', 'RiskScore')
    seen = set()
    for row in RiskScore.objects.order_by('patient_id', '-recorded_at', '-id'):
        if row.patient_id in seen:
            row.delete()
        else:
            seen.add(row.patient_id)


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0012_health_risk_alert'),
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RiskScoreHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.IntegerField(default=0)),
                ('level', models.CharField(default='low', max_length=10)),
                ('risk_types', models.JSONField(blank=True, default=list)),
                ('component_scores', models.JSONField(blank=True, default=dict)),
                ('reasons', models.JSONField(blank=True, default=list)),
                ('recorded_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='risk_history', to='accounts.customuser')),
            ],
            options={
                'ordering': ['-recorded_at'],
            },
        ),
        migrations.AddField(
            model_name='riskscore',
            name='component_scores',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='riskscore',
            name='disease_context',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='riskscore',
            name='health_impacts',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='riskscore',
            name='level_message',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='riskscore',
            name='reasons',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='riskscore',
            name='recommended_actions',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='riskscore',
            name='risk_types',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(dedupe_risk_scores, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='riskscore',
            name='patient',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='risk_score', to='accounts.customuser'),
        ),
        migrations.AlterField(
            model_name='riskscore',
            name='recorded_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddIndex(
            model_name='riskscore',
            index=models.Index(fields=['level', 'score'], name='medicines_r_level_8a2f1d_idx'),
        ),
        migrations.AddIndex(
            model_name='riskscorehistory',
            index=models.Index(fields=['patient', 'recorded_at'], name='medicines_r_patient_4c8e2a_idx'),
        ),
    ]
