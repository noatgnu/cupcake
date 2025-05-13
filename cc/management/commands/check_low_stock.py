from django.core.management.base import BaseCommand
from cc.models import StoredReagent


class Command(BaseCommand):
    help = 'Check all reagents for low stock and send notifications'

    def handle(self, *args, **options):
        reagents = StoredReagent.objects.filter(notify_on_low_stock=True).exclude(low_stock_threshold=None)
        notifications_sent = 0

        for reagent in reagents:
            if reagent.check_low_stock():
                notifications_sent += 1

        self.stdout.write(
            self.style.SUCCESS(f'Sent {notifications_sent} low stock notifications')
        )