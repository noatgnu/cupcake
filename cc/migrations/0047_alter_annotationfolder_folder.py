# Generated by Django 5.0.4 on 2024-05-02 21:29

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0046_stepannotation_annotation_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='annotationfolder',
            name='folder',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='parent_folder', to='cc.annotationfolder'),
        ),
    ]
