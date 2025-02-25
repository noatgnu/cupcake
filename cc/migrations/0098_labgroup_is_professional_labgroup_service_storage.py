# Generated by Django 5.1.4 on 2025-02-25 21:30

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0097_storageobject_access_lab_groups'),
    ]

    operations = [
        migrations.AddField(
            model_name='labgroup',
            name='is_professional',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='labgroup',
            name='service_storage',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='service_lab_groups', to='cc.storageobject'),
        ),
    ]
