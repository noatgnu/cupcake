from django.core.management.base import BaseCommand
from cc.models import Instrument


class Command(BaseCommand):
    help = 'Check all instruments for warranty expiration and maintenance needs and send notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Days threshold for warranty notifications (default: 30)'
        )
        parser.add_argument(
            '--maintenance-days',
            type=int,
            default=14,
            help='Days threshold for maintenance notifications (default: 14)'
        )
        parser.add_argument(
            '--warranty-only',
            action='store_true',
            help='Check only warranty expiration notifications'
        )
        parser.add_argument(
            '--maintenance-only',
            action='store_true',
            help='Check only maintenance notifications'
        )

    def handle(self, *args, **options):
        days_threshold = options['days']
        maintenance_days = options['maintenance_days']

        if options['warranty_only']:
            warranty_count = 0
            maintenance_count = 0
            instruments = Instrument.objects.filter(enabled=True)
            for instrument in instruments:
                if instrument.check_warranty_expiration(days_threshold):
                    warranty_count += 1

            self.stdout.write(
                self.style.SUCCESS(f'Sent {warranty_count} warranty expiration notifications')
            )
        elif options['maintenance_only']:
            maintenance_count = 0
            instruments = Instrument.objects.filter(enabled=True)
            for instrument in instruments:
                if instrument.check_upcoming_maintenance(maintenance_days):
                    maintenance_count += 1

            self.stdout.write(
                self.style.SUCCESS(f'Sent {maintenance_count} maintenance notifications')
            )
        else:
            warranty_count, maintenance_count = Instrument.check_all_instruments(days_threshold)

            self.stdout.write(
                self.style.SUCCESS(
                    f'Sent {warranty_count} warranty expiration notifications and '
                    f'{maintenance_count} maintenance notifications'
                )
            )