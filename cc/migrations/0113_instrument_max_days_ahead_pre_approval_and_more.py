# Generated by Django 5.1.6 on 2025-03-19 17:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0112_favouritemetadataoption_is_global'),
    ]

    operations = [
        migrations.AddField(
            model_name='instrument',
            name='max_days_ahead_pre_approval',
            field=models.IntegerField(blank=True, default=0, null=True),
        ),
        migrations.AddField(
            model_name='instrument',
            name='max_days_within_usage_pre_approval',
            field=models.IntegerField(blank=True, default=0, null=True),
        ),
        migrations.AddField(
            model_name='instrumentusage',
            name='approved',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='metadatatabletemplate',
            name='enabled',
            field=models.BooleanField(default=True),
        ),
    ]
