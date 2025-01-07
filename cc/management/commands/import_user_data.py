from django.core.management.base import BaseCommand, CommandError
from cc.rq_tasks import import_user_data

class Command(BaseCommand):
    help = 'Import user data'

    def add_arguments(self, parser):
        parser.add_argument('user_id', type=int, help='User ID to import data')
        parser.add_argument('file_path', type=str, help='Path to the user data file')

    def handle(self, *args, **options):
        user_id = options['user_id']
        file_path = options['file_path']
        import_user_data(user_id, file_path)
        self.stdout.write(self.style.SUCCESS('Successfully imported user data'))
