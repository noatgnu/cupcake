import os
import sqlite3
import tarfile
import tempfile
from django.core.management.base import BaseCommand
from django.db import transaction, connection
from django.contrib.auth.models import User
from cc.models import Session, ProtocolModel, ProtocolStep, ProtocolSection, AnnotationFolder, Annotation, TimeKeeper, \
    StoredReagent, ReagentAction, StepVariation, ProtocolRating, ProtocolReagent, StepReagent, Reagent, StorageObject, \
    MetadataColumn, InstrumentUsage, Instrument, Project, Tag

class Command(BaseCommand):
    help = 'Import exported data from a .cupcake archive. Data is vaulted by default for user isolation.'

    def add_arguments(self, parser):
        parser.add_argument('archive_path', type=str, help='Path to the .cupcake archive file')
        parser.add_argument('owner_id', type=int, help='ID of the user who owns the imported data')
        parser.add_argument('--no-vault', action='store_true', help='Import data without vaulting (default: vault items)', default=False)

    def handle(self, *args, **kwargs):
        archive_path = kwargs['archive_path']
        self.owner_id = kwargs['owner_id']
        self.vault_items = not kwargs['no_vault']  # Default to True unless --no-vault is specified
        
        # Get the importing user
        try:
            self.importing_user = User.objects.get(id=self.owner_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User with ID {self.owner_id} does not exist.'))
            return
            
        with tempfile.TemporaryDirectory() as temp_dir:
            self.extract_archive(archive_path, temp_dir)
            self.import_data(temp_dir)
            vault_msg = " into user vault" if self.vault_items else " (no vaulting)"
            self.stdout.write(self.style.SUCCESS(f'Data imported successfully{vault_msg}.'))

    def extract_archive(self, archive_path, extract_to):
        with tarfile.open(archive_path, 'r:xz') as tar:
            tar.extractall(path=extract_to)

    def import_data(self, extract_dir):
        sqlite_db_path = os.path.join(extract_dir, 'exported_data.sqlite3')
        media_dir = os.path.join(extract_dir, 'media')

        with transaction.atomic():
            self.import_sqlite_data(sqlite_db_path)
            self.import_media_files(media_dir)

    def import_sqlite_data(self, sqlite_db_path):
        sqlite_conn = sqlite3.connect(sqlite_db_path)
        sqlite_cursor = sqlite_conn.cursor()

        # Fetch all tables from the SQLite database
        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = sqlite_cursor.fetchall()

        self.id_map = {
            'annotation': {},
            'session': {},
            'protocol': {},
            'protocol_rating': {},
            'instrument_usage': {},
            'instrument': {},
            'metadata_column': {},
            'protocol_step': {},
            'protocol_section': {},
            'annotation_folder': {},
            'time_keeper': {},
            'stored_reagent': {},
            'reagent_action': {},
            'step_variation': {},
            'protocol_reagent': {},
            'step_reagent': {},
            'reagent': {},
            'storage_object': {},
            'project': {},
            'tag': {}
        }
        many_to_many_session_protocols = []
        for table_name in tables:
            table_name = table_name[0]
            sqlite_cursor.execute(f"SELECT * FROM {table_name}")
            rows = sqlite_cursor.fetchall()

            # Get column names
            column_names = [description[0] for description in sqlite_cursor.description]
            if table_name == "cc_session_protocols":
                many_to_many_session_protocols = rows

            else:
                # Insert data into the Django database
                for row in rows:
                    data = dict(zip(column_names, row))
                    self.insert_data(table_name, data)
        for session_protocol in many_to_many_session_protocols:
            session_id = self.id_map['session'].get(session_protocol[1], None)
            protocol_id = self.id_map['protocol'].get(session_protocol[2], None)
            if session_id and protocol_id:
                session = Session.objects.get(id=session_id)
                session.protocols.add(protocol_id)
        sqlite_conn.close()

    def insert_data(self, table_name, data):
        if "remote_id" in data:
            if "id" in data:
                data["remote_id"] = data["id"]
            else:
                del data["remote_id"]
        if "remote_host_id" in data:
            del data["remote_host_id"]
        if "user_id" in data:
            del data["user_id"]
        if "owner_id" in data:
            del data["owner_id"]
        if table_name == Annotation._meta.db_table:
            self.insert_annotation(data)
        elif table_name == Session._meta.db_table:
            del data["unique_id"]
            self.insert_session(data)
        elif table_name == ProtocolModel._meta.db_table:
            self.insert_protocol(data)
        elif table_name == ProtocolRating._meta.db_table:
            self.insert_protocol_rating(data)
        elif table_name == InstrumentUsage._meta.db_table:
            self.insert_instrument_usage(data)
        elif table_name == Instrument._meta.db_table:
            self.insert_instrument(data)
        elif table_name == MetadataColumn._meta.db_table:
            self.insert_metadata_column(data)
        elif table_name == ProtocolStep._meta.db_table:
            self.insert_protocol_step(data)
        elif table_name == ProtocolSection._meta.db_table:
            self.insert_protocol_section(data)
        elif table_name == AnnotationFolder._meta.db_table:
            self.insert_annotation_folder(data)
        elif table_name == TimeKeeper._meta.db_table:
            self.insert_time_keeper(data)
        elif table_name == StoredReagent._meta.db_table:
            self.insert_stored_reagent(data)
        elif table_name == ReagentAction._meta.db_table:
            self.insert_reagent_action(data)
        elif table_name == StepVariation._meta.db_table:
            self.insert_step_variation(data)
        elif table_name == ProtocolReagent._meta.db_table:
            self.insert_protocol_reagent(data)
        elif table_name == StepReagent._meta.db_table:
            self.insert_step_reagent(data)
        elif table_name == Reagent._meta.db_table:
            self.insert_reagent(data)
        elif table_name == StorageObject._meta.db_table:
            self.insert_storage_object(data)
        elif table_name == Project._meta.db_table:
            self.insert_project(data)
        elif table_name == Tag._meta.db_table:
            self.insert_tag(data)

    def insert_annotation(self, data):
        old_id = data.pop('id')
        data['session_id'] = None
        annotation = Annotation.objects.create(**data)
        self.id_map['annotation'][old_id] = annotation.id

    def insert_session(self, data):
        old_id = data.pop('id')
        session = Session.objects.create(**data)
        self.id_map['session'][old_id] = session.id

    def insert_protocol(self, data):
        old_id = data.pop('id')
        
        # Apply vaulting if enabled
        if self.vault_items:
            data['is_vaulted'] = True
            data['user'] = self.importing_user
        
        protocol = ProtocolModel.objects.create(**data)
        self.id_map['protocol'][old_id] = protocol.id

    def insert_protocol_rating(self, data):
        old_id = data.pop('id')
        data['protocol_id'] = self.id_map['protocol'].get(data['protocol_id'], None)
        protocol_rating = ProtocolRating.objects.create(**data)
        self.id_map['protocol_rating'][old_id] = protocol_rating.id

    def insert_instrument_usage(self, data):
        old_id = data.pop('id')
        data['annotation_id'] = self.id_map['annotation'].get(data['annotation_id'], None)
        instrument_usage = InstrumentUsage.objects.create(**data)
        self.id_map['instrument_usage'][old_id] = instrument_usage.id

    def insert_instrument(self, data):
        old_id = data.pop('id')
        
        # Apply vaulting if enabled
        if self.vault_items:
            data['is_vaulted'] = True
            data['user'] = self.importing_user
        
        instrument = Instrument.objects.create(**data)
        self.id_map['instrument'][old_id] = instrument.id

    def insert_metadata_column(self, data):
        old_id = data.pop('id')
        data['annotation_id'] = self.id_map['annotation'].get(data['annotation_id'], None)
        data['instrument_id'] = self.id_map['instrument'].get(data['instrument_id'], None)
        metadata_column = MetadataColumn.objects.create(**data)
        self.id_map['metadata_column'][old_id] = metadata_column.id

    def insert_protocol_step(self, data):
        old_id = data.pop('id')
        data['protocol_id'] = self.id_map['protocol'].get(data['protocol_id'], None)
        protocol_step = ProtocolStep.objects.create(**data)
        self.id_map['protocol_step'][old_id] = protocol_step.id

    def insert_protocol_section(self, data):
        old_id = data.pop('id')
        data['protocol_id'] = self.id_map['protocol'].get(data['protocol_id'], None)
        protocol_section = ProtocolSection.objects.create(**data)
        self.id_map['protocol_section'][old_id] = protocol_section.id

    def insert_annotation_folder(self, data):
        old_id = data.pop('id')
        data['session_id'] = self.id_map['session'].get(data['session_id'], None)
        annotation_folder = AnnotationFolder.objects.create(**data)
        self.id_map['annotation_folder'][old_id] = annotation_folder.id

    def insert_time_keeper(self, data):
        old_id = data.pop('id')
        data['session_id'] = self.id_map['session'].get(data['session_id'], None)
        time_keeper = TimeKeeper.objects.create(**data)
        self.id_map['time_keeper'][old_id] = time_keeper.id

    def insert_stored_reagent(self, data):
        old_id = data.pop('id')
        data['reagent_id'] = self.id_map['reagent'].get(data['reagent_id'], None)
        
        # Apply vaulting if enabled
        if self.vault_items:
            data['is_vaulted'] = True
            data['user'] = self.importing_user
            # Vault items are not shareable by default
            data['shareable'] = False
            data['access_all'] = False
        
        stored_reagent = StoredReagent.objects.create(**data)
        self.id_map['stored_reagent'][old_id] = stored_reagent.id

    def insert_reagent_action(self, data):
        old_id = data.pop('id')
        data['step_reagent_id'] = self.id_map['step_reagent'].get(data['step_reagent_id'], None)
        reagent_action = ReagentAction.objects.create(**data)
        self.id_map['reagent_action'][old_id] = reagent_action.id

    def insert_step_variation(self, data):
        old_id = data.pop('id')
        data['step_id'] = self.id_map['protocol_step'].get(data['step_id'], None)
        step_variation = StepVariation.objects.create(**data)
        self.id_map['step_variation'][old_id] = step_variation.id

    def insert_protocol_reagent(self, data):
        old_id = data.pop('id')
        data['protocol_id'] = self.id_map['protocol'].get(data['protocol_id'], None)
        protocol_reagent = ProtocolReagent.objects.create(**data)
        self.id_map['protocol_reagent'][old_id] = protocol_reagent.id

    def insert_step_reagent(self, data):
        old_id = data.pop('id')
        data['reagent_id'] = self.id_map['reagent'].get(data['reagent_id'], None)
        step_reagent = StepReagent.objects.create(**data)
        self.id_map['step_reagent'][old_id] = step_reagent.id

    def insert_reagent(self, data):
        old_id = data.pop('id')
        reagent = Reagent.objects.create(**data)
        self.id_map['reagent'][old_id] = reagent.id

    def insert_storage_object(self, data):
        old_id = data.pop('id')
        
        # Apply vaulting if enabled
        if self.vault_items:
            data['is_vaulted'] = True
            data['user'] = self.importing_user
        
        storage_object = StorageObject.objects.create(**data)
        self.id_map['storage_object'][old_id] = storage_object.id

    def insert_project(self, data):
        old_id = data.pop('id')
        
        # Apply vaulting if enabled
        if self.vault_items:
            data['is_vaulted'] = True
            data['owner'] = self.importing_user
        
        project = Project.objects.create(**data)
        self.id_map['project'][old_id] = project.id

    def insert_tag(self, data):
        old_id = data.pop('id')
        
        # Apply vaulting if enabled
        if self.vault_items:
            data['is_vaulted'] = True
            data['user'] = self.importing_user
        
        tag = Tag.objects.create(**data)
        self.id_map['tag'][old_id] = tag.id

    def import_media_files(self, media_dir):
        for root, _, files in os.walk(media_dir):
            for file in files:
                file_path = os.path.join(root, file)
                annotation_id = self.get_annotation_id_from_filename(file)
                self.update_media_reference(annotation_id, file_path)

    def get_annotation_id_from_filename(self, filename):
        return int(filename.split('_')[1].split('.')[0])

    def update_media_reference(self, annotation_id, new_path):
        annotation = Annotation.objects.get(id=self.id_map['annotation'][annotation_id])
        annotation.file = new_path
        annotation.save()