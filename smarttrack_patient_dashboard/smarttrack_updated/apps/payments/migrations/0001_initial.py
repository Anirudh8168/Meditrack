import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('appointments', '0009_appointment_doctor_missed_alert_seen'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ConsultationPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('payment_id', models.CharField(editable=False, max_length=32, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('currency', models.CharField(default='INR', max_length=3)),
                ('payment_type', models.CharField(choices=[('video', 'Video Consultation'), ('emergency_video', 'Emergency Video Consultation')], max_length=20)),
                ('appointment_type', models.CharField(max_length=20)),
                ('payment_gateway', models.CharField(default='razorpay', max_length=30)),
                ('gateway_order_id', models.CharField(blank=True, max_length=100)),
                ('transaction_id', models.CharField(blank=True, max_length=100)),
                ('payment_method', models.CharField(blank=True, choices=[('upi', 'UPI'), ('card', 'Credit/Debit Card'), ('netbanking', 'Net Banking'), ('wallet', 'Wallet'), ('razorpay', 'Razorpay'), ('demo', 'Demo Payment')], max_length=20)),
                ('payment_status', models.CharField(choices=[('pending', 'Pending'), ('paid', 'Paid'), ('failed', 'Failed'), ('refunded', 'Refunded')], default='pending', max_length=15)),
                ('tax_amount', models.DecimalField(decimal_places=2, default='0.00', max_digits=10)),
                ('reminder_sent_at', models.DateTimeField(blank=True, null=True)),
                ('failure_reason', models.TextField(blank=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('appointment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='consultation_payment', to='appointments.appointment')),
                ('caregiver', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='caregiver_payments_made', to=settings.AUTH_USER_MODEL)),
                ('doctor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='doctor_payments_received', to=settings.AUTH_USER_MODEL)),
                ('paid_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payments_made', to=settings.AUTH_USER_MODEL)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consultation_payments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='consultationpayment',
            index=models.Index(fields=['payment_status', 'doctor'], name='payments_co_status_7a1b0d_idx'),
        ),
        migrations.AddIndex(
            model_name='consultationpayment',
            index=models.Index(fields=['payment_status', 'patient'], name='payments_co_status_8b2c1e_idx'),
        ),
        migrations.AddIndex(
            model_name='consultationpayment',
            index=models.Index(fields=['created_at'], name='payments_co_created_9c3d2f_idx'),
        ),
    ]
