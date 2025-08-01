# Generated by Django 5.2.4 on 2025-07-17 20:38

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0146_historicalsitesettings_backup_frequency_days_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SamplePool',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pool_name', models.CharField(help_text='Name of the sample pool', max_length=255)),
                ('pool_description', models.TextField(blank=True, help_text='Optional description of the pool', null=True)),
                ('pooled_only_samples', models.JSONField(default=list, help_text='Sample indices that exist only in this pool')),
                ('pooled_and_independent_samples', models.JSONField(default=list, help_text='Sample indices that are both pooled and independent')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('instrument_job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sample_pools', to='cc.instrumentjob')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['instrument_job', 'pool_name'], name='cc_samplepo_instrum_1b6b1c_idx'), models.Index(fields=['created_at'], name='cc_samplepo_created_ff4efd_idx')],
                'unique_together': {('instrument_job', 'pool_name')},
            },
        ),
    ]
