# Generated by Django 5.1.6 on 2025-03-01 18:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0099_instrumentjob_service_lab_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='metadatacolumn',
            name='modifiers',
            field=models.TextField(blank=True, null=True),
        ),
    ]
