# Generated by Django 5.2.3 on 2025-06-27 14:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0134_alter_historicalmaintenancelog_maintenance_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalinstrument',
            name='accepts_bookings',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='instrument',
            name='accepts_bookings',
            field=models.BooleanField(default=True),
        ),
    ]
