# Generated by Django 5.1.4 on 2025-02-20 18:57

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0086_storedreagent_created_by_step'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InstrumentJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_type', models.CharField(choices=[('maintenance', 'Maintenance'), ('analysis', 'Analysis'), ('other', 'Other')], default='analysis', max_length=20)),
                ('assigned', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('completed', 'Completed'), ('in_progress', 'In Progress'), ('cancelled', 'Cancelled')], default='pending', max_length=20)),
                ('job_name', models.TextField(blank=True, null=True)),
                ('instrument', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instrument_jobs', to='cc.instrument')),
                ('instrument_usage', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instrument_jobs', to='cc.instrumentusage')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instrument_jobs', to='cc.project')),
                ('protocol', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instrument_jobs', to='cc.protocolmodel')),
                ('session', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instrument_jobs', to='cc.session')),
                ('staff', models.ManyToManyField(blank=True, related_name='assigned_instrument_jobs', to=settings.AUTH_USER_MODEL)),
                ('staff_annotations', models.ManyToManyField(blank=True, related_name='assigned_instrument_jobs', to='cc.annotation')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instrument_jobs', to=settings.AUTH_USER_MODEL)),
                ('user_annotations', models.ManyToManyField(blank=True, related_name='instrument_jobs', to='cc.annotation')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
