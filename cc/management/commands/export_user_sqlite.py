import os
import sys
import time
import shutil
import subprocess
import copy

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connections, IntegrityError
from django.core.serializers import serialize, deserialize

from django.apps import apps

User = get_user_model()  # Use custom user model if applicable

class Command(BaseCommand):
    help = 'Export data associated with a specific user into an SQLite database and the associated media files into a folder.'

    def add_arguments(self, parser):
        parser.add_argument('user_id', type=str, help='The ID of the user to export')
        parser.add_argument('export_dir', type=str, help='The directory to export the data to')

    def handle(self, *args, **kwargs):
        user_id = kwargs['user_id']
        export_dir = kwargs['export_dir']
        start_time = int(time.time())

        alias = self.export_to_sqlite(user_id, export_dir)
        self.copy_data_to_sqlite(user_id, alias)

        self.stdout.write(self.style.SUCCESS(f"Backup completed in {export_dir}"))

    def export_to_sqlite(self, user_id, export_dir):
        """ Creates a fresh SQLite database using Django migrations. """
        if os.path.exists(export_dir):
            shutil.rmtree(export_dir)
        os.makedirs(export_dir)

        sqlite_db_path = os.path.join(export_dir, 'exported_data.sqlite3')
        sqlite_db_alias = self.configure_sqlite_db(user_id, sqlite_db_path)
        # Set up environment variables for SQLite migration
        env = copy.deepcopy(os.environ)
        env['SQLITE_DB_PATH'] = sqlite_db_path
        env['PYTHONPATH'] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['VIRTUAL_ENV'] = os.getenv('VIRTUAL_ENV', '')
        env['PATH'] = os.path.dirname(sys.executable) + os.pathsep + env['PATH']

        # Run migrations to create SQLite schema
        subprocess.run(
            [sys.executable, 'manage.py', 'migrate', '--database=backup_db', '--noinput'],
            env=env,
            check=True
        )
        return sqlite_db_alias

    def configure_sqlite_db(self, user_id, sqlite_db_path):

        # Dynamically update the DATABASES dictionary
        settings.DATABASES[f'backup_db_{user_id}'] = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': sqlite_db_path,
            'TIME_ZONE': settings.TIME_ZONE,
            'CONN_HEALTH_CHECKS': False,
            'CONN_MAX_AGE': 0,
            'AUTOCOMMIT': True,
            'OPTIONS': {
                'timeout': 30,
            },
        }

        # Register the new DB in Django's connections
        connections.databases[f'backup_db_{user_id}'] = settings.DATABASES[f'backup_db_{user_id}']

        return f'backup_db_{user_id}'

    def copy_data_to_sqlite(self, user_id, sqlite_db_alias):
        """ Copies user data and related objects from PostgreSQL to the dynamic SQLite database. """
        postgres_db = "default"

        try:
            user = User.objects.using(postgres_db).get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR("User not found."))
            return

        exported_objects = set()

        def export_object(obj, ignore_labels=None):
            """ Recursively export an object and its related objects. """

            if ignore_labels:
                if obj._meta.label in ignore_labels:
                    return
            obj_id = f"{obj._meta.label}:{obj.pk}"
            if obj_id in exported_objects:
                return  # Avoid duplicates
            print(exported_objects)
            exported_objects.add(obj_id)
            print(obj_id)
            # Serialize and insert into the dynamically assigned SQLite DB
            obj_json = serialize("json", [obj])
            print(obj_json)

            for deserialized_obj in deserialize("json", obj_json):
                if "auth.User" == obj._meta.label:
                    try:
                        deserialized_obj.save(using=sqlite_db_alias)
                    except IntegrityError:
                        pass
                else:
                    deserialized_obj.save(using=sqlite_db_alias)


            # Export related objects (Foreign Key & OneToOne)
            for rel in obj._meta.related_objects:
                related_name = rel.get_accessor_name()
                related_manager = getattr(obj, related_name, None)

                if related_manager is not None:
                    if rel.one_to_one:
                        related_obj = related_manager
                        if related_obj:
                            export_object(related_obj, ["auth.User"])
                    else:
                        for related_obj in related_manager.all():
                            export_object(related_obj, ["auth.User"])

        def export_m2m_relationships(obj):
            """ Export many-to-many relationships for an object. """
            for m2m in obj._meta.many_to_many:
                related_manager = getattr(obj, m2m.name, None)
                if related_manager is not None:
                    for related_obj in related_manager.all():
                        obj_json = serialize("json", [related_obj])
                        for deserialized_obj in deserialize("json", obj_json):
                            try:
                                deserialized_obj.save(using=sqlite_db_alias)
                            except IntegrityError:
                                pass
                        # Add the relationship in the SQLite database
                        getattr(obj, m2m.name).add(related_obj)

        # Start export with the user
        export_object(user)

        # Reestablish many-to-many relationships
        for obj_id in exported_objects:
            model_label, pk = obj_id.split(":")
            model = apps.get_model(model_label)
            try:
                obj = model.objects.using(postgres_db).get(pk=pk)
            except model.DoesNotExist:
                continue
            export_m2m_relationships(obj)

        self.stdout.write(
            self.style.SUCCESS(f"User {user_id} and related data exported successfully to {sqlite_db_alias}."))