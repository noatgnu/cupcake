"""
Management command to list imported objects and their sources
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from cc.models import Annotation, ProtocolModel, Session, ImportTracker, ImportedObject


class Command(BaseCommand):
    help = 'List imported objects and their sources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Username to filter imported objects'
        )
        parser.add_argument(
            '--model',
            type=str,
            choices=['annotation', 'protocol', 'session', 'all'],
            default='all',
            help='Model type to list'
        )
        parser.add_argument(
            '--converted-only',
            action='store_true',
            help='Show only converted instrument annotations'
        )

    def handle(self, *args, **options):
        user_filter = {}
        if options['user']:
            try:
                user = User.objects.get(username=options['user'])
                user_filter['user'] = user
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"User '{options['user']}' not found")
                )
                return

        self.stdout.write(self.style.SUCCESS("=== IMPORTED OBJECTS REPORT ===\n"))

        if options['model'] in ['annotation', 'all']:
            self.list_imported_annotations(user_filter, options.get('converted_only', False))

        if options['model'] in ['protocol', 'all'] and not options.get('converted_only', False):
            self.list_imported_protocols(user_filter)

        if options['model'] in ['session', 'all'] and not options.get('converted_only', False):
            self.list_imported_sessions(user_filter)

        # Summary of import trackers
        if not options.get('converted_only', False):
            self.list_import_trackers(user_filter)

    def list_imported_annotations(self, user_filter, converted_only=False):
        if converted_only:
            annotations = Annotation.objects.filter(
                annotation_type='text',
                annotation__icontains='[IMPORTED INSTRUMENT BOOKING',
                **user_filter
            )
            self.stdout.write(self.style.WARNING("=== CONVERTED INSTRUMENT ANNOTATIONS ==="))
        else:
            annotations = Annotation.objects.filter(
                annotation_name__icontains='[IMPORTED]',
                **user_filter
            )
            self.stdout.write(self.style.WARNING("=== IMPORTED ANNOTATIONS ==="))

        for annotation in annotations:
            import_info = annotation.import_source_info
            conversion_info = ""
            if annotation.was_converted_from_instrument:
                conversion_info = " [CONVERTED FROM INSTRUMENT]"
            
            self.stdout.write(f"• ID: {annotation.id}")
            self.stdout.write(f"  Name: {annotation.annotation_name}")
            self.stdout.write(f"  Type: {annotation.annotation_type}{conversion_info}")
            self.stdout.write(f"  User: {annotation.user.username if annotation.user else 'None'}")
            
            if import_info:
                self.stdout.write(f"  Import ID: {import_info['import_tracker'].import_id}")
                self.stdout.write(f"  Original ID: {import_info['original_id']}")
                self.stdout.write(f"  Imported At: {import_info['imported_at']}")
            
            self.stdout.write("")

    def list_imported_protocols(self, user_filter):
        protocols = ProtocolModel.objects.filter(
            protocol_title__icontains='[IMPORTED]',
            **user_filter
        )
        
        self.stdout.write(self.style.WARNING("=== IMPORTED PROTOCOLS ==="))
        for protocol in protocols:
            import_info = protocol.import_source_info
            
            self.stdout.write(f"• ID: {protocol.id}")
            self.stdout.write(f"  Title: {protocol.protocol_title}")
            self.stdout.write(f"  User: {protocol.user.username if protocol.user else 'None'}")
            
            if import_info:
                self.stdout.write(f"  Import ID: {import_info['import_tracker'].import_id}")
                self.stdout.write(f"  Original ID: {import_info['original_id']}")
                self.stdout.write(f"  Imported At: {import_info['imported_at']}")
            
            self.stdout.write("")

    def list_imported_sessions(self, user_filter):
        sessions = Session.objects.filter(
            name__icontains='[IMPORTED]',
            **user_filter
        )
        
        self.stdout.write(self.style.WARNING("=== IMPORTED SESSIONS ==="))
        for session in sessions:
            import_info = session.import_source_info
            
            self.stdout.write(f"• ID: {session.id}")
            self.stdout.write(f"  Name: {session.name}")
            self.stdout.write(f"  User: {session.user.username if session.user else 'None'}")
            self.stdout.write(f"  UUID: {session.unique_id}")
            
            if import_info:
                self.stdout.write(f"  Import ID: {import_info['import_tracker'].import_id}")
                self.stdout.write(f"  Original ID: {import_info['original_id']}")
                self.stdout.write(f"  Imported At: {import_info['imported_at']}")
            
            self.stdout.write("")

    def list_import_trackers(self, user_filter):
        trackers = ImportTracker.objects.filter(**user_filter).order_by('-import_started_at')
        
        self.stdout.write(self.style.SUCCESS("=== IMPORT TRACKERS ==="))
        for tracker in trackers:
            self.stdout.write(f"• Import ID: {tracker.import_id}")
            self.stdout.write(f"  User: {tracker.user.username}")
            self.stdout.write(f"  Status: {tracker.import_status}")
            self.stdout.write(f"  Started: {tracker.import_started_at}")
            if tracker.import_completed_at:
                self.stdout.write(f"  Completed: {tracker.import_completed_at}")
            self.stdout.write(f"  Objects Created: {tracker.total_objects_created}")
            self.stdout.write(f"  Files Imported: {tracker.total_files_imported}")
            self.stdout.write(f"  Can Revert: {'Yes' if tracker.can_revert else 'No'}")
            
            # Show conversion count if available
            conversions = ImportedObject.objects.filter(
                import_tracker=tracker,
                model_name='Annotation',
                object_data__annotation_type='text'
            ).filter(
                object_data__annotation__icontains='[IMPORTED INSTRUMENT BOOKING'
            ).count()
            
            if conversions > 0:
                self.stdout.write(f"  Instrument Conversions: {conversions}")
            
            self.stdout.write("")