# Generated by Django 5.0.4 on 2024-05-02 22:03

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0047_alter_annotationfolder_folder'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='annotationfolder',
            name='folder',
        ),
        migrations.AddField(
            model_name='annotationfolder',
            name='parent_folder',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='child_folders', to='cc.annotationfolder'),
        ),
    ]
