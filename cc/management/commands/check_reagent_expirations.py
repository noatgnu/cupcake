from django.core.management.base import BaseCommand
from django.utils import timezone
from cc.models import StoredReagent
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check all stored reagents for upcoming expirations and send notifications'

    def handle(self, *args, **kwargs):
        self.stdout.write('Checking reagent expirations...')
        count = 0

        # Get all reagents where notification is enabled and expiration date exists
        reagents = StoredReagent.objects.filter(
            notify_on_expiry=True,
            expiration_date__isnull=False
        )

        for reagent in reagents:
            try:
                if reagent.check_expiration():
                    count += 1
                    logger.info(f"Sent expiration notification for reagent {reagent.id}: {reagent.reagent.name}")
            except Exception as e:
                logger.error(f"Error checking expiration for reagent {reagent.id}: {str(e)}")

        self.stdout.write(self.style.SUCCESS(f'Successfully sent {count} expiration notifications'))