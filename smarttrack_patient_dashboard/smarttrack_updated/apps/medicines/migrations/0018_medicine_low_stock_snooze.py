# Low-stock snooze until field for refill popup suppression

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0017_medicine_inventory_system'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicine',
            name='low_stock_snooze_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
