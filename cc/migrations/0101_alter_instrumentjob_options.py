# Generated by Django 5.1.6 on 2025-03-02 16:19

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0100_metadatacolumn_modifiers'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='instrumentjob',
            options={'ordering': ['-id']},
        ),
    ]
