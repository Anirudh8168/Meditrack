from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customuser',
            name='role',
            field=models.CharField(
                choices=[
                    ('patient', 'Patient'),
                    ('doctor', 'Doctor'),
                    ('admin', 'Admin'),
                    ('caregiver', 'Caregiver'),
                ],
                default='patient',
                max_length=20,
            ),
        ),
    ]
