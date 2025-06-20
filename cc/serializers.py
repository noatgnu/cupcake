from django.contrib.auth.models import User
from rest_framework.fields import ReadOnlyField
from rest_framework.serializers import ModelSerializer, SerializerMethodField, PrimaryKeyRelatedField
import json
from cc.models import ProtocolModel, ProtocolStep, Annotation, StepVariation, Session, TimeKeeper, ProtocolSection, \
    ProtocolRating, Reagent, ProtocolReagent, StepReagent, StepTag, ProtocolTag, Tag, AnnotationFolder, Project, \
    Instrument, InstrumentUsage, StorageObject, StoredReagent, ReagentAction, LabGroup, MSUniqueVocabularies, \
    HumanDisease, Tissue, SubcellularLocation, MetadataColumn, Species, Unimod, InstrumentJob, FavouriteMetadataOption, \
    Preset, MetadataTableTemplate, ExternalContactDetails, SupportInformation, ExternalContact, MaintenanceLog, \
    MessageRecipient, MessageThread, Message, MessageAttachment, ReagentSubscription


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
    class Meta:
        model = AnnotationFolder
        fields = ['id', 'folder_name', 'created_at', 'updated_at', 'parent_folder', 'session', 'instrument', 'stored_reagent']

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
            'last_warranty_notification_sent'
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

    def get_default_storage(self, obj):
        if obj.default_storage:
            return {"id": obj.default_storage.id, "object_name": obj.default_storage.object_name, "object_type": obj.default_storage.object_type, "object_description": obj.default_storage.object_description}
        return None

    def get_service_storage(self, obj):
        if obj.service_storage:
            return {"id": obj.service_storage.id, "object_name": obj.service_storage.object_name, "object_type": obj.service_storage.object_type, "object_description": obj.service_storage.object_description}
        return None


    class Meta:
        model = LabGroup
        fields = ['id', 'name', 'created_at', 'updated_at', 'description', 'default_storage', 'is_professional', 'service_storage']


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