import os
import tarfile
import hashlib
import tempfile
from django.core.management.base import BaseCommand
from django.core.signing import Signer

class Command(BaseCommand):
    help = 'Verify the integrity of the testexport archive.'

    def add_arguments(self, parser):
        parser.add_argument('archive_path', type=str, help='The path to the .cupcake archive')

    def handle(self, *args, **kwargs):
        archive_path = kwargs['archive_path']
        with tempfile.TemporaryDirectory() as export_dir:
            self.extract_archive(archive_path, export_dir)
            folder = os.path.join(export_dir, os.listdir(export_dir)[0])
            signature_file = ""
            for r, d, f in os.walk(folder):
                for i in f:
                    if i.endswith('hash_signature.txt'):
                        signature_file = i
                        break
            start_time = self.get_start_time_from_filename(signature_file)
            if self.verify_hash_and_signature(folder, start_time):
                self.stdout.write(self.style.SUCCESS('The integrity of the archive is verified.'))
            else:
                self.stdout.write(self.style.ERROR('The integrity of the archive could not be verified.'))

    def extract_archive(self, archive_path, export_dir):
        with tarfile.open(archive_path, 'r:xz') as tar:
            tar.extractall(path=export_dir)


    def get_start_time_from_filename(self, hash_signature_file):
        start_time_str = hash_signature_file.split('_')[0]
        return int(start_time_str)

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

    def verify_hash_and_signature(self, export_dir, start_time):
        hash_value = self.generate_hash(export_dir, start_time)
        file_name = f'{start_time}_hash_signature.txt'
        with open(os.path.join(export_dir, file_name), 'r') as f:
            stored_hash, stored_signature = f.read().splitlines()
        signer = Signer()
        signed_hash = signer.sign(hash_value)
        return stored_hash == hash_value and stored_signature == signed_hash