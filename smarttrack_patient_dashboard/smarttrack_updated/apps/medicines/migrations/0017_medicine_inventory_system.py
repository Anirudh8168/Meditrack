# Generated manually for medicine inventory system

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_prescription_inventory(apps, schema_editor):
    Medicine = apps.get_model('medicines', 'Medicine')
    for med in Medicine.objects.all():
        if not med.prescribed_quantity:
            med.prescribed_quantity = max(med.stock_quantity or 0, 1)
        if not med.expected_end_date:
            med.expected_end_date = med.end_date
        if med.critical_stock_threshold > 3:
            pass
        med.save(update_fields=['prescribed_quantity', 'expected_end_date'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('medicines', '0016_reminder_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicine',
            name='expected_end_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicine',
            name='is_critical_medicine',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='medicine',
            name='last_low_stock_alert_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicine',
            name='prescribed_quantity',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='medicine',
            name='prescription_status',
            field=models.CharField(
                choices=[('active', 'Active'), ('expired', 'Expired'), ('stopped', 'Stopped')],
                default='active',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='medicine',
            name='refill_required',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='medicine',
            name='stock_depleted_at',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='medicine',
            name='total_refilled_quantity',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='medicine',
            name='units_per_dose',
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name='medicine',
            name='stock_quantity',
            field=models.IntegerField(default=30, help_text='Remaining stock (doses/units)'),
        ),
        migrations.CreateModel(
            name='MedicineRefill',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity_purchased', models.PositiveIntegerField()),
                ('purchase_date', models.DateField()),
                ('pharmacy_name', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('bill_upload', models.FileField(blank=True, null=True, upload_to='medicine_refills/')),
                ('is_partial', models.BooleanField(default=False)),
                ('stock_before', models.PositiveIntegerField(default=0)),
                ('stock_after', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('medicine', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='refills', to='medicines.medicine')),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='medicine_refills', to=settings.AUTH_USER_MODEL)),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recorded_refills', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-purchase_date', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MedicineInventoryEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('prescribed', 'Prescribed'), ('taken', 'Medicine Taken'), ('missed', 'Missed Medicine'), ('skipped', 'Skipped'), ('delayed', 'Delayed'), ('remind_later', 'Reminder Later'), ('refilled', 'Refilled'), ('low_stock_alert', 'Low Stock Alert')], max_length=20)),
                ('quantity_delta', models.IntegerField(default=0)),
                ('stock_after', models.IntegerField(default=0)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventory_actions', to=settings.AUTH_USER_MODEL)),
                ('medicine', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='inventory_events', to='medicines.medicine')),
                ('medicine_log', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventory_events', to='medicines.medicinelog')),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='medicine_inventory_events', to=settings.AUTH_USER_MODEL)),
                ('refill', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='events', to='medicines.medicinerefill')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='medicineinventoryevent',
            index=models.Index(fields=['patient', 'event_type', 'created_at'], name='medicines_m_patient_8a1f2c_idx'),
        ),
        migrations.AddIndex(
            model_name='medicineinventoryevent',
            index=models.Index(fields=['medicine', 'created_at'], name='medicines_m_medicin_4b3e9a_idx'),
        ),
        migrations.RunPython(backfill_prescription_inventory, migrations.RunPython.noop),
    ]
