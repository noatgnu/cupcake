# Generated by Django 5.0.3 on 2024-04-17 12:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0033_session_ended_at_session_started_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stepannotation',
            name='annotation_type',
            field=models.CharField(choices=[('text', 'Text'), ('file', 'File'), ('image', 'Image'), ('video', 'Video'), ('audio', 'Audio'), ('sketch', 'Sketch'), ('other', 'Other'), ('checklist', 'Checklist'), ('counter', 'Counter'), ('table', 'Table'), ('alignment', 'Alignment')], default='text', max_length=10),
        ),
    ]
