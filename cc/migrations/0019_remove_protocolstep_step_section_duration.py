# Generated by Django 5.0.3 on 2024-03-27 12:13

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0018_protocolsection_alter_protocolstep_step_section'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='protocolstep',
            name='step_section_duration',
        ),
    ]
