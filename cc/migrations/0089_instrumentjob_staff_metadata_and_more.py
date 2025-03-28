# Generated by Django 5.1.4 on 2025-02-21 19:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0088_alter_instrumentjob_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='instrumentjob',
            name='staff_metadata',
            field=models.ManyToManyField(blank=True, related_name='assigned_instrument_jobs', to='cc.metadatacolumn'),
        ),
        migrations.AddField(
            model_name='instrumentjob',
            name='user_metadata',
            field=models.ManyToManyField(blank=True, related_name='instrument_jobs', to='cc.metadatacolumn'),
        ),
    ]
