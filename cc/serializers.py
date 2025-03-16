from django.contrib.auth.models import User
from rest_framework.serializers import ModelSerializer, SerializerMethodField
import json
from cc.models import ProtocolModel, ProtocolStep, Annotation, StepVariation, Session, TimeKeeper, ProtocolSection, \
    ProtocolRating, Reagent, ProtocolReagent, StepReagent, StepTag, ProtocolTag, Tag, AnnotationFolder, Project, \
    Instrument, InstrumentUsage, StorageObject, StoredReagent, ReagentAction, LabGroup, MSUniqueVocabularies, \
    HumanDisease, Tissue, SubcellularLocation, MetadataColumn, Species, Unimod, InstrumentJob, FavouriteMetadataOption, \
    Preset, MetadataTableTemplate


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
        fields = ['id', 'protocol', 'step_id', 'step_description', 'step_section', 'step_duration', 'next_step', 'annotations', 'variations', 'previous_step', 'reagents', 'tags', 'created_at', 'updated_at']


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
        fields = ['id', 'step', 'session', 'annotation', 'file', 'created_at', 'updated_at', 'annotation_type', 'transcribed', 'transcription', 'language', 'translation', 'scratched', 'annotation_name', 'folder', 'summary', 'instrument_usage', 'metadata_columns', 'fixed', 'user', 'stored_reagent']


class StepVariationSerializer(ModelSerializer):
    class Meta:
        model = StepVariation
        fields = ['id', 'step', 'variation_description', 'variation_duration']


class SessionSerializer(ModelSerializer):
    time_keeper = SerializerMethodField()
    projects = SerializerMethodField()
    def get_time_keeper(self, obj):
        return TimeKeeperSerializer(obj.time_keeper.all(), many=True).data
    def get_projects(self, obj):
        return [x.id for x in obj.projects.all()]

    class Meta:
        model = Session
        fields = ['id', 'user', 'unique_id', 'enabled', 'created_at', 'updated_at', 'protocols', 'name', 'time_keeper', 'enabled', 'started_at', 'ended_at', 'projects']
        lookup_field = 'unique_id'


class TimeKeeperSerializer(ModelSerializer):
    class Meta:
        model = TimeKeeper
        fields = ['id', 'start_time', 'session', 'step', 'started', 'current_duration']


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
        fields = ['id', 'folder_name', 'created_at', 'updated_at', 'parent_folder', 'session']

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


class InstrumentSerializer(ModelSerializer):
    metadata_columns = SerializerMethodField()
    def get_metadata_columns(self, obj):
        if obj.metadata_columns:
            return MetadataColumnSerializer(obj.metadata_columns.all(), many=True).data
        return []

    class Meta:
        model = Instrument
        fields = ['id', 'instrument_name', 'instrument_description', 'created_at', 'updated_at', 'enabled', 'metadata_columns']


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
            'description'
        ]

class StorageObjectSerializer(ModelSerializer):
    stored_reagents = SerializerMethodField()
    user = SerializerMethodField()

    def get_user(self, obj):
        if obj.user:
            return obj.user.username
        return None

    def get_stored_reagents(self, obj):
        return StoredReagentSerializer(obj.stored_reagents.all(), many=True).data

    class Meta:
        model = StorageObject
        fields = ['id', 'object_name', 'object_type', 'object_description', 'created_at', 'updated_at', 'can_delete', 'stored_at', 'stored_reagents', 'png_base64', 'user', 'access_lab_groups']


class StoredReagentSerializer(ModelSerializer):
    reagent = SerializerMethodField()
    user = SerializerMethodField()
    storage_object = SerializerMethodField()
    current_quantity = SerializerMethodField()
    metadata_columns = SerializerMethodField()
    created_by_session = SerializerMethodField()

    def get_reagent(self, obj):
        return ReagentSerializer(obj.reagent, many=False).data

    def get_user(self, obj):
        return obj.user.username

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

    class Meta:
        model = StoredReagent
        fields = ['id', 'reagent', 'quantity', 'created_at', 'updated_at', 'storage_object', 'user', 'notes', 'png_base64', 'barcode', 'shareable', 'access_all', 'current_quantity', 'metadata_columns', 'expiration_date', 'created_by_project', 'created_by_protocol', 'created_by_session', 'created_by_step']


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
            'selected_template'
            'submitted_at',
            'completed_at',
        ]

class FavouriteMetadataOptionSerializer(ModelSerializer):
    class Meta:
        model = FavouriteMetadataOption
        fields = ['id', 'user', 'name', 'type', 'value', 'display_value', 'service_lab_group', 'lab_group', 'preset', 'created_at', 'updated_at']

class PresetSerializer(ModelSerializer):
    class Meta:
        model = Preset
        fields = ['id', 'name', 'user', 'created_at', 'updated_at']

class MetadataTableTemplateSerializer(ModelSerializer):
    user_columns = SerializerMethodField()
    staff_columns = SerializerMethodField()
    hidden_user_columns = SerializerMethodField()
    hidden_staff_columns = SerializerMethodField()

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
            'lab_group'
        ]