# Generated by Django 5.1.4 on 2025-01-03 14:59

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0085_reagentaction_session'),
    ]

    operations = [
        migrations.AddField(
            model_name='storedreagent',
            name='created_by_step',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='created_reagents', to='cc.protocolstep'),
        ),
    ]
