# Generated by Django 5.0.6 on 2024-06-08 14:24

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0070_storageobject_user_alter_storageobject_object_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='storedreagent',
            name='shareable',
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name='ReagentAction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action_type', models.CharField(choices=[('add', 'Add'), ('reserve', 'Reserve')], default='add', max_length=20)),
                ('quantity', models.FloatField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('reagent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reagent_actions', to='cc.storedreagent')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='reagent_actions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
