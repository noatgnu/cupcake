"""
Django management command to wait for database to be available
Useful for Docker containers where the app starts before the database is ready
"""
import time
from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    """Django command to pause execution until database is available"""
    
    help = 'Wait for database to be available'

    def add_arguments(self, parser):
        parser.add_argument(
            '--timeout',
            type=int,
            default=60,
            help='Maximum time to wait in seconds (default: 60)'
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=1,
            help='Check interval in seconds (default: 1)'
        )

    def handle(self, *args, **options):
        timeout = options['timeout']
        interval = options['interval']
        
        self.stdout.write('Waiting for database...')
        
        start_time = time.time()
        db_conn = None
        
        while True:
            try:
                # Try to get database connection
                db_conn = connections['default']
                db_conn.cursor()
                break
            except OperationalError:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    self.stdout.write(
                        self.style.ERROR(f'Database unavailable after {timeout} seconds')
                    )
                    raise
                
                self.stdout.write(f'Database unavailable, waiting {interval} second(s)...')
                time.sleep(interval)
        
        elapsed = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(f'Database available after {elapsed:.1f} seconds!')
        )