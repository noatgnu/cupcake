# Generated by Django 5.0.4 on 2024-05-13 16:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0055_annotation_summary'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='processing',
            field=models.BooleanField(default=False),
        ),
    ]
