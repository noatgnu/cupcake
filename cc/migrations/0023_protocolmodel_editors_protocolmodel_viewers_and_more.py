# Generated by Django 5.0.3 on 2024-03-28 09:11

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cc', '0022_alter_protocolmodel_protocol_created_on_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='protocolmodel',
            name='editors',
            field=models.ManyToManyField(blank=True, related_name='editor_protocols', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='protocolmodel',
            name='viewers',
            field=models.ManyToManyField(blank=True, related_name='viewer_protocols', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='session',
            name='editors',
            field=models.ManyToManyField(blank=True, related_name='editor_sessions', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='session',
            name='viewers',
            field=models.ManyToManyField(blank=True, related_name='viewer_sessions', to=settings.AUTH_USER_MODEL),
        ),
    ]
