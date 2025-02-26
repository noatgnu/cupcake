# Generated by Django 5.1.4 on 2025-02-26 20:25

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0098_labgroup_is_professional_labgroup_service_storage'),
    ]

    operations = [
        migrations.AddField(
            model_name='instrumentjob',
            name='service_lab_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instrument_jobs', to='cc.labgroup'),
        ),
    ]
