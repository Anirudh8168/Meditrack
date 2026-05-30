# Generated for professional payment workflow

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='consultationpayment',
            name='otp_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='consultationpayment',
            name='receipt_id',
            field=models.CharField(blank=True, max_length=32, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='consultationpayment',
            name='verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='consultationpayment',
            name='payment_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('processing', 'Processing'),
                    ('paid', 'Paid'),
                    ('failed', 'Failed'),
                    ('refunded', 'Refunded'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=15,
            ),
        ),
    ]
