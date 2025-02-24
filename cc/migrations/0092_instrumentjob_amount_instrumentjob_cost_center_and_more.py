# Generated by Django 5.1.4 on 2025-02-21 20:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0091_annotation_fixed'),
    ]

    operations = [
        migrations.AddField(
            model_name='instrumentjob',
            name='amount',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='instrumentjob',
            name='cost_center',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='instrumentjob',
            name='funder',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='instrumentjob',
            name='unit',
            field=models.TextField(blank=True, null=True),
        ),
    ]
