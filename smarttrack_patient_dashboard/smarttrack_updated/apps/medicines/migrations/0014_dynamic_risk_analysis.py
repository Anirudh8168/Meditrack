from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0013_risk_engine_redesign'),
    ]

    operations = [
        migrations.AddField(
            model_name='riskscore',
            name='dynamic_analysis',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='riskscorehistory',
            name='dynamic_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
