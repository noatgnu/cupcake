# Generated by Django 5.0.3 on 2024-03-22 22:24

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0012_protocolstep_branch_from'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='protocols',
            field=models.ManyToManyField(blank=True, related_name='sessions', to='cc.protocolmodel'),
        ),
    ]
