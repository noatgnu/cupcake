# Generated by Django 5.0.4 on 2024-04-20 18:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0034_alter_stepannotation_annotation_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stepannotation',
            name='annotation_type',
            field=models.CharField(choices=[('text', 'Text'), ('file', 'File'), ('image', 'Image'), ('video', 'Video'), ('audio', 'Audio'), ('sketch', 'Sketch'), ('other', 'Other'), ('checklist', 'Checklist'), ('counter', 'Counter'), ('table', 'Table'), ('alignment', 'Alignment'), ('calculator', 'Calculator')], default='text', max_length=10),
        ),
    ]
