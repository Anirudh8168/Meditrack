# Generated migration — prescription ≠ stock; MedicinePurchase history

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_purchases_from_refills(apps, schema_editor):
    """Create MedicinePurchase rows from existing refills for historical continuity."""
    MedicineRefill = apps.get_model('medicines', 'MedicineRefill')
    MedicinePurchase = apps.get_model('medicines', 'MedicinePurchase')
    for refill in MedicineRefill.objects.all().iterator():
        if MedicinePurchase.objects.filter(refill_id=refill.id).exists():
            continue
        MedicinePurchase.objects.create(
            medicine_id=refill.medicine_id,
            patient_id=refill.patient_id,
            purchase_quantity=refill.quantity_purchased,
            purchase_date=refill.purchase_date,
            previous_stock=refill.stock_before,
            updated_stock=refill.stock_after,
            pharmacy_name=refill.pharmacy_name or '',
            notes='',
            recorded_by_id=refill.recorded_by_id,
            refill_id=refill.id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('medicines', '0019_simplify_medicine_refill'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='medicine',
            name='stock_quantity',
            field=models.IntegerField(
                default=0,
                help_text='Available stock (doses/units) — set only via patient purchase',
            ),
        ),
        migrations.CreateModel(
            name='MedicinePurchase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('purchase_quantity', models.PositiveIntegerField()),
                ('purchase_date', models.DateField()),
                ('previous_stock', models.PositiveIntegerField(default=0)),
                ('updated_stock', models.PositiveIntegerField(default=0)),
                ('pharmacy_name', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('medicine', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='purchases', to='medicines.medicine')),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='medicine_purchases', to=settings.AUTH_USER_MODEL)),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recorded_purchases', to=settings.AUTH_USER_MODEL)),
                ('refill', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='purchase_record', to='medicines.medicinerefill')),
            ],
            options={
                'ordering': ['-purchase_date', '-created_at'],
            },
        ),
        migrations.RunPython(backfill_purchases_from_refills, migrations.RunPython.noop),
    ]
