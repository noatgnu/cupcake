import sys
import os
import copy
import sqlite3
import subprocess
import tarfile

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models
from django.db import connections
from shutil import copyfile
from cc.models import Session, ProtocolModel, ProtocolStep, ProtocolSection, AnnotationFolder, Annotation, TimeKeeper, \
    StoredReagent, ReagentAction, StepVariation, ProtocolRating, ProtocolReagent, StepReagent, Reagent, StorageObject, \
    MetadataColumn, Instrument, InstrumentUsage

import hashlib
from django.core.signing import Signer
import time
import shutil

class Command(BaseCommand):
    help = 'Export data associated with a specific session or project into an SQLite database and the associated media files into a folder.'

    def add_arguments(self, parser):
        parser.add_argument('unique_id', type=str, help='The unique ID of the session to export')
        parser.add_argument('export_dir', type=str, help='The directory to export the data to')

    def handle(self, *args, **kwargs):
        unique_id = kwargs['unique_id']
        export_dir = kwargs['export_dir']
        start_time = int(time.time())
        self.export_to_sqlite(unique_id, export_dir)
        self.create_and_sign_hash(export_dir, start_time)
        self.compress_export_dir(export_dir)

    def export_to_sqlite(self, unique_id, export_dir):
        if os.path.exists(export_dir):
            shutil.rmtree(export_dir)
        os.makedirs(export_dir)

        sqlite_db_path = os.path.join(export_dir, 'exported_data.sqlite3')
        # Clear the folder if it already exists


        env = copy.deepcopy(os.environ)
        env['SQLITE_DB_PATH'] = sqlite_db_path
        env['PYTHONPATH'] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['VIRTUAL_ENV'] = os.getenv('VIRTUAL_ENV', '')
        env['PATH'] = os.path.dirname(sys.executable) + os.pathsep + env['PATH']

        subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], env=env, check=True)
        self.export_data_to_sqlite(unique_id, sqlite_db_path, export_dir)

    def export_data_to_sqlite(self, unique_id, sqlite_db_path, export_dir):
        with connections['default'].cursor() as django_cursor:
            django_cursor.execute('SELECT * FROM cc_session WHERE unique_id = %s', [unique_id])
            session = django_cursor.fetchone()
            if session:
                session_id = session[0]
                columns = [col[0] for col in django_cursor.description]
                session = list(session)
                session[columns.index('unique_id')] = str(session[columns.index('unique_id')])  # Convert UUID to string
                with sqlite3.connect(sqlite_db_path) as conn:
                    cursor = conn.cursor()
                    placeholders = ', '.join(['?'] * len(columns))
                    cursor.executemany(f'INSERT INTO cc_session ({", ".join(columns)}) VALUES ({placeholders})', [session])
                    conn.commit()
                    self.get_session_related_data(django_cursor, session_id, conn)
                    self.export_media_files(unique_id, export_dir, conn)


    def get_session_related_data(self, django_cursor, session_id, conn):
        session = Session.objects.get(id=session_id)
        # Get all TimeKeepers associated with this Session and export them
        time_keeper_table_name = TimeKeeper._meta.db_table
        django_cursor.execute(f'SELECT * FROM {time_keeper_table_name} WHERE session_id = %s', [session_id])
        time_keepers = django_cursor.fetchall()
        time_keeper_columns = [col[0] for col in django_cursor.description]
        time_keeper_placeholders = ', '.join(['?'] * len(time_keeper_columns))
        cursor = conn.cursor()
        cursor.executemany(f'INSERT INTO {time_keeper_table_name} ({", ".join(time_keeper_columns)}) VALUES ({time_keeper_placeholders})', time_keepers)
        conn.commit()

        # Get all AnnotationFolders associated with this Session and export them
        annotation_folder_table_name = AnnotationFolder._meta.db_table
        django_cursor.execute(f'SELECT * FROM {annotation_folder_table_name} WHERE session_id = %s', [session_id])
        annotation_folders = django_cursor.fetchall()
        annotation_folder_columns = [col[0] for col in django_cursor.description]
        annotation_folder_placeholders = ', '.join(['?'] * len(annotation_folder_columns))
        annotations = []
        metadata_columns = []
        metadata_column_columns = []
        metadata_columns_placeholders = ''
        if annotation_folders:
            cursor.executemany(f'INSERT INTO {annotation_folder_table_name} ({", ".join(annotation_folder_columns)}) VALUES ({annotation_folder_placeholders})', annotation_folders)
            conn.commit()
            # Export Annotations associated to AnnotationFolders
            annotation_table_name = Annotation._meta.db_table
            django_cursor.execute(f'SELECT * FROM {annotation_table_name} WHERE folder_id IN ({", ".join(["%s"] * len(annotation_folders))})', [folder[0] for folder in annotation_folders])
            annotations = django_cursor.fetchall()
            annotation_columns = [col[0] for col in django_cursor.description]
            annotation_placeholders = ', '.join(['?'] * len(annotation_columns))
            if annotations:
                cursor.executemany(f'INSERT INTO {annotation_table_name} ({", ".join(annotation_columns)}) VALUES ({annotation_placeholders})', annotations)
                conn.commit()

        for f in Session._meta.get_fields():
            if isinstance(f, models.ManyToManyField):
                related_table = f.remote_field.through._meta.db_table
                django_cursor.execute(f'SELECT * FROM {related_table} WHERE session_id = %s', [session_id])
                related_rows = django_cursor.fetchall()
                related_columns = [col[0] for col in django_cursor.description]
                related_placeholders = ', '.join(['?'] * len(related_columns))
                if related_rows:
                    cursor.executemany(f'INSERT INTO {related_table} ({", ".join(related_columns)}) VALUES ({related_placeholders})', related_rows)
                    conn.commit()
                    if f.name == 'protocols':

                        position_of_protocol = related_columns.index('protocolmodel_id')
                        protocol_ids = [related_row[position_of_protocol] for related_row in related_rows]

                        for related_row in related_rows:
                            # Export ProtocolStep of this Protocol
                            protocol_step_table_name = ProtocolStep._meta.db_table
                            django_cursor.execute(f'SELECT * FROM {protocol_step_table_name} WHERE protocol_id = %s', [related_row[position_of_protocol]])
                            protocol_steps = django_cursor.fetchall()
                            protocol_step_columns = [col[0] for col in django_cursor.description]
                            protocol_step_placeholders = ', '.join(['?'] * len(protocol_step_columns))
                            cursor.executemany(f'INSERT INTO {protocol_step_table_name} ({", ".join(protocol_step_columns)}) VALUES ({protocol_step_placeholders})', protocol_steps)
                            # Export ProtocolSection of this Protocol
                            protocol_section_table_name = ProtocolSection._meta.db_table
                            django_cursor.execute(f'SELECT * FROM {protocol_section_table_name} WHERE protocol_id = %s', [related_row[position_of_protocol]])
                            protocol_sections = django_cursor.fetchall()
                            protocol_section_columns = [col[0] for col in django_cursor.description]
                            protocol_section_placeholders = ', '.join(['?'] * len(protocol_section_columns))
                            cursor.executemany(f'INSERT INTO {protocol_section_table_name} ({", ".join(protocol_section_columns)}) VALUES ({protocol_section_placeholders})', protocol_sections)
                            # Export StepVariation of these ProtocolSteps
                            step_variation_table_name = StepVariation._meta.db_table
                            django_cursor.execute(f'SELECT * FROM {step_variation_table_name} WHERE step_id IN ({", ".join(["%s"] * len(protocol_steps))})', [step[0] for step in protocol_steps])
                            step_variations = django_cursor.fetchall()
                            step_variation_columns = [col[0] for col in django_cursor.description]
                            step_variation_placeholders = ', '.join(['?'] * len(step_variation_columns))
                            cursor.executemany(f'INSERT INTO {step_variation_table_name} ({", ".join(step_variation_columns)}) VALUES ({step_variation_placeholders})', step_variations)
                            conn.commit()
                            # Export Annotation associated to ProtocolStep
                            annotation_table_name = Annotation._meta.db_table
                            django_cursor.execute(f'SELECT * FROM {annotation_table_name} WHERE step_id IN ({", ".join(["%s"] * len(protocol_steps))})', [step[0] for step in protocol_steps])
                            step_annotations = django_cursor.fetchall()
                            annotation_columns = [col[0] for col in django_cursor.description]
                            annotation_placeholders = ', '.join(['?'] * len(annotation_columns))
                            cursor.executemany(f'INSERT INTO {annotation_table_name} ({", ".join(annotation_columns)}) VALUES ({annotation_placeholders})', step_annotations)
                            if step_annotations:
                                annotations.extend(step_annotations)
                                conn.commit()
                            # Export ProtocolReagent associated to ProtocolModel
                            protocol_reagent_table_name = ProtocolReagent._meta.db_table
                            django_cursor.execute(f'SELECT * FROM {protocol_reagent_table_name} WHERE protocol_id = %s', [related_row[position_of_protocol]])
                            protocol_reagents = django_cursor.fetchall()
                            protocol_reagent_columns = [col[0] for col in django_cursor.description]
                            protocol_reagent_placeholders = ', '.join(['?'] * len(protocol_reagent_columns))
                            if protocol_reagents:
                                cursor.executemany(f'INSERT INTO {protocol_reagent_table_name} ({", ".join(protocol_reagent_columns)}) VALUES ({protocol_reagent_placeholders})', protocol_reagents)
                                conn.commit()
                                # Export StepReagent associated to ProtocolReagent
                                step_reagent_table_name = StepReagent._meta.db_table
                                django_cursor.execute(f'SELECT * FROM {step_reagent_table_name} WHERE reagent_id IN ({", ".join(["%s"] * len(protocol_reagents))})', [reagent[0] for reagent in protocol_reagents])
                                step_reagents = django_cursor.fetchall()
                                step_reagent_columns = [col[0] for col in django_cursor.description]
                                step_reagent_placeholders = ', '.join(['?'] * len(step_reagent_columns))
                                if step_reagents:
                                    cursor.executemany(f'INSERT INTO {step_reagent_table_name} ({", ".join(step_reagent_columns)}) VALUES ({step_reagent_placeholders})', step_reagents)
                                    conn.commit()
                                    # Export Reagent associated to ProtocolReagent
                                    reagent_table_name = Reagent._meta.db_table
                                    django_cursor.execute(f'SELECT * FROM {reagent_table_name} WHERE id IN ({", ".join(["%s"] * len(step_reagents))})', [reagent[1] for reagent in step_reagents])
                                    reagents = django_cursor.fetchall()
                                    reagent_columns = [col[0] for col in django_cursor.description]
                                    reagent_placeholders = ', '.join(['?'] * len(reagent_columns))
                                    if reagents:
                                        cursor.executemany(f'INSERT INTO {reagent_table_name} ({", ".join(reagent_columns)}) VALUES ({reagent_placeholders})', reagents)
                                        conn.commit()
                                        # Export StoredReagent associated to Reagent
                                        stored_reagent_table_name = StoredReagent._meta.db_table
                                        django_cursor.execute(f'SELECT * FROM {stored_reagent_table_name} WHERE reagent_id IN ({", ".join(["%s"] * len(reagents))})', [reagent[0] for reagent in reagents])
                                        stored_reagents = django_cursor.fetchall()
                                        stored_reagent_columns = [col[0] for col in django_cursor.description]
                                        stored_reagent_placeholders = ', '.join(['?'] * len(stored_reagent_columns))
                                        if stored_reagents:
                                            cursor.executemany(f'INSERT INTO {stored_reagent_table_name} ({", ".join(stored_reagent_columns)}) VALUES ({stored_reagent_placeholders})', stored_reagents)
                                            conn.commit()

                                            stored_reagent_orm = StoredReagent.objects.filter(id__in=[st[0] for st in stored_reagents])
                                            # Export StorageObject associated to StoredReagent
                                            for st in stored_reagent_orm:
                                                storage_object = st.storage_object
                                                storage_object_list = [storage_object.id]
                                                while storage_object.stored_at:
                                                    storage_object = storage_object.stored_at
                                                    storage_object_list.append(storage_object.id)
                                                if storage_object_list:
                                                    storage_object_table_name = StorageObject._meta.db_table
                                                    django_cursor.execute(f'SELECT * FROM {storage_object_table_name} WHERE id IN ({", ".join(["%s"] * len(storage_object_list))})', storage_object_list)
                                                    storage_objects = django_cursor.fetchall()
                                                    storage_object_columns = [col[0] for col in django_cursor.description]
                                                    storage_object_placeholders = ', '.join(['?'] * len(storage_object_columns))
                                                    cursor.executemany(f'INSERT INTO {storage_object_table_name} ({", ".join(storage_object_columns)}) VALUES ({storage_object_placeholders})', storage_objects)
                                                    conn.commit()
                                                    # Export MetadataColumns associated to StoredReagent
                                                    metadata_column_table_name = MetadataColumn._meta.db_table
                                                    django_cursor.execute(f'SELECT * FROM {metadata_column_table_name} WHERE stored_reagent_id IN ({", ".join(["%s"] * len(stored_reagents))})', [st[0] for st in stored_reagents])
                                                    metadata_columns = django_cursor.fetchall()
                                                    metadata_column_columns = [col[0] for col in django_cursor.description]
                                                    metadata_columns_placeholders = ', '.join(['?'] * len(metadata_column_columns))
                                                    metadata_columns.extend(metadata_columns)
                                    # Export ReagentAction associated to StepReagent and Session

                                    reagent_action_table_name = ReagentAction._meta.db_table
                                    django_cursor.execute(f'SELECT * FROM {reagent_action_table_name} WHERE step_reagent_id IN ({", ".join(["%s"] * len(step_reagents))}) AND session_id = %s', [reagent[0] for reagent in step_reagents] + [session_id])
                                    reagent_actions = django_cursor.fetchall()
                                    reagent_action_columns = [col[0] for col in django_cursor.description]
                                    reagent_action_placeholders = ', '.join(['?'] * len(reagent_action_columns))
                                    cursor.executemany(f'INSERT INTO {reagent_action_table_name} ({", ".join(reagent_action_columns)}) VALUES ({reagent_action_placeholders})', reagent_actions)
                                    conn.commit()

                        # Export ProtocolModel
                        protocol_table_name = ProtocolModel._meta.db_table
                        django_cursor.execute(f'SELECT * FROM {protocol_table_name} WHERE id IN ({", ".join(["%s"] * len(protocol_ids))})', protocol_ids)
                        protocols = django_cursor.fetchall()
                        protocol_columns = [col[0] for col in django_cursor.description]
                        protocol_placeholders = ', '.join(['?'] * len(protocol_columns))
                        if protocols:
                            cursor.executemany(f'INSERT INTO {protocol_table_name} ({", ".join(protocol_columns)}) VALUES ({protocol_placeholders})', protocols)
                            conn.commit()
                            # Export ProtocolRating associated to Protocol
                            protocol_rating_table_name = ProtocolRating._meta.db_table
                            django_cursor.execute(f'SELECT * FROM {protocol_rating_table_name} WHERE protocol_id IN ({", ".join(["%s"] * len(protocol_ids))})', protocol_ids)
                            protocol_ratings = django_cursor.fetchall()
                            protocol_rating_columns = [col[0] for col in django_cursor.description]
                            protocol_rating_placeholders = ', '.join(['?'] * len(protocol_rating_columns))
                            if protocol_ratings:
                                cursor.executemany(f'INSERT INTO {protocol_rating_table_name} ({", ".join(protocol_rating_columns)}) VALUES ({protocol_rating_placeholders})', protocol_ratings)
                                conn.commit()
        if annotations:
            # Export InstrumentUsage associated to Annotations
            instrument_usage_table_name = InstrumentUsage._meta.db_table
            django_cursor.execute(f'SELECT * FROM {instrument_usage_table_name} WHERE annotation_id IN ({", ".join(["%s"] * len(annotations))})', [annotation[0] for annotation in annotations])
            instrument_usages = django_cursor.fetchall()
            instrument_usage_columns = [col[0] for col in django_cursor.description]
            instrument_usage_placeholders = ', '.join(['?'] * len(instrument_usage_columns))
            if instrument_usages:
                cursor.executemany(f'INSERT INTO {instrument_usage_table_name} ({", ".join(instrument_usage_columns)}) VALUES ({instrument_usage_placeholders})', instrument_usages)
                conn.commit()
                # Export Instrument associated to InstrumentUsage
                instrument_table_name = Instrument._meta.db_table
                print(instrument_usages)

                instrument_ids = list(set([instrument_usage[6] for instrument_usage in instrument_usages if instrument_usage[6]]))
                print(instrument_ids)
                if len(instrument_ids) > 1:
                    django_cursor.execute(f'SELECT * FROM {instrument_table_name} WHERE id IN ({", ".join(["%s"] * len(instrument_ids))})', instrument_ids)
                    instruments = django_cursor.fetchall()
                elif len(instrument_ids) == 1:
                    django_cursor.execute(f'SELECT * FROM {instrument_table_name} WHERE id = %s', instrument_ids)
                    instruments = [django_cursor.fetchone()]
                else:
                    instruments = []
                instrument_columns = [col[0] for col in django_cursor.description]
                print(instrument_columns)
                instrument_placeholders = ', '.join(['?'] * len(instrument_columns))
                if instruments:
                    cursor.executemany(f'INSERT INTO {instrument_table_name} ({", ".join(instrument_columns)}) VALUES ({instrument_placeholders})', instruments)
                    conn.commit()
                    # Export MetadataColumn associated to Instrument
                    metadata_column_table_name = MetadataColumn._meta.db_table
                    django_cursor.execute(f'SELECT * FROM {metadata_column_table_name} WHERE instrument_id IN ({", ".join(["%s"] * len(instruments))})', [instrument[0] for instrument in instruments])
                    metadata_columns = django_cursor.fetchall()
                    metadata_columns.extend(metadata_columns)
            # Export MetadataColumn associated to Annotations
            metadata_column_table_name = MetadataColumn._meta.db_table
            django_cursor.execute(f'SELECT * FROM {metadata_column_table_name} WHERE annotation_id IN ({", ".join(["%s"] * len(annotations))})', [annotation[0] for annotation in annotations])
            metadata_columns = django_cursor.fetchall()
            metadata_column_columns = [col[0] for col in django_cursor.description]
            metadata_columns_placeholders = ', '.join(['?'] * len(metadata_column_columns))
            metadata_columns.extend(metadata_columns)
        if metadata_columns:
            # Export MetadataColumns
            metadata_column_table_name = MetadataColumn._meta.db_table

            cursor.executemany(f'INSERT INTO {metadata_column_table_name} ({", ".join(metadata_column_columns)}) VALUES ({metadata_columns_placeholders})', set(metadata_columns))
            conn.commit()

    def export_media_files(self, unique_id, export_dir, conn):
        media_dir = os.path.join(export_dir, 'media')
        if not os.path.exists(media_dir):
            os.makedirs(media_dir)

        session = Session.objects.get(unique_id=unique_id)
        annotations = Annotation.objects.filter(session=session)
        cursor = conn.cursor()
        for annotation in annotations:
            if annotation.file:
                src_path = annotation.file.path
                dest_path = os.path.join(media_dir, os.path.basename(src_path))
                copyfile(src_path, dest_path)
                self.update_media_reference(annotation.id, dest_path, cursor)
        conn.commit()

    def update_media_reference(self, annotation_id, new_path, conn):

        conn.execute('UPDATE cc_annotation SET file = ? WHERE id = ?', (new_path, annotation_id))

    def create_and_sign_hash(self, export_dir, start_time):
        hash_value = self.generate_hash(export_dir, start_time)
        signed_hash = self.sign_hash(hash_value)
        self.store_hash_and_signature(export_dir, hash_value, signed_hash, start_time)

    def generate_hash(self, export_dir, start_time):
        hasher = hashlib.sha512()

        # Hash the SQLite database file
        sqlite_db_path = os.path.join(export_dir, 'exported_data.sqlite3')
        with open(sqlite_db_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)

        # Hash all media files
        media_dir = os.path.join(export_dir, 'media')
        for root, _, files in os.walk(media_dir):
            for file in files:
                file_path = os.path.join(root, file)
                with open(file_path, 'rb') as f:
                    while chunk := f.read(8192):
                        hasher.update(chunk)

        # Include the start time in the hash
        hasher.update(str(start_time).encode('utf-8'))

        return hasher.hexdigest()

    def sign_hash(self, hash_value):
        signer = Signer()
        return signer.sign(hash_value)

    def store_hash_and_signature(self, export_dir, hash_value, signed_hash, start_time):
        file_name = f'{start_time}_hash_signature.txt'
        with open(os.path.join(export_dir, file_name), 'w') as f:
            f.write(f'{hash_value}\n{signed_hash}\n')

    def verify_hash_and_signature(self, export_dir, start_time):
        sqlite_db_path = os.path.join(export_dir, 'exported_data.sqlite3')
        hash_value = self.generate_hash(sqlite_db_path, start_time)
        file_name = f'{start_time}_hash_signature.txt'
        with open(os.path.join(export_dir, file_name), 'r') as f:
            stored_hash, stored_signature = f.read().splitlines()
        signer = Signer()
        signed_hash = signer.sign(hash_value)
        return stored_hash == hash_value and stored_signature == signed_hash

    def compress_export_dir(self, export_dir):
        output_filename = f'{export_dir}.cupcake'
        with tarfile.open(output_filename, 'w:xz') as tar:
            tar.add(export_dir, arcname=os.path.basename(export_dir))
            # Remove the original export directory
            shutil.rmtree(export_dir)