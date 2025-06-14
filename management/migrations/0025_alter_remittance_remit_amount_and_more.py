# Generated by Django 5.0.6 on 2025-05-30 10:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('management', '0024_alter_remittance_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='remittance',
            name='remit_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='remittance',
            name='savings_amount',
            field=models.DecimalField(blank=True, decimal_places=2, default=0, max_digits=10, null=True),
        ),
    ]
