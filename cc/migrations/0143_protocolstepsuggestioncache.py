# Generated by Django 5.2.4 on 2025-07-15 17:35

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0142_celltype_chebicompound_mondodisease_ncbitaxonomy_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProtocolStepSuggestionCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('analyzer_type', models.CharField(choices=[('standard_nlp', 'Standard NLP'), ('mcp_claude', 'MCP Claude'), ('anthropic_claude', 'Anthropic Claude')], max_length=50)),
                ('sdrf_suggestions', models.JSONField(default=dict, help_text='Cached SDRF suggestions')),
                ('analysis_metadata', models.JSONField(default=dict, help_text='Analysis metadata')),
                ('extracted_terms', models.JSONField(default=list, help_text='Extracted terms')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_valid', models.BooleanField(default=True, help_text='Whether cache is still valid')),
                ('step_content_hash', models.CharField(help_text='Hash of step description for cache invalidation', max_length=64)),
                ('step', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='suggestion_cache', to='cc.protocolstep')),
            ],
            options={
                'ordering': ['-updated_at'],
                'indexes': [models.Index(fields=['step', 'analyzer_type'], name='cc_protocol_step_id_e9d384_idx'), models.Index(fields=['step', 'is_valid'], name='cc_protocol_step_id_e13829_idx'), models.Index(fields=['created_at'], name='cc_protocol_created_9b63a7_idx')],
                'unique_together': {('step', 'analyzer_type')},
            },
        ),
    ]
