# Generated by Django 5.0.3 on 2024-03-22 22:12

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0011_protocolstep_original'),
    ]

    operations = [
        migrations.AddField(
            model_name='protocolstep',
            name='branch_from',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='branch_steps', to='cc.protocolstep'),
        ),
    ]
