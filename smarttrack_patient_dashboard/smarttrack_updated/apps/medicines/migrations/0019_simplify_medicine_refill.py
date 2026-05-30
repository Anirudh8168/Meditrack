# Remove bill upload and notes from medicine refills

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0018_medicine_low_stock_snooze'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='medicinerefill',
            name='bill_upload',
        ),
        migrations.RemoveField(
            model_name='medicinerefill',
            name='notes',
        ),
    ]
