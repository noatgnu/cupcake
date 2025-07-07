from django.contrib.auth.models import User
from rest_framework.exceptions import ValidationError
from rest_framework.fields import ReadOnlyField, CharField, IntegerField
from rest_framework.relations import StringRelatedField
from rest_framework.serializers import ModelSerializer, SerializerMethodField, PrimaryKeyRelatedField
import json
from cc.models import ProtocolModel, ProtocolStep, Annotation, StepVariation, Session, TimeKeeper, ProtocolSection, \
    ProtocolRating, Reagent, ProtocolReagent, StepReagent, StepTag, ProtocolTag, Tag, AnnotationFolder, Project, \
    Instrument, InstrumentUsage, StorageObject, StoredReagent, ReagentAction, LabGroup, MSUniqueVocabularies, \
    HumanDisease, Tissue, SubcellularLocation, MetadataColumn, Species, Unimod, InstrumentJob, FavouriteMetadataOption, \
    Preset, MetadataTableTemplate, ExternalContactDetails, SupportInformation, ExternalContact, MaintenanceLog, \
    MessageRecipient, MessageThread, Message, MessageAttachment, ReagentSubscription, SiteSettings, BackupLog, DocumentPermission, \
    ImportTracker, ImportedObject, ImportedFile, ImportedRelationship


class UserBasicSerializer(ModelSerializer):

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']
        read_only_fields = fields


class ExternalContactDetailsSerializer(ModelSerializer):
    class Meta:
        model = ExternalContactDetails
        fields = ['id', 'contact_method_alt_name', 'contact_type', 'contact_value']


class ExternalContactSerializer(ModelSerializer):
    contact_details = ExternalContactDetailsSerializer(many=True, required=False)

    class Meta:
        model = ExternalContact
        fields = ['id', 'user', 'contact_name', 'contact_details']

    def create(self, validated_data):
        contact_details_data = validated_data.pop('contact_details', [])
        contact = ExternalContact.objects.create(**validated_data)

        for detail_data in contact_details_data:
            ex_detail = ExternalContactDetails.objects.create(
                **detail_data
            )
            contact.contact_details.add(ex_detail)

        return contact

    def update(self, instance, validated_data):
        # Update the main contact fields
        instance.contact_name = validated_data.get('contact_name', instance.contact_name)
        instance.user = validated_data.get('user', instance.user)

        if 'contact_details' in validated_data:
            contact_details_data = validated_data.pop('contact_details')

            detail_ids = [item.get('id') for item in contact_details_data if item.get('id')]

            instance.contact_details.exclude(id__in=detail_ids).delete()

            for detail_data in contact_details_data:
                detail_id = detail_data.get('id')
                if detail_id:
                    contact_detail = ExternalContactDetails.objects.get(id=detail_id)
                    contact_detail.contact_type = detail_data.get('contact_type', contact_detail.contact_type)
                    contact_detail.contact_value = detail_data.get('contact_value', contact_detail.contact_value)
                    contact_detail.contact_method_alt_name = detail_data.get('contact_method_alt_name', contact_detail.contact_method_alt_name)
                    contact_detail.save()
                else:
                    ex = ExternalContactDetails.objects.create(
                        contact_type=detail_data.get('contact_type'),
                        contact_value=detail_data.get('contact_value'),
                        contact_method_alt_name=detail_data.get('contact_method_alt_name'),
                    )
                    instance.contact_details.add(ex)

        instance.save()
        return instance


class SupportInformationSerializer(ModelSerializer):
    vendor_contacts = ExternalContactSerializer(many=True, required=False)
    manufacturer_contacts = ExternalContactSerializer(many=True, required=False)
    location = SerializerMethodField()
    location_id = PrimaryKeyRelatedField(
        source='location',
        queryset=StorageObject.objects.all(),
        required=False,
        allow_null=True,
        write_only=True
    )

    def get_location(self, obj):
        if obj.location:
            location: StorageObject = obj.location

            return {
                "id": location.id,
                "object_name": location.object_name,
                "object_type": location.object_type,
                "object_description": location.object_description,
            }
        return None

    class Meta:
        model = SupportInformation
        fields = [
            'id',
            'vendor_name',
            'vendor_contacts',
            'manufacturer_name',
            'manufacturer_contacts',
            'serial_number',
            'maintenance_frequency_days',
            'location',
            'location_id',
            'warranty_start_date',
            'warranty_end_date',
            'created_at',
            'updated_at'
        ]

    def create(self, validated_data):
        vendor_contacts_data = validated_data.pop('vendor_contacts', [])
        manufacturer_contacts_data = validated_data.pop('manufacturer_contacts', [])

        support_info = SupportInformation.objects.create(**validated_data)

        for vendor_contact in vendor_contacts_data:
            contact_details_data = vendor_contact.pop('contact_details', [])
            contact = ExternalContact.objects.create(**vendor_contact)

            for detail in contact_details_data:
                contact_detail = ExternalContactDetails.objects.create(**detail)
                contact.contact_details.add(contact_detail)

            support_info.vendor_contacts.add(contact)

        for manufacturer_contact in manufacturer_contacts_data:
            contact_details_data = manufacturer_contact.pop('contact_details', [])
            contact = ExternalContact.objects.create(**manufacturer_contact)

            for detail in contact_details_data:
                contact_detail = ExternalContactDetails.objects.create(**detail)
                contact.contact_details.add(contact_detail)

            support_info.manufacturer_contacts.add(contact)

        return support_info

    def update(self, instance, validated_data):
        instance.vendor_name = validated_data.get('vendor_name', instance.vendor_name)
        instance.manufacturer_name = validated_data.get('manufacturer_name', instance.manufacturer_name)
        instance.serial_number = validated_data.get('serial_number', instance.serial_number)
        instance.maintenance_frequency_days = validated_data.get('maintenance_frequency_days',
                                                              instance.maintenance_frequency_days)
        instance.warranty_start_date = validated_data.get('warranty_start_date', instance.warranty_start_date)
        instance.warranty_end_date = validated_data.get('warranty_end_date', instance.warranty_end_date)

        location = validated_data.get('location', instance.location)
        if location:
            instance.location = location

        instance.save()
        if 'vendor_contacts' in validated_data:
            vendor_contacts_data = validated_data.pop('vendor_contacts')
            for vendor_contact_data in vendor_contacts_data:
                contact_id = vendor_contact_data.get('id')
                if contact_id:
                    try:
                        contact = ExternalContact.objects.get(id=contact_id)
                        contact_serializer = ExternalContactSerializer(contact, data=vendor_contact_data)
                        if contact_serializer.is_valid():
                            contact_serializer.save()
                    except ExternalContact.DoesNotExist:
                        pass
                else:
                    contact_serializer = ExternalContactSerializer(data=vendor_contact_data)
                    if contact_serializer.is_valid():
                        contact = contact_serializer.save()
                        instance.vendor_contacts.add(contact)

        if 'manufacturer_contacts' in validated_data:
            manufacturer_contacts_data = validated_data.pop('manufacturer_contacts')
            for manufacturer_contact_data in manufacturer_contacts_data:
                contact_id = manufacturer_contact_data.get('id')
                if contact_id:
                    try:
                        contact = ExternalContact.objects.get(id=contact_id)
                        contact_serializer = ExternalContactSerializer(contact, data=manufacturer_contact_data)
                        if contact_serializer.is_valid():
                            contact_serializer.save()
                    except ExternalContact.DoesNotExist:
                        pass
                else:
                    contact_serializer = ExternalContactSerializer(data=manufacturer_contact_data)
                    if contact_serializer.is_valid():
                        contact = contact_serializer.save()
                        instance.manufacturer_contacts.add(contact)
        return instance


class ProtocolModelSerializer(ModelSerializer):
    steps = SerializerMethodField()
    sections = SerializerMethodField()
    complexity_rating = SerializerMethodField()
    duration_rating = SerializerMethodField()
    reagents = SerializerMethodField()
    tags = SerializerMethodField()
    metadata_columns = SerializerMethodField()

    def get_steps(self, obj):
        return ProtocolStepSerializer(obj.get_step_in_order(), many=True).data

    def get_sections(self, obj):
        return ProtocolSectionSerializer(obj.get_section_in_order(), many=True).data

    def get_complexity_rating(self, obj):
        r = obj.ratings.all()
        if r:
            data = [x.complexity_rating for x in r]
            return sum(data) / len(data)
        return 0

    def get_duration_rating(self, obj):
        r = obj.ratings.all()
        if r:
            data = [x.duration_rating for x in r]
            return sum(data) / len(data)
        return 0

    def get_reagents(self, obj):
        return ProtocolReagentSerializer(obj.reagents.all(), many=True).data

    def get_tags(self, obj):
        return ProtocolTagSerializer(obj.tags.all(), many=True).data

    def get_metadata_columns(self, obj):
        metadata_columns = obj.metadata_columns.all()
        if metadata_columns.exists():
            return MetadataColumnSerializer(metadata_columns, many=True).data
        return []

    class Meta:
        model = ProtocolModel
        fields = [
            'id',
            'protocol_id',
            'protocol_created_on',
            'protocol_doi',
            'protocol_title',
            'protocol_description',
            'protocol_url',
            'protocol_version_uri',
            'steps',
            'sections',
            'enabled',
            'complexity_rating',
            'duration_rating',
            'reagents',
            'tags',
            'metadata_columns'
        ]

class ProtocolStepSerializer(ModelSerializer):
    annotations = SerializerMethodField()
    variations = SerializerMethodField()
    reagents = SerializerMethodField()
    tags = SerializerMethodField()

    def get_annotations(self, obj):
        return AnnotationSerializer(obj.annotations.all(), many=True).data

    def get_variations(self, obj):
        return StepVariationSerializer(obj.variations.all(), many=True).data

    def get_reagents(self, obj):
        return StepReagentSerializer(obj.reagents.all(), many=True).data

    def get_tags(self, obj):
        return StepTagSerializer(obj.tags.all(), many=True).data

    class Meta:
        model = ProtocolStep
        fields = [
            'id',
            'protocol',
            'step_id',
            'step_description',
            'step_section',
            'step_duration',
            'next_step',
            'annotations',
            'variations',
            'previous_step',
            'reagents',
            'tags',
            'created_at',
            'updated_at'
        ]


class AnnotationSerializer(ModelSerializer):
    folder = SerializerMethodField()
    instrument_usage = SerializerMethodField()
    metadata_columns = SerializerMethodField()
    user = SerializerMethodField()

    def get_instrument_usage(self, obj):
        return InstrumentUsageSerializer(obj.instrument_usage.all(), many=True).data

    def get_folder(self, obj):
        # get folder path to root
        path = []
        folder = obj.folder
        while folder:
            path.append({'id': folder.id, 'folder_name': folder.folder_name})
            folder = folder.parent_folder
        return path

    def get_metadata_columns(self, obj):
        if obj.metadata_columns:
            return MetadataColumnSerializer(obj.metadata_columns.all(), many=True).data
        return []

    def get_user(self, obj):
        if obj.user:
            return {"id": obj.user.id, "username": obj.user.username}
        return None

    class Meta:
        model = Annotation
        fields = [
            'id',
            'step',
            'session',
            'annotation',
            'file',
            'created_at',
            'updated_at',
            'annotation_type',
            'transcribed',
            'transcription',
            'language',
            'translation',
            'scratched',
            'annotation_name',
            'folder',
            'summary',
            'instrument_usage',
            'metadata_columns',
            'fixed',
            'user',
            'stored_reagent']


class StepVariationSerializer(ModelSerializer):
    class Meta:
        model = StepVariation
        fields = [
            'id',
            'step',
            'variation_description',
            'variation_duration']


class SessionSerializer(ModelSerializer):
    time_keeper = SerializerMethodField()
    projects = SerializerMethodField()
    def get_time_keeper(self, obj):
        return TimeKeeperSerializer(obj.time_keeper.all(), many=True).data
    def get_projects(self, obj):
        return [x.id for x in obj.projects.all()]

    class Meta:
        model = Session
        fields = [
            'id',
                  'user',
            'unique_id',
            'enabled',
            'created_at',
            'updated_at',
            'protocols',
            'name',
            'time_keeper',
            'enabled',
            'started_at',
            'ended_at',
            'projects'
        ]
        lookup_field = 'unique_id'


class TimeKeeperSerializer(ModelSerializer):
    class Meta:
        model = TimeKeeper
        fields = [
            'id',
            'start_time',
            'session',
            'step',
            'started',
            'current_duration'
        ]


class ProtocolSectionSerializer(ModelSerializer):
    class Meta:
        model = ProtocolSection
        fields = ['id', 'protocol', 'section_description', 'section_duration', 'created_at', 'updated_at']

class UserSerializer(ModelSerializer):
    lab_groups = SerializerMethodField()
    managed_lab_groups = SerializerMethodField()

    def get_lab_groups(self, obj):
        return [LabGroupSerializer(x, many=False).data for x in obj.lab_groups.all()]

    def get_managed_lab_groups(self, obj):
        return [LabGroupSerializer(x, many=False).data for x in obj.managed_lab_groups.all()]

    class Meta:
        model = User
        fields = ['id', 'username', 'lab_groups', 'managed_lab_groups', 'email', 'first_name', 'last_name', 'is_staff']

class ProtocolRatingSerializer(ModelSerializer):
    class Meta:
        model = ProtocolRating
        fields = ['id', 'protocol', 'user', 'complexity_rating', 'duration_rating', 'created_at', 'updated_at']

class ReagentSerializer(ModelSerializer):
    class Meta:
        model = Reagent
        fields = ['id', 'name', 'unit', 'created_at', 'updated_at']

class ProtocolReagentSerializer(ModelSerializer):
    reagent = SerializerMethodField()
    def get_reagent(self, obj):
        return ReagentSerializer(obj.reagent, many=False).data
    class Meta:
        model = ProtocolReagent
        fields = ['id', 'protocol', 'reagent', 'quantity', 'created_at', 'updated_at']

class StepReagentSerializer(ModelSerializer):
    reagent = SerializerMethodField()

    def get_reagent(self, obj):
        return ReagentSerializer(obj.reagent, many=False).data

    class Meta:
        model = StepReagent
        fields = ['id', 'step', 'reagent', 'quantity', 'created_at', 'updated_at', 'scalable', 'scalable_factor']

class StepTagSerializer(ModelSerializer):
    tag = SerializerMethodField()
    def get_tag(self, obj):
        return TagSerializer(obj.tag, many=False).data

    class Meta:
        model = StepTag
        fields = ['id', 'step', 'tag', 'created_at', 'updated_at']

class ProtocolTagSerializer(ModelSerializer):
    tag = SerializerMethodField()

    def get_tag(self, obj):
        return TagSerializer(obj.tag, many=False).data

    class Meta:
        model = ProtocolTag
        fields = ['id', 'protocol', 'tag', 'created_at', 'updated_at']

class TagSerializer(ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'tag', 'created_at', 'updated_at']

class AnnotationFolderSerializer(ModelSerializer):
    owner = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = AnnotationFolder
        fields = ['id', 'folder_name', 'created_at', 'updated_at', 'parent_folder', 'session', 'instrument', 'stored_reagent', 'is_shared_document_folder', 'owner']

class ProjectSerializer(ModelSerializer):
    sessions = SerializerMethodField()
    owner = SerializerMethodField()

    def get_sessions(self, obj):
        return [{"unique_id": x.unique_id, "name": x.name, "protocol": [i.id for i in x.protocols.all()]} for x in obj.sessions.all()]

    def get_owner(self, obj):
        return obj.owner.username

    class Meta:
        model = Project
        fields = ['id', 'project_name', 'created_at', 'updated_at', 'project_description', 'owner', 'sessions']

class MaintenanceLogSerializer(ModelSerializer):
    annotations = SerializerMethodField()
    created_by_user = SerializerMethodField()
    annotation_folder_details = SerializerMethodField()

    def get_annotations(self, obj):
        if obj.annotation_folder:
            annotations = obj.annotation_folder.annotations.all()
            return AnnotationSerializer(annotations, many=True).data
        return []

    def get_created_by_user(self, obj):
        if obj.created_by:
            return {"id": obj.created_by.id, "username": obj.created_by.username}
        return None

    def get_annotation_folder_details(self, obj):
        if obj.annotation_folder:
            return {
                "id": obj.annotation_folder.id,
                "folder_name": obj.annotation_folder.folder_name
            }
        return None

    class Meta:
        model = MaintenanceLog
        fields = [
            'id',
            'maintenance_date',
            'maintenance_notes',
            'maintenance_type',
            'maintenance_description',
            'instrument',
            'created_at',
            'updated_at',
            'created_by',
            'created_by_user',
            'status',
            'is_template',
            'annotation_folder',
            'annotation_folder_details',
            'annotations'
        ]


class InstrumentSerializer(ModelSerializer):
    metadata_columns = SerializerMethodField()
    annotation_folders = SerializerMethodField()
    support_information = SerializerMethodField()

    def get_metadata_columns(self, obj):
        if obj.metadata_columns:
            return MetadataColumnSerializer(obj.metadata_columns.all(), many=True).data
        return []

    def get_annotation_folders(self, obj):
        folders = obj.annotation_folders.filter(folder_name__in=["Manuals", "Certificates", "Maintenance"])
        if folders.exists():
            return AnnotationFolderSerializer(folders, many=True).data
        return []

    def get_support_information(self, obj):
        support_info = obj.support_information.all()
        if support_info.exists():
            return SupportInformationSerializer(support_info, many=True).data
        return []

    class Meta:
        model = Instrument
        fields = [
            'id',
            'max_days_ahead_pre_approval',
            'max_days_within_usage_pre_approval',
            'instrument_name',
            'instrument_description',
            'created_at',
            'updated_at',
            'enabled',
            'metadata_columns',
            'annotation_folders',
            'image',
            'support_information',
            'days_before_maintenance_notification',
            'days_before_warranty_notification',
            'last_maintenance_notification_sent',
            'last_warranty_notification_sent',
            'accepts_bookings'
        ]


class InstrumentUsageSerializer(ModelSerializer):
    user = SerializerMethodField()

    def get_user(self, obj):
        if obj.user:
            return obj.user.username
        return None

    class Meta:
        model = InstrumentUsage
        fields = [
            'id',
            'instrument',
            'annotation',
            'created_at',
            'updated_at',
            'time_started',
            'time_ended',
            'user',
            'description',
            'approved',
            'maintenance',
            'approved_by'
        ]

class StorageObjectSerializer(ModelSerializer):
    stored_reagents = SerializerMethodField(read_only=True)
    user = SerializerMethodField(read_only=True)
    path_to_root = SerializerMethodField(read_only=True)
    child_count = SerializerMethodField(read_only=True)

    def get_user(self, obj):
        if obj.user:
            return obj.user.username
        return None

    def get_stored_reagents(self, obj):
        return StoredReagentSerializer(obj.stored_reagents.all(), many=True).data

    def get_path_to_root(self, obj):
        return obj.get_path_to_root()

    def create(self, validated_data):
        return StorageObject.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    def get_child_count(self, obj):
        return StorageObject.objects.filter(stored_at=obj).count()

    def validate(self, data):
        instance = self.instance
        parent = data.get('stored_at')

        if instance and parent:
            if instance.id == parent.id:
                raise ValidationError("A storage object cannot be its own parent")

            children = instance.get_all_children()
            if parent.id in [child.id for child in children]:
                raise ValidationError(
                    "Cannot set parent to be one of the object's children"
                )

        return data

    class Meta:
        model = StorageObject
        fields = [
            'id',
            'object_name',
            'object_type',
            'object_description',
            'created_at',
            'updated_at',
            'can_delete',
            'stored_at',
            'stored_reagents',
            'png_base64',
            'user',
            'access_lab_groups',
            'path_to_root',
            'child_count'
        ]

class ReagentSubscriptionSerializer(ModelSerializer):
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = ReagentSubscription
        fields = [
            'id', 'user', 'stored_reagent',
            'notify_on_low_stock', 'notify_on_expiry',
            'created_at'
        ]
        read_only_fields = ['id', 'user', 'created_at']

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['user'] = user

        try:
            subscription = ReagentSubscription.objects.get(
                user=user,
                stored_reagent=validated_data['stored_reagent']
            )
            subscription.notify_on_low_stock = validated_data.get('notify_on_low_stock',
                                                                  subscription.notify_on_low_stock)
            subscription.notify_on_expiry = validated_data.get('notify_on_expiry', subscription.notify_on_expiry)
            subscription.save()
            return subscription
        except ReagentSubscription.DoesNotExist:
            return super().create(validated_data)

class StoredReagentSerializer(ModelSerializer):
    reagent = ReagentSerializer(read_only=True)
    user = UserBasicSerializer(read_only=True)
    storage_object = SerializerMethodField()
    current_quantity = SerializerMethodField()
    metadata_columns = SerializerMethodField()
    created_by_session = SerializerMethodField()
    reagent_id = PrimaryKeyRelatedField(
        queryset=Reagent.objects.all(),
        write_only=True,
        source='reagent'
    )
    storage_object_id = PrimaryKeyRelatedField(
        queryset=StorageObject.objects.all(),
        write_only=True,
        source='storage_object'
    )
    is_subscribed = SerializerMethodField()
    subscription = SerializerMethodField()
    subscriber_count = SerializerMethodField()

    def get_storage_object(self, obj):
        return {"id": obj.storage_object.id, "object_name": obj.storage_object.object_name}

    def get_current_quantity(self, obj):
        return obj.get_current_quantity()

    def get_metadata_columns(self, obj):
        if obj.metadata_columns:
            return MetadataColumnSerializer(obj.metadata_columns.all(), many=True).data
        return []

    def get_created_by_session(self, obj):
        if obj.created_by_session:
            return obj.created_by_session.unique_id
        return None

    def get_created_by_step(self, obj):
        if obj.created_by_step:
            return ProtocolStepSerializer(obj.created_by_step, many=False).data
        return None

    def get_is_subscribed(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            return obj.subscriptions.filter(user=request.user).exists()
        return False

    def get_subscription(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        try:
            subscription = obj.subscriptions.get(user=request.user)
            return {
                'id': subscription.id,
                'notify_on_low_stock': subscription.notify_on_low_stock,
                'notify_on_expiry': subscription.notify_on_expiry,
                'created_at': subscription.created_at
            }
        except ReagentSubscription.DoesNotExist:
            return None

    def get_subscriber_count(self, obj):
        return obj.subscriptions.count()

    class Meta:
        model = StoredReagent
        fields = [
            'id', 'reagent', 'reagent_id', 'storage_object', 'storage_object_id',
            'quantity', 'notes', 'user', 'created_at', 'updated_at', 'current_quantity',
            'png_base64', 'barcode', 'shareable', 'expiration_date', 'created_by_session',
            'created_by_step', 'metadata_columns',
            'notify_on_low_stock', 'last_notification_sent', 'low_stock_threshold',
            'notify_days_before_expiry', 'notify_on_expiry', 'last_expiry_notification_sent',
            'is_subscribed', 'subscription', 'subscriber_count'
        ]
        read_only_fields = ['created_at', 'updated_at', 'last_notification_sent', 'last_expiry_notification_sent']

class ReagentActionSerializer(ModelSerializer):
    user = SerializerMethodField()

    def get_user(self, obj):
        return obj.user.username

    class Meta:
        model = ReagentAction
        fields = ['id', 'reagent', 'action_type', 'notes', 'quantity', 'created_at', 'updated_at', 'user', 'step_reagent']


class LabGroupSerializer(ModelSerializer):
    default_storage = SerializerMethodField()
    service_storage = SerializerMethodField()
    managers = SerializerMethodField()

    def get_default_storage(self, obj):
        if obj.default_storage:
            return {"id": obj.default_storage.id, "object_name": obj.default_storage.object_name, "object_type": obj.default_storage.object_type, "object_description": obj.default_storage.object_description}
        return None

    def get_service_storage(self, obj):
        if obj.service_storage:
            return {"id": obj.service_storage.id, "object_name": obj.service_storage.object_name, "object_type": obj.service_storage.object_type, "object_description": obj.service_storage.object_description}
        return None

    def get_managers(self, obj):
        return [{"id": manager.id, "username": manager.username, "first_name": manager.first_name, "last_name": manager.last_name} for manager in obj.managers.all()]

    class Meta:
        model = LabGroup
        fields = ['id', 'name', 'created_at', 'updated_at', 'description', 'default_storage', 'is_professional', 'service_storage', 'managers']


class MetadataColumnSerializer(ModelSerializer):
    modifiers = SerializerMethodField()

    def get_modifiers(self, obj):
        if obj.modifiers:
            return json.loads(obj.modifiers)
        return []

    class Meta:
        model = MetadataColumn
        fields = [
            "id",
            "name",
            "type",
            "column_position",
            "value",
            "stored_reagent", "created_at", "updated_at", "not_applicable", "mandatory", "modifiers", "readonly", "hidden", "auto_generated"
        ]

class SubcellularLocationSerializer(ModelSerializer):
    class Meta:
        model = SubcellularLocation
        fields = ['location_identifier', 'topology_identifier', 'orientation_identifier', 'accession', 'definition', 'synonyms', 'content', 'is_a', 'part_of', 'keyword', 'gene_ontology', 'annotation', 'references', 'links']

class TissueSerializer(ModelSerializer):
    class Meta:
        model = Tissue
        fields = ["identifier", "accession", "synonyms", "cross_references"]

class HumanDiseaseSerializer(ModelSerializer):
    class Meta:
        model = HumanDisease
        fields = ["identifier", "acronym", "accession", "synonyms", "cross_references", "definition", "keywords"]

class MSUniqueVocabulariesSerializer(ModelSerializer):
    class Meta:
        model = MSUniqueVocabularies
        fields = ["accession", "name", "definition", "term_type"]

class SpeciesSerializer(ModelSerializer):
    class Meta:
        model = Species
        fields = ['id', 'code', 'taxon', 'common_name', 'official_name', 'synonym']

class UnimodSerializer(ModelSerializer):
    class Meta:
        model = Unimod
        fields = ["accession", "name", "definition", "additional_data"]

class InstrumentJobSerializer(ModelSerializer):
    user = SerializerMethodField()
    project = SerializerMethodField()
    session = SerializerMethodField()
    protocol = SerializerMethodField()
    user_annotations = SerializerMethodField()
    staff_annotations = SerializerMethodField()
    staff = SerializerMethodField()
    instrument_usage = SerializerMethodField()
    stored_reagent = SerializerMethodField()
    user_metadata = SerializerMethodField()
    staff_metadata = SerializerMethodField()
    service_lab_group = SerializerMethodField()
    selected_template = SerializerMethodField()

    def get_selected_template(self, obj):
        if obj.selected_template:
            return MetadataTableTemplateSerializer(obj.selected_template).data
        return None

    def get_service_lab_group(self, obj):
        if obj.service_lab_group:
            return {"id": obj.service_lab_group.id, "name": obj.service_lab_group.name}
        return None

    def get_user(self, obj):
        if obj.user:
            return {"id": obj.user.id, "username": obj.user.username}
        return None

    def get_project(self, obj):
        if obj.project:
            return {"id": obj.project.id, "project_name": obj.project.project_name, "project_description": obj.project.project_description}
        return None

    def get_session(self, obj):
        if obj.session:
            return {"id": obj.session.id, "name": obj.session.name, "unique_id": obj.session.unique_id}
        return None

    def get_protocol(self, obj):
        if obj.protocol:
            return {"id": obj.protocol.id, "protocol_title": obj.protocol.protocol_title, "protocol_description": obj.protocol.protocol_description}
        return None

    def get_user_annotations(self, obj):
        # sort by updated_at from newest to oldest
        annotations = obj.user_annotations.all().order_by('-updated_at')
        return AnnotationSerializer(annotations, many=True).data

    def get_staff_annotations(self, obj):
        annotations = obj.staff_annotations.all().order_by('-updated_at')
        return AnnotationSerializer(annotations, many=True).data

    def get_staff(self, obj):
        if obj.staff.all():
            return [{"id": x.id, "username": x.username} for x in obj.staff.all()]
        return []

    def get_instrument_usage(self, obj):
        if obj.instrument_usage:
            return InstrumentUsageSerializer(obj.instrument_usage, many=False).data
        return None

    def get_user_metadata(self, obj):
        if obj.user_metadata:
            return MetadataColumnSerializer(obj.user_metadata.all(), many=True).data
        return []

    def get_staff_metadata(self, obj):
        if obj.staff_metadata:
            return MetadataColumnSerializer(obj.staff_metadata.all(), many=True).data
        return []

    def get_stored_reagent(self, obj):
        if obj.stored_reagent:
            return StoredReagentSerializer(obj.stored_reagent, many=False).data
        return None

    class Meta:
        model = InstrumentJob
        fields = [
            'id',
            'instrument',
            'user',
            'created_at',
            'updated_at',
            'project',
            'session',
            'protocol',
            'job_type',
            'user_annotations',
            'staff_annotations',
            'assigned', 'staff',
            'instrument_usage',
            'job_name', 'user_metadata', 'staff_metadata',
            'sample_number',
            'sample_type', 'funder', 'cost_center',
            'stored_reagent',
            'injection_volume',
            'injection_unit',
            'search_engine',
            'search_engine_version',
            'search_details',
            'location',
            'status',
            'funder',
            'cost_center',
            'service_lab_group',
            'selected_template',
            'submitted_at',
            'completed_at',
        ]

class FavouriteMetadataOptionSerializer(ModelSerializer):
    class Meta:
        model = FavouriteMetadataOption
        fields = ['id', 'user', 'name', 'type', 'value', 'display_value', 'service_lab_group', 'lab_group', 'preset', 'created_at', 'updated_at', 'is_global']

class PresetSerializer(ModelSerializer):
    class Meta:
        model = Preset
        fields = ['id', 'name', 'user', 'created_at', 'updated_at']

class MetadataTableTemplateSerializer(ModelSerializer):
    user_columns = SerializerMethodField()
    staff_columns = SerializerMethodField()
    hidden_user_columns = SerializerMethodField()
    hidden_staff_columns = SerializerMethodField()
    field_mask_mapping = SerializerMethodField()

    def get_user_columns(self, obj):
        data = obj.user_columns.all()
        if data.exists():
            return MetadataColumnSerializer(data, many=True).data
        return []

    def get_staff_columns(self, obj):
        data = obj.staff_columns.all()
        if data.exists():
            return MetadataColumnSerializer(data, many=True).data
        return []

    def get_hidden_user_columns(self, obj):
        data = obj.user_columns.filter(hidden=True)
        if data.exists():
            return data.count()
        return 0

    def get_hidden_staff_columns(self, obj):
        data = obj.staff_columns.filter(hidden=True)
        if data.exists():
            return data.count()
        return 0

    def get_field_mask_mapping(self, obj):
        if obj.field_mask_mapping:
            return json.loads(obj.field_mask_mapping)
        return []

    class Meta:
        model = MetadataTableTemplate
        fields = [
            'id',
            'name',
            'user',
            'created_at',
            'updated_at',
            'user_columns',
            'hidden_user_columns',
            'staff_columns',
            'hidden_staff_columns',
            'service_lab_group',
            'lab_group',
            'field_mask_mapping'
        ]




class MessageAttachmentSerializer(ModelSerializer):
    download_url = SerializerMethodField()

    class Meta:
        model = MessageAttachment
        fields = ['id', 'file', 'file_name', 'file_size', 'content_type', 'created_at']
        read_only_fields = ['file_size', 'content_type', 'created_at']

    def validate(self, attrs):
        if 'file' in attrs:
            file = attrs['file']
            attrs['file_size'] = file.size
            attrs['content_type'] = file.content_type
            if not attrs.get('file_name'):
                attrs['file_name'] = file.name
        return attrs


class MessageRecipientSerializer(ModelSerializer):
    """Serializer for message read status by recipients"""
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = MessageRecipient
        fields = ['id', 'user', 'is_read', 'read_at', 'is_archived', 'is_deleted']
        read_only_fields = ['read_at']


class MessageSerializer(ModelSerializer):
    """Serializer for individual messages"""
    sender = UserBasicSerializer(read_only=True)
    sender_id = PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        write_only=True,
        required=False,
        source='sender'
    )
    recipients = MessageRecipientSerializer(many=True, read_only=True)
    attachments = MessageAttachmentSerializer(many=True, read_only=True)
    is_read = SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'sender', 'sender_id', 'content', 'created_at', 'updated_at',
            'message_type', 'priority', 'expires_at', 'recipients', 'attachments',
            'project', 'protocol', 'session', 'instrument', 'instrument_job',
            'stored_reagent', 'is_read'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_is_read(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        recipient = obj.recipients.filter(user=request.user).first()
        return recipient.is_read if recipient else False


class ThreadMessageSerializer(ModelSerializer):
    sender = UserBasicSerializer(read_only=True)
    attachment_count = SerializerMethodField()
    is_read = SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'sender', 'content', 'created_at', 'message_type',
            'priority', 'attachment_count', 'is_read'
        ]

    def get_attachment_count(self, obj):
        return obj.attachments.count()

    def get_is_read(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        recipient = obj.recipients.filter(user=request.user).first()
        return recipient.is_read if recipient else False


class LabGroupBasicSerializer(ModelSerializer):
    class Meta:
        model = LabGroup
        fields = ['id', 'name']


class MessageThreadSerializer(ModelSerializer):
    participants = UserBasicSerializer(many=True, read_only=True)
    participant_ids = PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        write_only=True,
        required=False,
        many=True,
        source='participants'
    )
    latest_message = SerializerMethodField()
    unread_count = SerializerMethodField()
    lab_group = LabGroupBasicSerializer(read_only=True)
    lab_group_id = PrimaryKeyRelatedField(
        queryset=LabGroup.objects.all(),
        write_only=True,
        required=False,
        source='lab_group'
    )
    creator = UserBasicSerializer(read_only=True)

    class Meta:
        model = MessageThread
        fields = [
            'id', 'title', 'created_at', 'updated_at', 'participants',
            'participant_ids', 'is_system_thread', 'lab_group', 'lab_group_id',
            'latest_message', 'unread_count', 'creator'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_latest_message(self, obj):
        latest = obj.messages.order_by('-created_at').first()
        if latest:
            return ThreadMessageSerializer(latest, context=self.context).data
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 0

        # Count messages where user is a recipient and message is unread
        return MessageRecipient.objects.filter(
            message__thread=obj,
            user=request.user,
            is_read=False,
            is_deleted=False
        ).count()


class MessageThreadDetailSerializer(MessageThreadSerializer):
    messages = SerializerMethodField()

    class Meta(MessageThreadSerializer.Meta):
        fields = MessageThreadSerializer.Meta.fields + ['messages']

    def get_messages(self, obj):
        messages = obj.messages.order_by('created_at')
        return ThreadMessageSerializer(messages, many=True, context=self.context).data


class SiteSettingsSerializer(ModelSerializer):
    """Serializer for site settings management"""
    updated_by = UserBasicSerializer(read_only=True)
    
    class Meta:
        model = SiteSettings
        fields = [
            'id', 'is_active', 'site_name', 'site_tagline', 'logo', 'favicon',
            'banner_enabled', 'banner_text', 'banner_color', 'banner_text_color', 
            'banner_dismissible', 'primary_color', 'secondary_color', 'footer_text',
            'allow_import_protocols', 'allow_import_sessions', 'allow_import_annotations',
            'allow_import_projects', 'allow_import_reagents', 'allow_import_instruments',
            'allow_import_lab_groups', 'allow_import_messaging', 'allow_import_support_models',
            'staff_only_import_override', 'import_archive_size_limit_mb',
            'created_at', 'updated_at', 'updated_by'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'updated_by']
        
    def create(self, validated_data):
        # Set updated_by from request user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['updated_by'] = request.user
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        # Set updated_by from request user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['updated_by'] = request.user
        return super().update(instance, validated_data)


class BackupLogSerializer(ModelSerializer):
    """Serializer for backup log entries"""
    file_size_mb = ReadOnlyField()
    backup_type_display = CharField(source='get_backup_type_display', read_only=True)
    status_display = CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = BackupLog
        fields = [
            'id', 'backup_type', 'backup_type_display', 'status', 'status_display',
            'started_at', 'completed_at', 'duration_seconds', 'backup_file_path',
            'file_size_bytes', 'file_size_mb', 'error_message', 'success_message',
            'triggered_by', 'container_id'
        ]
        read_only_fields = ['id', 'started_at']


class DocumentPermissionSerializer(ModelSerializer):
    """Serializer for document permissions and folder permissions"""
    user = UserBasicSerializer(read_only=True)
    lab_group = StringRelatedField(read_only=True)
    shared_by = UserBasicSerializer(read_only=True)
    is_expired = ReadOnlyField()
    
    # Input fields for creating permissions
    user_id = IntegerField(write_only=True, required=False)
    lab_group_id = IntegerField(write_only=True, required=False)
    
    class Meta:
        model = DocumentPermission
        fields = [
            'id', 'annotation', 'folder', 'user', 'lab_group', 'user_id', 'lab_group_id',
            'can_view', 'can_download', 'can_comment', 'can_edit', 'can_share', 'can_delete',
            'shared_by', 'shared_at', 'expires_at', 'last_accessed', 'access_count', 'is_expired'
        ]
        read_only_fields = ['id', 'shared_by', 'shared_at', 'last_accessed', 'access_count']
    
    def validate(self, data):
        """Validate permission creation constraints"""
        user_id = data.get('user_id')
        lab_group_id = data.get('lab_group_id')
        annotation = data.get('annotation')
        folder = data.get('folder')
        
        # Ensure either user_id or lab_group_id is provided, but not both
        if not user_id and not lab_group_id:
            raise ValidationError("Either user_id or lab_group_id must be provided")
        
        if user_id and lab_group_id:
            raise ValidationError("Cannot specify both user_id and lab_group_id")
        
        # Ensure either annotation or folder is provided, but not both
        if not annotation and not folder:
            raise ValidationError("Either annotation or folder must be provided")
        
        if annotation and folder:
            raise ValidationError("Cannot specify both annotation and folder")
        
        # Validate annotation has file if specified
        if annotation and not annotation.file:
            raise ValidationError("Can only set permissions on annotations with files")
        
        # Validate folder is shared document folder if specified
        if folder and not folder.is_shared_document_folder:
            raise ValidationError("Can only set permissions on shared document folders")
        
        return data
    
    def create(self, validated_data):
        user_id = validated_data.pop('user_id', None)
        lab_group_id = validated_data.pop('lab_group_id', None)
        
        # Set the shared_by to the current user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['shared_by'] = request.user
        
        # Set user or lab_group based on provided ID
        if user_id:
            validated_data['user_id'] = user_id
        if lab_group_id:
            validated_data['lab_group_id'] = lab_group_id
        
        return super().create(validated_data)


class SharedDocumentSerializer(AnnotationSerializer):
    """Extended annotation serializer for document sharing"""
    document_permissions = DocumentPermissionSerializer(many=True, read_only=True)
    user_permissions = SerializerMethodField()
    sharing_stats = SerializerMethodField()
    file_info = SerializerMethodField()
    
    class Meta(AnnotationSerializer.Meta):
        fields = AnnotationSerializer.Meta.fields + [
            'document_permissions', 'user_permissions', 'sharing_stats', 'file_info'
        ]
    
    def get_user_permissions(self, obj):
        """Get current user's permissions for this document"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        
        # Owner has all permissions
        if obj.user == request.user:
            return {
                'can_view': True,
                'can_download': True,
                'can_comment': True,
                'can_edit': True,
                'can_share': True,
                'can_delete': True,
                'is_owner': True
            }
        
        # Check specific permissions
        permissions = {}
        for perm_type in ['view', 'download', 'comment', 'edit', 'share', 'delete']:
            permissions[f'can_{perm_type}'] = DocumentPermission.user_can_access(
                obj, request.user, perm_type
            )
        permissions['is_owner'] = False
        
        return permissions
    
    def get_sharing_stats(self, obj):
        """Get sharing statistics"""
        if not obj.file:
            return None
        
        permissions = obj.document_permissions.all()
        total_shared = permissions.count()
        total_users = permissions.filter(user__isnull=False).count()
        total_groups = permissions.filter(lab_group__isnull=False).count()
        total_access_count = sum(p.access_count for p in permissions)
        
        return {
            'total_shared': total_shared,
            'shared_with_users': total_users,
            'shared_with_groups': total_groups,
            'total_access_count': total_access_count,
        }
    
    def get_file_info(self, obj):
        """Get file information"""
        if not obj.file:
            return None
        
        try:
            import os
            file_path = obj.file.path
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(obj.file.name)
            file_ext = os.path.splitext(file_name)[1].lower()
            
            return {
                'name': file_name,
                'size': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2),
                'extension': file_ext,
                'url': obj.file.url if obj.file else None,
            }
        except (OSError, AttributeError):
            return {
                'name': os.path.basename(obj.file.name) if obj.file else None,
                'url': obj.file.url if obj.file else None,
            }


# Import Tracking Serializers

class ImportedObjectSerializer(ModelSerializer):
    """Serializer for objects created during import"""
    
    class Meta:
        model = ImportedObject
        fields = ['id', 'model_name', 'object_id', 'original_id', 'created_at', 'object_data']
        read_only_fields = fields


class ImportedFileSerializer(ModelSerializer):
    """Serializer for files created during import"""
    
    class Meta:
        model = ImportedFile
        fields = ['id', 'file_path', 'original_name', 'file_size_bytes', 'created_at']
        read_only_fields = fields


class ImportedRelationshipSerializer(ModelSerializer):
    """Serializer for relationships created during import"""
    
    class Meta:
        model = ImportedRelationship
        fields = ['id', 'from_model', 'from_object_id', 'to_model', 'to_object_id', 'relationship_field', 'created_at']
        read_only_fields = fields


class ImportTrackerSerializer(ModelSerializer):
    """Serializer for import tracking with detailed information"""
    
    user_username = CharField(source='user.username', read_only=True)
    user_full_name = SerializerMethodField()
    duration = SerializerMethodField()
    imported_objects = ImportedObjectSerializer(many=True, read_only=True)
    imported_files = ImportedFileSerializer(many=True, read_only=True)
    imported_relationships = ImportedRelationshipSerializer(many=True, read_only=True)
    stats = SerializerMethodField()
    
    class Meta:
        model = ImportTracker
        fields = [
            'id', 'import_id', 'user', 'user_username', 'user_full_name',
            'archive_path', 'archive_size_mb',
            'import_status', 'import_options', 'metadata',
            'import_started_at', 'import_completed_at', 'duration',
            'total_objects_created', 'total_files_imported', 'total_relationships_created',
            'can_revert', 'revert_reason', 'reverted_at', 'reverted_by',
            'imported_objects', 'imported_files', 'imported_relationships', 'stats'
        ]
        read_only_fields = [
            'id', 'import_id', 'user_username', 'user_full_name', 
            'duration', 'imported_objects', 'imported_files', 'imported_relationships', 'stats'
        ]
    
    def get_user_full_name(self, obj):
        """Get user's full name"""
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
        return None
    
    def get_duration(self, obj):
        """Calculate import duration"""
        if obj.import_started_at and obj.import_completed_at:
            delta = obj.import_completed_at - obj.import_started_at
            return {
                'seconds': delta.total_seconds(),
                'formatted': str(delta).split('.')[0]  # Remove microseconds
            }
        return None
    
    def get_stats(self, obj):
        """Get import statistics"""
        return {
            'objects_by_type': self._get_objects_by_type(obj),
            'files_by_type': self._get_files_by_type(obj),
            'relationships_by_field': self._get_relationships_by_field(obj),
            'status_color': self._get_status_color(obj.import_status),
        }
    
    def _get_objects_by_type(self, obj):
        """Group imported objects by model type"""
        objects_by_type = {}
        for imported_obj in obj.imported_objects.all():
            model_name = imported_obj.model_name
            if model_name not in objects_by_type:
                objects_by_type[model_name] = 0
            objects_by_type[model_name] += 1
        return objects_by_type
    
    def _get_files_by_type(self, obj):
        """Group imported files by extension"""
        files_by_type = {}
        for imported_file in obj.imported_files.all():
            file_ext = imported_file.file_path.split('.')[-1].lower() if '.' in imported_file.file_path else 'no_ext'
            if file_ext not in files_by_type:
                files_by_type[file_ext] = 0
            files_by_type[file_ext] += 1
        return files_by_type
    
    def _get_relationships_by_field(self, obj):
        """Group imported relationships by field name"""
        relationships_by_field = {}
        for imported_rel in obj.imported_relationships.all():
            field_name = imported_rel.relationship_field
            if field_name not in relationships_by_field:
                relationships_by_field[field_name] = 0
            relationships_by_field[field_name] += 1
        return relationships_by_field
    
    def _get_status_color(self, status):
        """Get color for import status"""
        status_colors = {
            'in_progress': 'primary',
            'completed': 'success',
            'failed': 'danger',
            'reverted': 'warning'
        }
        return status_colors.get(status, 'secondary')


class ImportTrackerListSerializer(ModelSerializer):
    """Simplified serializer for import tracker lists"""
    
    user_username = CharField(source='user.username', read_only=True)
    user_full_name = SerializerMethodField()
    duration = SerializerMethodField()
    status_color = SerializerMethodField()
    
    class Meta:
        model = ImportTracker
        fields = [
            'id', 'import_id', 'user', 'user_username', 'user_full_name',
            'archive_path', 'archive_size_mb', 'import_status', 'status_color',
            'import_started_at', 'import_completed_at', 'duration',
            'total_objects_created', 'total_files_imported', 'total_relationships_created',
            'can_revert', 'reverted_at', 'reverted_by'
        ]
        read_only_fields = fields
    
    def get_user_full_name(self, obj):
        """Get user's full name"""
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
        return None
    
    def get_duration(self, obj):
        """Calculate import duration"""
        if obj.import_started_at and obj.import_completed_at:
            delta = obj.import_completed_at - obj.import_started_at
            return {
                'seconds': delta.total_seconds(),
                'formatted': str(delta).split('.')[0]  # Remove microseconds
            }
        return None
    
    def get_status_color(self, obj):
        """Get color for import status"""
        status_colors = {
            'in_progress': 'primary',
            'completed': 'success',
            'failed': 'danger',
            'reverted': 'warning'
        }
        return status_colors.get(obj.import_status, 'secondary')


class HistoricalRecordSerializer(ModelSerializer):
    """Generic serializer for historical records"""
    history_user = CharField(source='history_user.username', read_only=True)
    history_date = ReadOnlyField()
    history_type = ReadOnlyField()
    history_id = ReadOnlyField()
    
    class Meta:
        model = None  # Will be set dynamically
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        # Set the model dynamically based on the instance
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, '__class__'):
            self.Meta.model = self.instance.__class__
        elif hasattr(self, 'context') and 'view' in self.context:
            # Get model from viewset's queryset
            view = self.context['view']
            if hasattr(view, 'get_queryset'):
                queryset = view.get_queryset()
                if queryset and hasattr(queryset, 'model'):
                    self.Meta.model = queryset.model