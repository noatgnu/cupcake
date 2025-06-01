import base64
import hashlib
import hmac
import io
import json
import time
import uuid
from datetime import datetime, timedelta
from django.core.mail import send_mail
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.models import User
from django.core.signing import TimestampSigner, loads, dumps, BadSignature, SignatureExpired
from django.db.models import Q, Max
from django.db.models.expressions import result
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django_filters.views import FilterMixin
from drf_chunked_upload.models import ChunkedUpload
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.filters import SearchFilter, OrderingFilter
from django.core.files.base import File as djangoFile
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination
from sdrf_pipelines.sdrf.sdrf import SdrfDataFrame

from cc.filters import UnimodFilter, UnimodSearchFilter, MSUniqueVocabulariesSearchFilter, HumanDiseaseSearchFilter, \
    TissueSearchFilter, SubcellularLocationSearchFilter, SpeciesSearchFilter
from cc.models import ProtocolModel, ProtocolStep, Annotation, Session, StepVariation, TimeKeeper, ProtocolSection, \
    ProtocolRating, Reagent, StepReagent, ProtocolReagent, ProtocolTag, StepTag, Tag, AnnotationFolder, Project, \
    Instrument, InstrumentUsage, InstrumentPermission, StorageObject, StoredReagent, ReagentAction, LabGroup, Species, \
    SubcellularLocation, HumanDisease, Tissue, MetadataColumn, MSUniqueVocabularies, Unimod, InstrumentJob, \
    FavouriteMetadataOption, Preset, MetadataTableTemplate, MaintenanceLog, SupportInformation, ExternalContact, \
    ExternalContactDetails, Message, MessageRecipient, MessageAttachment, MessageRecipient, MessageThread, \
    ReagentSubscription
from cc.permissions import OwnerOrReadOnly, InstrumentUsagePermission, InstrumentViewSetPermission, IsParticipantOrAdmin
from cc.rq_tasks import transcribe_audio_from_video, transcribe_audio, create_docx, llama_summary, remove_html_tags, \
    ocr_b64_image, export_data, import_data, llama_summary_transcript, export_sqlite, export_instrument_job_metadata, \
    import_sdrf_file, validate_sdrf_file, export_excel_template, export_instrument_usage, import_excel, sdrf_validate, export_reagent_actions, import_reagents_from_file, check_instrument_warranty_maintenance
from cc.serializers import ProtocolModelSerializer, ProtocolStepSerializer, AnnotationSerializer, \
    SessionSerializer, StepVariationSerializer, TimeKeeperSerializer, ProtocolSectionSerializer, UserSerializer, \
    ProtocolRatingSerializer, ReagentSerializer, StepReagentSerializer, ProtocolReagentSerializer, \
    ProtocolTagSerializer, StepTagSerializer, TagSerializer, AnnotationFolderSerializer, ProjectSerializer, \
    InstrumentSerializer, InstrumentUsageSerializer, StorageObjectSerializer, StoredReagentSerializer, \
    ReagentActionSerializer, LabGroupSerializer, SpeciesSerializer, SubcellularLocationSerializer, \
    HumanDiseaseSerializer, TissueSerializer, MetadataColumnSerializer, MSUniqueVocabulariesSerializer, \
    UnimodSerializer, InstrumentJobSerializer, FavouriteMetadataOptionSerializer, PresetSerializer, \
    MetadataTableTemplateSerializer, MaintenanceLogSerializer, SupportInformationSerializer, ExternalContactSerializer, \
    ExternalContactDetailsSerializer, MessageSerializer, MessageRecipientSerializer, MessageAttachmentSerializer, \
    MessageRecipientSerializer, MessageThreadSerializer, MessageThreadDetailSerializer, ReagentSubscriptionSerializer
from cc.utils import user_metadata, staff_metadata, send_slack_notification

class ProtocolViewSet(ModelViewSet, FilterMixin):
    permission_classes = [OwnerOrReadOnly]
    queryset = ProtocolModel.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['protocol_title', 'protocol_description']
    ordering_fields = ['protocol_title', 'protocol_created_on']
    filterset_fields = ['protocol_title', 'protocol_created_on']
    serializer_class = ProtocolModelSerializer

    def create(self, request, *args, **kwargs):
        if "url" in request.data:
            protocol = ProtocolModel.create_protocol_from_url(request.data['url'])
        else:
            protocol = ProtocolModel()
            protocol.protocol_title = request.data['protocol_title']
            protocol.protocol_description = request.data['protocol_description']
            protocol.save()
            section = ProtocolSection()
            section.protocol = protocol
            section.section_description = "Default Section"
            section.section_duration = 0
            section.save()
            step = ProtocolStep()
            step.step_description = "Default Step"
            step.step_duration = 0
            step.protocol = protocol
            step.step_section = section
            step.save()
        if self.request.user.is_authenticated:
            protocol.user = self.request.user
            protocol.save()
        data = self.get_serializer(protocol).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def get_associated_sessions(self, request, pk=None):
        protocol = self.get_object()
        sessions = protocol.sessions.all()
        user = self.request.user

        if user.is_authenticated:
            data = SessionSerializer(sessions.filter(Q(user=user)|Q(enabled=True)), many=True).data
        else:
            data = SessionSerializer(sessions.filter(enabled=True), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            return ProtocolModel.objects.filter(Q(user=user)|Q(enabled=True)|Q(viewers=user)|Q(editors=user))
        else:
            return ProtocolModel.objects.filter(enabled=True)

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        if obj.user == user or obj.enabled:
            return obj
        elif obj.viewers.filter(id=user.id).exists():
            if self.request.method in ["GET", "OPTIONS"]:
                return obj
            else:
                raise PermissionDenied
        elif obj.editors.filter(id=user.id).exists():
            return obj
        else:
            raise PermissionDenied

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not request.user.is_staff:
            if not instance.user == request.user and not instance.viewers.filter(id=request.user.id).exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        instance.protocol_title = request.data['protocol_title']
        instance.protocol_description = request.data['protocol_description']
        if "enabled" in request.data:
            instance.enabled = request.data['enabled']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], pagination_class=LimitOffsetPagination)
    def get_user_protocols(self, request):
        if self.request.user.is_anonymous:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        user = request.user
        search = request.query_params.get('search', None)
        protocols = ProtocolModel.objects.filter(user=user)
        if search:
            protocols = protocols.filter(Q(protocol_title__icontains=search)|Q(protocol_description__icontains=search))
        limitdata = request.query_params.get('limit', None)
        paginator = LimitOffsetPagination()
        paginator.default_limit = int(limitdata) if limitdata else 5

        pagination = paginator.paginate_queryset(protocols, request)
        if pagination is not None:
            serializer = self.get_serializer(pagination, many=True)
            return paginator.get_paginated_response(serializer.data)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def create_export(self, request, pk=None):
        protocol = self.get_object()
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        print(request.data)
        if "export_type" in request.data:
            if "session" == self.request.data["export_type"]:
                if "session" in self.request.data:
                    session_id = self.request.data['session']
                    if "format" in self.request.data:
                        if "docx" == self.request.data["format"]:
                            create_docx.delay(protocol.id, session_id, self.request.user.id, custom_id)
                            return Response(status=status.HTTP_200_OK)
            elif "protocol" == self.request.data["export_type"]:
                if "format" in self.request.data:
                    if "docx" == self.request.data["format"]:
                        create_docx.delay(protocol.id, None, self.request.user.id, custom_id)
                        return Response(status=status.HTTP_200_OK)
                    elif "tar.gz" == self.request.data["format"]:
                        export_data.delay(self.request.user.id, [protocol.id], custom_id)
                        return Response(status=status.HTTP_200_OK)
            elif "session-sqlite" == self.request.data["export_type"]:
                if "session" in self.request.data:
                    session_id = self.request.data['session']
                    export_sqlite.delay(self.request.user.id, session_id, custom_id)
                    return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def download_temp_file(self, request):
        token = request.query_params.get('token', None)
        if not token:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        signer = TimestampSigner()
        try:
            data = signer.unsign(token, max_age=60*30)
            response = HttpResponse(status=200)
            response["Content-Disposition"] = f'attachment; filename="{data}"'
            response["X-Accel-Redirect"] = f"/media/temp/{data}"
            return response
        except Exception as e:
            return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        protocol = self.get_object()
        new_protocol = ProtocolModel(user=self.request.user)
        new_protocol.protocol_title = protocol.protocol_title
        if "protocol_title" in request.data:
            new_protocol.protocol_title = request.data['protocol_title']
        new_protocol.protocol_description = protocol.protocol_description
        if "protocol_description" in request.data:
            new_protocol.protocol_description = request.data['protocol_description']
        new_protocol.protocol_id = protocol.protocol_id
        new_protocol.protocol_doi = protocol.protocol_doi
        new_protocol.protocol_url = protocol.protocol_url
        new_protocol.protocol_version_uri = protocol.protocol_version_uri
        new_protocol.protocol_created_on = protocol.protocol_created_on
        new_protocol.save()
        for tag in protocol.tags.all():
            new_tag = ProtocolTag()
            new_tag.protocol = new_protocol
            new_tag.tag = tag.tag
            new_tag.save()
        previous_step = None
        for section in protocol.sections.all():
            new_section = ProtocolSection()
            new_section.protocol = new_protocol
            new_section.section_description = section.section_description
            new_section.section_duration = section.section_duration
            new_section.created_at = section.created_at
            new_section.updated_at = section.updated_at
            new_section.save()

            for step in section.get_step_in_order():
                new_step = ProtocolStep()
                new_step.branch_from = step
                new_step.step_description = step.step_description
                new_step.step_duration = step.step_duration
                new_step.protocol = new_protocol
                new_step.step_section = new_section
                if previous_step:
                    new_step.previous_step = previous_step
                new_step.save()
                previous_step = new_step
                for reagent in step.reagents.all():
                    new_reagent = StepReagent()
                    new_reagent.reagent = reagent.reagent
                    new_reagent.step = new_step
                    new_reagent.quantity = reagent.quantity
                    new_reagent.scalable = reagent.scalable
                    new_reagent.scalable_factor = reagent.scalable_factor
                    new_reagent.save()
                    protocol_reagents = new_protocol.reagents.filter(reagent=reagent.reagent)
                    description = new_step.step_description[:]
                    for i in [f"%{reagent.id}.name%", f"%{reagent.id}.unit%", f"%{reagent.id}.quantity%", f"%{reagent.id}.scaled_quantity%"]:
                        if i in description:
                            if i == f"%{reagent.id}.name%":
                                description = description.replace(i, f"%{new_reagent.id}.name%")
                            elif i == f"%{reagent.id}.unit%":
                                description = description.replace(i, f"%{new_reagent.id}.unit%")
                            elif i == f"%{reagent.id}.quantity%":
                                description = description.replace(i, f"%{new_reagent.id}.quantity%")
                            elif i == f"%{reagent.id}.scaled_quantity%":
                                description = description.replace(i, f"%{new_reagent.id}.scaled_quantity%")
                    new_step.step_description = description
                    new_step.save()
                    if not protocol_reagents.exists():
                        ProtocolReagent.objects.create(
                            protocol=new_protocol,
                            reagent=reagent.reagent,
                            quantity=reagent.quantity)
                    else:
                        protocol_reagent = protocol_reagents.first()
                        protocol_reagent.quantity = protocol_reagent.quantity + reagent.quantity
                        protocol_reagent.save()
                    for tag in step.tags.all():
                        new_tag = StepTag()
                        new_tag.step = new_step
                        new_tag.tag = tag.tag
                        new_tag.save()

        data = self.get_serializer(new_protocol).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def check_if_title_exists(self, request):
        title = request.data['protocol_title']
        protocol = ProtocolModel.objects.filter(protocol_title=title)
        if protocol.exists():
            return Response(status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_user_role(self, request, pk=None):
        protocol = self.get_object()
        if self.request.user != protocol.user:
            raise PermissionDenied
        user = User.objects.get(username=request.data['user'])
        if user == protocol.user:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        role = request.data['role']
        if role == "viewer":
            if user in protocol.viewers.all():
                return Response(status=status.HTTP_409_CONFLICT)
            protocol.viewers.add(user)
        elif role == "editor":
            if user in protocol.editors.all():
                return Response(status=status.HTTP_409_CONFLICT)
            protocol.editors.add(user)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_editors(self, request, pk=None):
        protocol = self.get_object()
        data = UserSerializer(protocol.editors.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_viewers(self, request, pk=None):
        protocol = self.get_object()
        data = UserSerializer(protocol.viewers.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_user_role(self, request, pk=None):
        protocol = self.get_object()
        if self.request.user != protocol.user:
            raise PermissionDenied
        user = User.objects.get(username=request.data['user'])
        role = request.data['role']
        if role == "viewer":
            protocol.viewers.remove(user)
        elif role == "editor":
            protocol.editors.remove(user)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_reagents(self, request, pk=None):
        protocol = self.get_object()
        data = ProtocolReagentSerializer(protocol.reagents.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_tag(self, request, pk=None):
        protocol = self.get_object()
        tag_name = request.data['tag']
        tags = Tag.objects.filter(tag=tag_name)
        if tags.exists():
            tag = tags.first()
        else:
            tag = Tag.objects.create(tag=tag_name)

        protocol_tags = ProtocolTag.objects.filter(tag=tag)
        if not protocol_tags.exists():
            protocol_tag = ProtocolTag.objects.create(protocol=protocol, tag=tag)
            data = ProtocolTagSerializer(protocol_tag, many=False).data
            return Response(data, status=status.HTTP_200_OK)
        else:
            return Response(status=status.HTTP_409_CONFLICT)

    @action(detail=True, methods=['post'])
    def remove_tag(self, request, pk=None):
        protocol = self.get_object()
        tag = ProtocolTag.objects.get(id=request.data['tag'])
        protocol.tags.remove(tag)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_metadata_columns(self, request, pk=None):
        protocol = self.get_object()
        metadata_columns = request.data['metadata_columns']
        for metadata_column in metadata_columns:
            metadata_column = MetadataColumn.objects.create(
                protocol=protocol,
                name=metadata_column['name'],
                value=metadata_column['value'],
                type=metadata_column['type']
            )

        return Response(ProtocolModelSerializer(protocol, many=False).data, status=status.HTTP_200_OK)

class StepViewSet(ModelViewSet, FilterMixin):
    permission_classes = [OwnerOrReadOnly]
    queryset = ProtocolStep.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['step_description', 'step_section']
    ordering_fields = ['step_description', 'step_section']
    filterset_fields = ['step_description', 'step_section']
    serializer_class = ProtocolStepSerializer

    def get_queryset(self):
        user = self.request.user
        return ProtocolStep.objects.filter(Q(protocol__user=user)|Q(protocol__enabled=True))

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        if obj.protocol.user == user or obj.protocol.enabled:
            return obj
        else:
            raise PermissionDenied


    def create(self, request, *args, **kwargs):
        protocol = ProtocolModel.objects.get(id=request.data['protocol'])
        # get all steps in the section
        steps = ProtocolStep.objects.filter(step_section=request.data['step_section'], protocol=protocol)
        #check if there is a next step using the current last step in the section
        step = ProtocolStep()
        step.step_description = request.data['step_description']
        section = ProtocolSection.objects.get(id=request.data['step_section'])
        step.step_duration = request.data['step_duration']
        if "step_id" in request.data:
            step.step_id = request.data['step_id']
        step.protocol = protocol
        step.save()
        last_step_in_section = section.get_last_in_section()
        if last_step_in_section:
            section.insert_step(step, last_step_in_section)
        else:
            last_step_in_protocol = protocol.get_last_in_protocol()
            if last_step_in_protocol:
                step.previous_step = last_step_in_protocol
            step.step_section = section
            step.save()

        data = self.get_serializer(step).data
        return Response(data, status=status.HTTP_201_CREATED)


    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.step_description = request.data['step_description']
        instance.step_duration = request.data['step_duration']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        print(instance)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['patch', 'options'])
    def move_up(self, request, pk=None):
        step = self.get_object()
        step.move_up()
        data = self.get_serializer(step).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch', 'options'])
    def move_down(self, request, pk=None):
        step = self.get_object()
        step.move_down()
        data = self.get_serializer(step).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def get_timekeeper(self, request, pk=None):
        user = request.user
        step = self.get_object()
        started = False
        if "session" in self.request.data:
            session = self.request.data['session']
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if "started" in self.request.data:
            started = self.request.data['started']
        start_time = None
        if "start_time" in self.request.data:
            start_time = self.request.data['start_time']

        if session:
            try:
                timekeeper = TimeKeeper.objects.get(user=user, session__unique_id=session, step=step)
                if start_time:
                    timekeeper.start_time = start_time
                if started:
                    timekeeper.started = started
                timekeeper.save()
                data = TimeKeeperSerializer(timekeeper, many=False).data
                return Response(data, status=status.HTTP_200_OK)
            except TimeKeeper.DoesNotExist:
                timekeeper = TimeKeeper()
                timekeeper.user = user
                timekeeper.session = Session.objects.get(unique_id=session)
                timekeeper.step = step
                timekeeper.started = started
                if start_time:
                    timekeeper.start_time = start_time
                timekeeper.save()
                data = TimeKeeperSerializer(timekeeper, many=False).data
                return Response(data, status=status.HTTP_201_CREATED)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def add_protocol_reagent(self, request, pk=None):
        step = self.get_object()
        try:
            reagent = Reagent.objects.get(name=request.data['name'], unit=request.data['unit'])
        except Reagent.DoesNotExist:
            reagent = Reagent.objects.create(name=request.data['name'], unit=request.data['unit'])

        step_reagents = step.reagents.filter(reagent=reagent)
        if not step_reagents.exists():
            step_reagent = StepReagent.objects.create(step=step, reagent=reagent, quantity=request.data['quantity'], scalable=request.data['scalable'], scalable_factor=request.data['scalable_factor'])
            protocol_reagents = step.protocol.reagents.filter(reagent=reagent)
            if not protocol_reagents.exists():
                ProtocolReagent.objects.create(protocol=step.protocol, reagent=reagent, quantity=request.data['quantity'])
            data = StepReagentSerializer(step_reagent, many=False).data
            return Response(data, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_409_CONFLICT)

    @action(detail=True, methods=['post'])
    def remove_protocol_reagent(self, request, pk=None):
        step = self.get_object()
        reagent = StepReagent.objects.get(id=request.data['reagent'])
        if step == reagent.step:
            protocol_step = step.protocol.reagents.filter(reagent=reagent.reagent)
            if protocol_step.exists():
                protocol_reagent = protocol_step.first()
                if protocol_reagent.quantity == reagent.quantity:
                    protocol_reagent.delete()
                else:
                    protocol_reagent.quantity = protocol_reagent.quantity - reagent.quantity
                    protocol_reagent.save()
            reagent.delete()
            data = self.get_serializer(step).data
            return Response(data, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)
    @action(detail=True, methods=['post'])
    def update_protocol_reagent(self, request, pk=None):
        step = self.get_object()
        reagent = StepReagent.objects.get(id=request.data['reagent'])
        protocol_step = step.protocol.reagents.filter(reagent=reagent.reagent)
        if protocol_step.exists():
            protocol_reagent = protocol_step.first()
            amount_remove = reagent.quantity
            if reagent.scalable:
                amount_remove = reagent.quantity * reagent.scalable_factor
            protocol_quantity_before = protocol_reagent.quantity - amount_remove
            reagent.quantity = request.data['quantity']
            reagent.scalable = request.data['scalable']
            reagent.scalable_factor = request.data['scalable_factor']
            reagent.save()
            amount_add = reagent.quantity
            if reagent.scalable:
                amount_add = reagent.quantity * reagent.scalable_factor

            protocol_reagent.quantity = protocol_quantity_before + amount_add
            protocol_reagent.save()
            data = StepReagentSerializer(reagent, many=False).data
            return Response(data, status=status.HTTP_200_OK)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def add_tag(self, request, pk=None):
        step = self.get_object()
        tag_name = request.data['tag']
        tags = Tag.objects.filter(tag=tag_name)
        if tags.exists():
            tag = tags.first()
        else:
            tag = Tag.objects.create(tag=tag_name)
        step_tags = StepTag.objects.filter(tag=tag)
        if not step_tags.exists():
            step_tag = StepTag.objects.create(step=step, tag=tag)
            data = StepTagSerializer(step_tag, many=False).data
            return Response(data, status=status.HTTP_200_OK)
        else:
            return Response(status=status.HTTP_409_CONFLICT)


    @action(detail=True, methods=['post'])
    def remove_tag(self, request, pk=None):
        step = self.get_object()
        tag = StepTag.objects.get(id=request.data['tag'])
        step.tags.remove(tag)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_associated_reagent_actions(self, request, pk=None):
        step = self.get_object()
        reagents = step.reagents.all()
        session = self.request.query_params.get('session', None)
        if not session:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        if session:
            session = Session.objects.get(unique_id=session)
        reagent_actions = ReagentAction.objects.filter(step_reagent__in=reagents, session=session)
        data = ReagentActionSerializer(reagent_actions, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def export_associated_metadata(self, request, pk=None):
        step: ProtocolStep = self.get_object()
        session_unique_id = self.request.query_params.get('session', None)
        if not session_unique_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        data = step.get_metadata_columns(session_unique_id)
        return Response(data=data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def convert_metadata_to_sdrf_txt(self, request, pk=None):
        step: ProtocolStep = self.get_object()
        data = request.data
        result = step.convert_to_sdrf_file(data)
        return Response(data=result, status=status.HTTP_200_OK)

class AnnotationViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Annotation.objects.all()
    parser_classes = [MultiPartParser, JSONParser]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['annotation']
    ordering_fields = ['created_at']
    serializer_class = AnnotationSerializer
    filterset_fields = ['step', 'session__unique_id']

    def create(self, request, *args, **kwargs):
        step = None
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        annotation = Annotation()
        if 'stored_reagent' in request.data:
            stored_reagent = StoredReagent.objects.get(id=request.data['stored_reagent'])
            annotation.stored_reagent = stored_reagent
        if 'step' in request.data:
            if request.data['step']:
                step = ProtocolStep.objects.get(id=request.data['step'])
                annotation.step = step
        if 'session' in request.data:
            if request.data['session'] != "":
                session = Session.objects.get(unique_id=request.data['session'])
                annotation.session = session
        maintenance = request.data.get('maintenance', False)
        annotation.annotation = request.data['annotation']
        annotation.annotation_type = request.data['annotation_type']
        annotation.user = request.user
        time_started = None
        time_ended = None
        instrument = None
        adding_metadata_columns = []
        if annotation.annotation_type == "instrument":
            instrument = Instrument.objects.filter(id=request.data['instrument'])
            if not instrument.exists():
                return Response(status=status.HTTP_400_BAD_REQUEST)
            instrument = instrument.first()
            meta_cols = instrument.metadata_columns.all()
            if meta_cols.exists():
                for meta_col in meta_cols:
                    adding_metadata_columns.append(
                        MetadataColumn(value=meta_col.value, type=meta_col.type, name=meta_col.name, annotation=annotation)
                    )
            if not request.user.is_staff:
                instrument_permission = InstrumentPermission.objects.filter(instrument=instrument, user=request.user)
                if not instrument_permission.exists():
                    return Response(status=status.HTTP_401_UNAUTHORIZED)
                instrument_permission = instrument_permission.first()
                if not instrument_permission.can_manage and not instrument_permission.can_book:
                    return Response(status=status.HTTP_401_UNAUTHORIZED)
                if maintenance:
                    if not instrument_permission.can_manage:
                        return Response(status=status.HTTP_401_UNAUTHORIZED)
            if "time_started" in request.data and "time_ended" in request.data:
                time_started = request.data['time_started']
                time_ended = request.data['time_ended']

                # check if the instrument is available at this time by checking if submitted time_started is between the object time_started and time_ended or time_ended is between the object time_started and time_ended
                if time_started and time_ended:
                    time_started = parse_datetime(request.data['time_started'])
                    time_ended = parse_datetime(request.data['time_ended'])
                    if time_started and time_ended:
                        if timezone.is_naive(time_started):
                            time_started = timezone.make_aware(time_started, timezone.get_current_timezone())
                        if timezone.is_naive(time_ended):
                            time_ended = timezone.make_aware(time_ended, timezone.get_current_timezone())
                    time_started_overlap = InstrumentUsage.objects.filter(instrument=instrument,
                                                                          time_started__range=[time_started,
                                                                                               time_ended])
                    time_ended_overlap = InstrumentUsage.objects.filter(instrument=instrument, time_ended__range=[time_started, time_ended])
                    has_maintenance_started = time_started_overlap.filter(maintenance=True).exists()
                    has_maintenance_ended = time_ended_overlap.filter(maintenance=True).exists()
                    if has_maintenance_started or has_maintenance_ended:
                        return Response(status=status.HTTP_409_CONFLICT)
                    else:
                        if (time_started_overlap.exists() or time_ended_overlap.exists()) and not settings.ALLOW_OVERLAP_BOOKINGS:
                            return Response(status=status.HTTP_409_CONFLICT)



        annotation.save()
        if adding_metadata_columns:
            # sort the metadata columns first by type, characteristics first, then none, then comment type
            def sort_key(meta_col):
                if meta_col.type == "Characteristics":
                    return 0
                elif meta_col.type == "Comment":
                    return 2
                elif meta_col.type == "Factor value":
                    return 3
                else:
                    return 1
            adding_metadata_columns.sort(key=sort_key)
            for n, meta_col in enumerate(adding_metadata_columns):
                meta_col.column_position = n
                meta_col.save()
        annotation.save()
        if 'file' in request.data:
            annotation.annotation_name = request.data['file'].name
            uploaded_file_extension = request.data['file'].name.split('.')[-1]
            annotation.file.save(uuid.uuid4().hex+"."+uploaded_file_extension, djangoFile(request.data['file']))
        annotation.save()
        if settings.USE_WHISPER:
            if annotation.annotation_type == "video":
                transcribe_audio_from_video.delay(annotation.file.path, settings.WHISPERCPP_DEFAULT_MODEL, annotation.id, "auto", True, custom_id)
            elif annotation.annotation_type == "audio":
                transcribe_audio.delay(annotation.file.path, settings.WHISPERCPP_DEFAULT_MODEL, annotation.id, "auto", True, custom_id)
        if annotation.annotation_type == "instrument":
            usage = InstrumentUsage.objects.create(
                instrument=instrument,
                annotation=annotation,
                time_started=time_started,
                time_ended=time_ended,
                user=request.user,
                description=annotation.annotation,
                maintenance=maintenance
            )
            duration = usage.time_ended - usage.time_started

            day_ahead = usage.time_started - timezone.now()
            if (
                    duration.days + 1
                    <= instrument.max_days_within_usage_pre_approval
                    # or instrument.max_days_within_usage_pre_approval == 0
            ) and (
                    day_ahead.days + 1 <=
                    instrument.max_days_ahead_pre_approval
                    # or instrument.max_days_ahead_pre_approval == 0
            ):
                usage.approved = True
            else:
                usage.approved = False
        if 'instrument_job' in request.data and 'instrument_user_type' in request.data:
            instrument_job = InstrumentJob.objects.get(id=request.data['instrument_job'])
            if request.data['instrument_user_type'] == "staff_annotation":
                instrument_job.staff_annotations.add(annotation)
                if annotation.annotation_type == "instrument":
                    metadata_columns = annotation.metadata_columns.all()
                    for meta_col in metadata_columns:
                        instrument_job_staff_metadata = instrument_job.staff_metadata.filter(name=meta_col.name, type=meta_col.type)
                        if instrument_job_staff_metadata.exists():
                            instrument_job_instrument_metadata = instrument_job_staff_metadata.first()
                            if not instrument_job_instrument_metadata.value:
                                instrument_job_instrument_metadata.value = meta_col.value
                                instrument_job_instrument_metadata.save()
                        else:
                            metadata_col = MetadataColumn.objects.create(
                                name=meta_col.name,
                                value=meta_col.value,
                                type=meta_col.type,
                            )
                            instrument_job.staff_metadata.add(metadata_col)

            elif request.data['instrument_user_type'] == "user_annotation":
                instrument_job.user_annotations.add(annotation)

        data = self.get_serializer(annotation).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not request.user.is_staff:
            if not instance.check_for_right(request.user, "edit"):
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        if 'annotation' in request.data:
            instance.annotation = request.data['annotation']
        if 'file' in request.data:
            instance.file = request.data['file']
        if 'translation' in request.data:
            instance.translation = request.data['translation']
        if 'transcription' in request.data:
            instance.transcription = request.data['transcription']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance: Annotation = self.get_object()
        if not request.user.is_staff:
            if not instance.check_for_right(request.user, "delete"):
                return Response(status=status.HTTP_401_UNAUTHORIZED)

        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        # Check if session is enabled, and if the user is the owner of the session
        queryset = self.queryset
        user = self.request.user

        if not user.is_staff:

            protected_annotations = Annotation.objects.filter(
                Q(folder__name='Certificates') | Q(folder__name='Maintenance'),
                folder__parent_folders__instrument__isnull=False
            )
            permissions = InstrumentPermission.objects.filter(can_manage=False, user=user)

            if permissions.exists():
                protected_annotations = protected_annotations.filter(
                    folder__parent_folders__instrument__in=permissions.values_list('instrument', flat=True)
                )

            queryset = queryset.exclude(id__in=protected_annotations.values_list('id', flat=True))


        if self.request.method in ["GET", "OPTIONS"]:
            if user.is_authenticated:
                return queryset.filter(Q(session__user=user)|Q(session__enabled=True)|Q(session__viewers=user)|Q(session__editors=user)|Q(user=user))
            else:
                return queryset.filter(session__enabled=True)
        else:
            if user.is_authenticated:
                return queryset.filter(Q(session__user=user)|Q(session__editors=user)|Q(user=user))
            else:
                return []

    @action(detail=True, methods=['get'])
    def download_file(self, request, pk=None):
        annotation = self.get_object()
        user = self.request.user
        if not user.is_staff:
            protected_annotations = Annotation.objects.filter(
                Q(folder__name='Certificates') | Q(folder__name='Maintenance'),
                folder__parent_folders__instrument__isnull=False
            )
            permissions = InstrumentPermission.objects.filter(can_manage=False, user=user)

            if permissions.exists():
                protected_annotations = protected_annotations.filter(
                    folder__parent_folders__instrument__in=permissions.values_list('instrument', flat=True)
                )

            if annotation in protected_annotations:
                return Response(status=status.HTTP_403_FORBIDDEN)

        file_name = annotation.file.name
        response = HttpResponse(status=200)
        response["Content-Disposition"] = f'attachment; filename="{file_name.split("/")[-1]}"'
        response["X-Accel-Redirect"] = f"/media/{file_name}"
        return response

    def get_object(self):
        obj: Annotation = super().get_object()
        user = self.request.user
        if obj.user == user:
            return obj
        if obj.session:
            if obj.session.user == user:
                return obj
            if obj.session.viewers.filter(id=user.id).exists():
                return obj
            if obj.session.editors.filter(id=user.id).exists():
                return obj
            if obj.session.enabled:
                return obj
        if obj.folder:
            if obj.folder.instrument:
                i_permission = InstrumentPermission.objects.filter(instrument=obj.folder.instrument, user=user)
                if i_permission.exists():
                    i_permission = i_permission.first()
                    if i_permission.can_book or i_permission.can_manage or i_permission.can_view:
                        return obj
        instrument_jobs = obj.instrument_jobs.all()
        if instrument_jobs.exists():
            return obj
        raise PermissionDenied

    @action(detail=True, methods=['post'])
    def get_signed_url(self, request, pk=None):
        signer = TimestampSigner()
        annotation = Annotation.objects.get(id=pk)
        user = self.request.user
        file = {'file': annotation.file.name, 'id': annotation.id}
        signed_token = signer.sign_object(file)
        if annotation.check_for_right(user, "view"):
            return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        # if annotation.session:
        #     if annotation.session.enabled:
        #         if not annotation.scratched:
        #             return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        #
        # if user.is_authenticated:
        #     if annotation.session:
        #         if user in annotation.session.viewers.all() or user in annotation.session.editors.all() or user == annotation.session.user or user == annotation.user:
        #             if annotation.scratched:
        #                 if user not in annotation.session.editors.all() and user != annotation.user and user != annotation.session.user:
        #                     return Response(status=status.HTTP_401_UNAUTHORIZED)
        #             else:
        #                 return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        #             return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        #     if annotation.folder:
        #         if annotation.folder.instrument:
        #             i_permission = InstrumentPermission.objects.filter(instrument=annotation.folder.instrument, user=user)
        #             if i_permission.exists():
        #                 i_permission = i_permission.first()
        #                 if i_permission.can_book or i_permission.can_manage or i_permission.can_view:
        #                     return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        #     else:
        #         instrument_jobs = annotation.instrument_jobs.all()
        #         for instrument_job in instrument_jobs:
        #             if user == instrument_job.user:
        #                 return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        #             else:
        #                 lab_group = instrument_job.service_lab_group
        #                 staff =  instrument_job.staff.all()
        #                 if staff.count() > 0:
        #                     if user in staff:
        #                         return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        #                 else:
        #                     if user in lab_group.users.all():
        #                         return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_401_UNAUTHORIZED)


    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def download_signed(self, request, *args, **kwargs):
        token = request.query_params.get('token', None)
        if not token:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        signer = TimestampSigner()
        try:
            data = signer.unsign_object(token, max_age=60*30)
            annotation = Annotation.objects.get(id=data['id'])
            if annotation.file:
                response = HttpResponse(status=200)
                response["Content-Disposition"] = f'attachment; filename="{annotation.file.name.split("/")[-1]}"'
                response["X-Accel-Redirect"] = f"/media/{data['file']}"
                return response
            else:
                return Response(status=status.HTTP_404_NOT_FOUND)
        except:
            return Response(status=status.HTTP_400_BAD_REQUEST)


    @action(detail=True, methods=['post'])
    def retranscribe(self, request, pk=None):
        annotation = self.get_object()
        language = "auto"
        if not annotation.check_for_right(request.user, "edit"):
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        if "language" in request.data:
            language = request.data['language']
        if annotation.annotation_type == "video":
            transcribe_audio_from_video.delay(annotation.file.path, settings.WHISPERCPP_DEFAULT_MODEL, annotation.id, language, True)
        elif annotation.annotation_type == "audio":
            transcribe_audio.delay(annotation.file.path, settings.WHISPERCPP_DEFAULT_MODEL, annotation.id, language, True)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def ocr(self, request, pk=None):
        if not settings.USE_OCR:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        annotation: Annotation = self.get_object()
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        if not annotation.check_for_right(request.user, "edit"):
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        if annotation.annotation_type == "sketch":
            with open(annotation.file.path, "rb") as f:
                json_data = json.load(f)
                ocr_b64_image.delay(json_data["png"], annotation.id, annotation.session.unique_id, custom_id)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def scratch(self, request, pk=None):
        annotation: Annotation = self.get_object()
        if annotation.scratched:
            annotation.scratched = False
        else:
            annotation.scratched = True
        annotation.save()
        data = self.get_serializer(annotation, many=False).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def rename(self, request, pk=None):
        annotation: Annotation = self.get_object()
        annotation.annotation_name = request.data['annotation_name']
        annotation.save()
        data = self.get_serializer(annotation, many=False).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def move_to_folder(self, request, pk=None):
        annotation: Annotation = self.get_object()
        folder = request.data['folder']
        folder = AnnotationFolder.objects.get(id=folder)
        annotation.folder = folder
        annotation.save()
        data = self.get_serializer(annotation, many=False).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def get_annotation_in_folder(self, request):
        folder = request.query_params.get('folder', None)
        search_term = request.query_params.get('search_term', None)
        if folder:
            anntation_folder = AnnotationFolder.objects.get(id=folder)
            annotations = Annotation.objects.filter(folder=anntation_folder)
            if search_term:
                annotations = annotations.filter(Q(annotation_name__icontains=search_term)|Q(annotation__icontains=search_term))
            paginator = LimitOffsetPagination()
            pagination = paginator.paginate_queryset(annotations, request)
            if pagination is not None:
                serializer = self.get_serializer(pagination, many=True)
                return paginator.get_paginated_response(serializer.data)
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def bind_uploaded_file(self, request):
        upload_id = request.data['upload_id']
        file_name = request.data['file_name']

        annotation_name = request.data['annotation_name']
        upload = ChunkedUpload.objects.get(id=upload_id)
        annotation = Annotation()
        annotation.user = request.user
        if "step" in request.data:
            step = ProtocolStep.objects.filter(id=request.data['step'])
            if step.exists():
                step = step.first()
                annotation.step = step
        if "folder" in request.data:
            folder = AnnotationFolder.objects.filter(id=request.data['folder'])
            if folder.exists():
                folder = folder.first()
                annotation.folder = folder
        if "session" in request.data:
            session = Session.objects.filter(unique_id=request.data['session'])
            if session.exists():
                session = session.first()
                annotation.session = session
        if "stored_reagent" in request.data:
            stored_reagent = StoredReagent.objects.get(id=request.data['stored_reagent'])
            annotation.stored_reagent = stored_reagent

        annotation.annotation_name = annotation_name
        annotation.annotation_type = "file"
        with open(upload.file.path, "rb") as f:
            annotation.file.save(file_name, f)
        annotation.save()
        if "instrument_user_type" in request.data and "instrument_job" in request.data:
            instrument_job = InstrumentJob.objects.get(id=request.data['instrument_job'])
            if request.data['instrument_user_type'] == "staff_annotation":
                instrument_job.staff_annotations.add(annotation)
            elif request.data['instrument_user_type'] == "user_annotation":
                instrument_job.user_annotations.add(annotation)
        upload.delete()
        data = self.get_serializer(annotation).data
        return Response(data, status=status.HTTP_201_CREATED)




class SessionViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Session.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    lookup_field = 'unique_id'
    search_fields = ['unique_id', 'name']
    ordering_fields = ['unique_id', 'started_at', 'ended_at']
    filterset_fields = ['unique_id']
    serializer_class = SessionSerializer

    def create(self, request, *args, **kwargs):
        user = request.user
        session = Session()
        session.user = user
        session.unique_id = uuid.uuid4()
        session.save()
        if "protocol_ids" in request.data:
            for protocol_id in request.data['protocol_ids']:
                protocol = ProtocolModel.objects.get(id=protocol_id)
                session.protocols.add(protocol)
        data = self.get_serializer(session, many=False).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user != request.user:
            raise PermissionDenied
        for i in request.data:
            if i in ['enabled', 'created_at', 'updated_at', 'protocols', 'name', 'started_at', 'ended_at']:
                setattr(instance, i, request.data[i])
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        # Check if session is enabled, and if the user is the owner of the session
        user = self.request.user
        if user.is_authenticated:
            return Session.objects.filter(Q(user=user)|Q(enabled=True)|Q(viewers=user)|Q(editors=user))
        else:
            return Session.objects.filter(enabled=True)

    def get_object(self):
        print(self.request)
        obj = super().get_object()
        print(obj.__dict__)
        user = self.request.user
        if obj.user == user or (obj.enabled and self.request.method in ["GET", "OPTIONS"]):
            return obj
        elif obj.viewers.filter(id=user.id).exists():
            if self.request.method in ["GET", "OPTIONS"]:
                return obj
        elif obj.editors.filter(id=user.id).exists():
            return obj
        else:
            raise PermissionDenied

    @action(detail=False, methods=['get'], pagination_class=LimitOffsetPagination)
    def get_user_sessions(self, request):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        user = request.user
        sessions = Session.objects.filter(user=user)
        search = request.query_params.get('search', None)
        if search:
            sessions = sessions.filter(Q(name__icontains=search)|Q(unique_id__icontains=search))

        limitdata = request.query_params.get('limit', None)
        paginator = LimitOffsetPagination()
        paginator.default_limit = int(limitdata) if limitdata else 5

        pagination = paginator.paginate_queryset(sessions, request)
        if pagination is not None:
            serializer = self.get_serializer(pagination, many=True)
            return paginator.get_paginated_response(serializer.data)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], lookup_field = 'unique_id')
    def get_associated_protocol_titles(self, request, unique_id=None):
        session = self.get_object()
        protocols = session.protocols.all()
        #data = [{"id": p.id, "protocol_title": p.protocol_title} for p in protocols]
        data = ProtocolModelSerializer(protocols, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_protocol(self, request, unique_id=None):
        session = self.get_object()
        protocol = ProtocolModel.objects.get(id=request.data['protocol'])
        user = self.request.user
        if protocol not in session.protocols.all():
            if user.is_staff:
                session.protocols.add(protocol)

            elif protocol.user == user:
                session.protocols.add(protocol)

            elif user in protocol.viewers.all() or user in protocol.editors.all() or protocol.enabled:
                session.protocols.add(protocol)
            else:
                raise PermissionDenied
            session.protocols.add(protocol)
        data = self.get_serializer(session).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_protocol(self, request, unique_id=None):
        session = self.get_object()
        protocol = ProtocolModel.objects.get(id=request.data['protocol'])
        session.protocols.remove(protocol)
        data = self.get_serializer(session).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def calendar_get_sessions(self, request):
        user = self.request.user
        start_date = request.query_params.get('start', None)
        end_date = request.query_params.get('end', None)
        if not start_date or not end_date:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        sessions = Session.objects.filter(user=user, started_at__gte=start_date, started_at__lte=end_date)
        data = SessionSerializer(sessions, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_user_role(self, request, unique_id=None):
        session = self.get_object()
        if self.request.user != session.user:
            raise PermissionDenied
        user = User.objects.get(username=request.data['user'])
        if user == session.user:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        role = request.data['role']
        if role == "viewer":
            session.viewers.add(user)
        elif role == "editor":
            session.editors.add(user)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_editors(self, request, unique_id=None):
        session = self.get_object()
        data = UserSerializer(session.editors.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_viewers(self, request, unique_id=None):
        session = self.get_object()
        data = UserSerializer(session.viewers.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_user_role(self, request, unique_id=None):
        session = self.get_object()
        if self.request.user != session.user:
            raise PermissionDenied
        user = User.objects.get(username=request.data['user'])
        role = request.data['role']
        if role == "viewer":
            session.viewers.remove(user)
        elif role == "editor":
            session.editors.remove(user)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_base_folders(self, request, unique_id=None):
        session = self.get_object()
        folders = AnnotationFolder.objects.filter(session=session, parent_folder=None)
        data = AnnotationFolderSerializer(folders, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_folder(self, request, unique_id=None):
        session = self.get_object()
        folders_with_same_name = AnnotationFolder.objects.filter(session=session, folder_name=request.data['folder_name'])
        folder = AnnotationFolder()
        folder.session = session
        folder.folder_name = request.data['folder_name']
        if "parent_folder" in request.data:
            folder_with_same_name_and_parent = folders_with_same_name.objects.filter(parent_folder=request.data['parent_folder'])
            if folder_with_same_name_and_parent.exists():
                return Response(status=status.HTTP_409_CONFLICT)
            parent_folder = AnnotationFolder.objects.get(id=request.data['parent_folder'])
            folder.parent_folder = parent_folder
        else:
            folders_with_same_name_at_root = folders_with_same_name.filter(parent_folder=None)
            if folders_with_same_name_at_root.exists():
                return Response(status=status.HTTP_409_CONFLICT)
        folder.save()
        data = AnnotationFolderSerializer(folder, many=False).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def remove_folder(self, request, unique_id=None):
        session = self.get_object()
        folder = AnnotationFolder.objects.get(id=request.data['folder'])
        if folder.session == session:
            if "remove_contents" in request.data:
                if request.data['remove_contents']:
                    annotations = Annotation.objects.filter(folder=folder)
                    annotations.delete()
            folder.delete()
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)


class VariationViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = StepVariation.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['variation_description']
    ordering_fields = ['variation_description']
    filterset_fields = ['variation_description']
    serializer_class = StepVariationSerializer

    def create(self, request, *args, **kwargs):
        step = ProtocolStep.objects.get(id=request.data['step'])
        variation = StepVariation()
        variation.variation_description = request.data['variation_description']
        variation.variation_duration = request.data['variation_duration']
        variation.step = step
        variation.save()
        data = self.get_serializer(variation).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.variation_description = request.data['variation_description']
        instance.variation_duration = request.data['variation_duration']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        # Check if session is enabled, and if the user is the owner of the session
        user = self.request.user
        return StepVariation.objects.filter(step__session__user=user)

    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        if obj.step.session.user == user:
            return obj
        else:
            if obj.step.session.enabled:
                return obj
            raise PermissionDenied


class TimeKeeperViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = TimeKeeper.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    serializer_class = TimeKeeperSerializer

    def get_queryset(self):
        user = self.request.user
        query = Q(user=user)
        started = self.request.query_params.get('started', 'false').lower() == 'true'
        if started:
            query &= Q(started=started)
        return TimeKeeper.objects.filter(user=user)

    def get_object(self):
        obj = super().get_object()
        user = self.request.user
        if obj.user == user:
            return obj
        else:
            raise PermissionDenied

    def create(self, request, *args, **kwargs):
        user = request.user
        data = {}

        if 'session' in request.data and request.data['session']:
            try:
                session = Session.objects.get(unique_id=request.data['session'])
                data['session'] = session
            except Session.DoesNotExist:
                return Response(
                    {"error": "Session not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        if 'step' in request.data and request.data['step']:
            try:
                step = ProtocolStep.objects.get(id=request.data['step'])
                data['step'] = step
            except ProtocolStep.DoesNotExist:
                return Response(
                    {"error": "Step not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        data['user'] = user

        if 'started' in request.data:
            data['started'] = request.data['started']

        if 'start_time' in request.data:
            data['start_time'] = request.data['start_time']

        if 'current_duration' in request.data:
            data['current_duration'] = request.data['current_duration']

        timekeeper = TimeKeeper.objects.create(**data)

        serializer = self.get_serializer(timekeeper)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        if 'started' in request.data:
            instance.started = request.data['started']

        if 'start_time' in request.data:
            instance.start_time = request.data['start_time']

        if 'current_duration' in request.data:
            instance.current_duration = request.data['current_duration']

        instance.save()

        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProtocolSectionViewSet(ModelViewSet):
    permission_classes = [OwnerOrReadOnly]
    queryset = ProtocolSection.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = [MultiPartParser, JSONParser]
    serializer_class = ProtocolSectionSerializer
    pagination_class = LimitOffsetPagination

    def create(self, request, *args, **kwargs):
        protocol = ProtocolModel.objects.get(id=request.data['protocol'])
        section = ProtocolSection()
        section.protocol = protocol
        section.section_description = request.data['section_description']
        section.section_duration = request.data['section_duration']
        section.save()
        data = self.get_serializer(section).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.section_description = request.data['section_description']
        instance.section_duration = request.data['section_duration']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        user = self.request.user
        return ProtocolSection.objects.filter(Q(protocol__user=user)|Q(protocol__enabled=True))

    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        if obj.protocol.user == user or obj.protocol.enabled:
            return obj
        else:
            raise PermissionDenied

    @action(detail=True, methods=['get'])
    def get_steps(self, request, pk=None):
        section = self.get_object()
        steps = section.get_step_in_order()
        data = ProtocolStepSerializer(steps, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'])
    def update_steps(self, request, pk=None):
        section = self.get_object()
        steps = request.data['steps']
        section.update_steps(steps)
        steps = section.get_step_in_order()
        data = ProtocolStepSerializer(steps, many=True).data
        return Response(data, status=status.HTTP_200_OK)


class UserViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticated]
    queryset = User.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    serializer_class = UserSerializer
    parser_classes = [MultiPartParser, JSONParser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['username']

    def get_queryset(self):
        stored_reagent = self.request.query_params.get('stored_reagent', None)
        if stored_reagent:
            stored_reagent = StoredReagent.objects.get(id=stored_reagent)
            return stored_reagent.access_users.all()
        lab_group = self.request.query_params.get('lab_group', None)
        if lab_group:
            lab_group = LabGroup.objects.get(id=lab_group)
            return lab_group.users.all()
        return self.queryset

    def get_object(self):
        obj = super().get_object()
        return obj

    def create(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=False, methods=['put'])
    def update_profile(self, request, *args, **kwargs):
        instance = request.user
        if "first_name" in request.data:
            instance.first_name = request.data['first_name']
        if "last_name" in request.data:
            instance.last_name = request.data['last_name']
        if "email" in request.data:
            if User.objects.filter(email=request.data['email']).exists():
                return Response(status=status.HTTP_409_CONFLICT)
            instance.email = request.data['email']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        user = request.user
        if "password" in request.data:
            if user.check_password(request.data['old_password']):
                user.set_password(request.data['password'])
                user.save()
                return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def check_protocol_permission(self, request):
        user = self.request.user
        protocol = ProtocolModel.objects.get(id=request.data['protocol'])
        permission = {
            "edit": False,
            "view": False,
            "delete": False
        }
        if protocol.user == user:
            permission['edit'] = True
            permission['view'] = True
            permission['delete'] = True
        elif user in protocol.editors.all():
            permission['edit'] = True
            permission['view'] = True
        elif user in protocol.viewers.all():
            permission['view'] = True
        if protocol.enabled:
            permission['view'] = True
        return Response(permission, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def check_session_permission(self, request):
        user = self.request.user
        session = Session.objects.get(unique_id=request.data['session'])
        permission = {
            "edit": False,
            "view": False,
            "delete": False
        }
        if session.user == user:
            permission['edit'] = True
            permission['view'] = True
            permission['delete'] = True

        elif user in session.editors.all():
            permission['edit'] = True
            permission['view'] = True

        elif user in session.viewers.all():
            permission['view'] = True
        if session.enabled:
            permission['view'] = True

        return Response(permission, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def check_annotation_permission(self, request):
        annotation_ids = request.data['annotations']
        annotations = Annotation.objects.filter(id__in=annotation_ids)
        permission_list = []
        for a in annotations:
            permission = {
                "edit": False,
                "view": False,
                "delete": False
            }
            if a.user == request.user:
                permission['edit'] = True
                permission['view'] = True
                permission['delete'] = True

            if a.session:
                if a.session.user == request.user or request.user in a.session.editors.all():
                    permission['edit'] = True
                    permission['view'] = True
                    permission['delete'] = True
                elif request.user in a.session.viewers.all() or a.session.enabled:
                    permission['view'] = True

            elif a.folder:
                if a.folder.instrument:
                    i_permission = InstrumentPermission.objects.filter(instrument=a.folder.instrument, user=request.user)
                    if i_permission.exists():
                        p = i_permission.first()
                        if p.can_manage:
                            permission['edit'] = True
                            permission['view'] = True
                            permission['delete'] = True
                        elif p.can_book:
                            permission['view'] = True
                        elif p.can_view:
                            permission['view'] = True

            permission_list.append({"permission": permission, "annotation": a.id})
        return Response(permission_list, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def check_stored_reagent_permission(self, request):
        stored_reagent_ids = request.data["stored_reagents"]
        stored_reagents = StoredReagent.objects.filter(id__in=stored_reagent_ids)
        permission_list = []
        if request.user.is_authenticated:
            if request.user.is_staff:
                permission_list = [{"permission": {"edit": True, "view": True, "delete": True, "use": True}, "stored_reagent": sr.id} for sr in stored_reagents]
                return Response(permission_list, status=status.HTTP_200_OK)

        for sr in stored_reagents:
            permission = {
                "edit": False,
                "view": True,
                "delete": False,
                "use": False
            }
            if sr.user == request.user:
                permission['delete'] = True
                permission['edit'] = True
                permission['use'] = True
            else:
                if sr.shareable:
                    if request.user in sr.access_users.all():
                        permission['use'] = True
                    else:
                        lab_groups = request.user.lab_groups.all()
                        if sr.access_lab_groups.filter(
                            id__in=lab_groups.values_list('id', flat=True)).exists():
                            permission['use'] = True
            permission_list.append({"permission": permission, "stored_reagent": sr.id})
        return Response(permission_list, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def summarize_prompt(self, request):
        prompt = request.data['prompt']
        prompt = f"System: You are a helpful laboratory assistant.\nUser: {prompt}"
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        llama_summary.delay(prompt, request.user.id, request.data['target'], custom_id)
        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def summarize_steps(self, request):
        steps = request.data['steps']
        steps = ProtocolStep.objects.filter(id__in=steps)
        prompt = "<|im_start|>system\n You are a helpful laboratory assistant.\nBelow is a lists of steps that have been completed.\n<|im_end|>\n<|im_start|>user\n"
        for n, step in enumerate(steps):
            prompt += f"Step {n+1}: {remove_html_tags(step.step_description)}\n"
        current_step = request.data['current_step']
        #current_step = ProtocolStep.objects.get(id=current_step)
        prompt += f"Please summarize the information above in 1 paragraph that is at most 3 sentences long without adding current step information or any other extra.<|im_end|>\n<|im_start|>assistant"

        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        llama_summary.delay(prompt, request.user.id, request.data['target'], custom_id)
        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def summarize_audio_transcript(self, request):
        if not settings.USE_LLM:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        annotation = Annotation.objects.get(id=request.data['target']['annotation'])
        wtt = annotation.transcription
        if annotation.language == "en":
            wtt = annotation.translation
        prompt = f"<|im_start|>system\n You are a helpful laboratory assistant.\nBellow is the content of a webvtt transcription file.\n<|im_end|>\n<|im_start|>user\n{wtt}\n<|im_end|><|im_start|>user\nPlease provide a short summary list of the content above and do not mention that it is from a Webvtt file or any extra details about the file.\n<|im_end|>\n<|im_start|>assistant"
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        llama_summary_transcript.delay(prompt, request.user.id, request.data['target'], custom_id)
        return Response(status=status.HTTP_200_OK)


    @action(detail=False, methods=['get'])
    def generate_turn_credential(self, request):
        if not settings.USE_COTURN:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        user = self.request.user
        timestamp = int(time.time()) + 24*3600
        temporary_username = str(timestamp) + ':' + user.username

        password = hmac.new(bytes(settings.COTURN_SECRET, 'utf-8'), bytes(temporary_username, 'utf-8'), hashlib.sha1)
        password = base64.b64encode(password.digest()).decode()
        return Response({"username": temporary_username, "password": password, "turn_server": settings.COTURN_SERVER, "turn_port": settings.COTURN_PORT}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def export_data(self, request):
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        export_data.delay(request.user.id, custom_id)
        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def import_user_data(self, request):
        user = self.request.user
        chunked_upload_id = request.data['upload_id']
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        chunked_upload = ChunkedUpload.objects.get(id=chunked_upload_id, user=user)
        if chunked_upload.completed_at:
            # get completed file path
            file_path = chunked_upload.file.path
            import_data.delay(user.id, file_path, custom_id)
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def get_server_settings(self, request):
        use_coturn = settings.USE_COTURN
        use_llm = settings.USE_LLM
        use_ocr = settings.USE_OCR
        use_whisper = settings.USE_WHISPER
        allow_overlap_bookings = settings.ALLOW_OVERLAP_BOOKINGS
        can_send_email = settings.NOTIFICATION_EMAIL_FROM != ""
        return Response({
            "allow_overlap_bookings": allow_overlap_bookings,
            "use_coturn": use_coturn,
            "use_llm": use_llm,
            "use_ocr": use_ocr,
            "use_whisper": use_whisper,
            "default_service_lab_group": settings.DEFAULT_SERVICE_LAB_GROUP,
            "can_send_email": can_send_email,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def is_staff(self, request):
        user = self.request.user
        if not user.is_authenticated:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        return Response({"is_staff": user.is_staff}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def get_user_lab_groups(self, request):
        user = self.request.user
        lab_groups = user.lab_groups.all()
        is_professional = request.query_params.get('is_professional', None)
        is_professional = True if is_professional == "true" else False
        if is_professional:
            lab_groups = lab_groups.filter(is_professional=True)
        paginator = LimitOffsetPagination()
        paginator.default_limit = 10
        pagination = paginator.paginate_queryset(lab_groups, request)
        return paginator.get_paginated_response(LabGroupSerializer(pagination, many=True).data)

    @action(detail=False, methods=['post'])
    def check_user_in_lab_group(self, request):
        user = self.request.user
        lab_group = LabGroup.objects.get(id=request.data['lab_group'])
        if user in lab_group.users.all():
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def signup(self, request):
        token = request.data.get('token')
        signer = TimestampSigner()
        try:
            decoded_payload = signer.unsign(token, max_age=60 * 60 * 24)  # Token valid for 24 hours
            payload = loads(decoded_payload)

            user = User.objects.create_user(email=payload['email'], username=request.data['username'])
            user.set_password(request.data['password'])
            user.save()
            if payload['lab_group']:
                lab_group = LabGroup.objects.get(id=payload['lab_group'])
                lab_group.users.add(user)
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        except (BadSignature, SignatureExpired):
            return Response({'error': 'Invalid or expired token'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def generate_signup_token(self, request):
        if not request.user.is_staff:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        email = request.data.get('email')
        lab_group = request.data.get('lab_group')
        if User.objects.filter(email=email).exists():
            return Response({'error': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)
        signer = TimestampSigner()
        payload = {
            'email': email,
            'lab_group': lab_group
        }

        token = signer.sign(dumps(payload))
        return Response({'token': token}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def generate_signup_token_and_send_email(self, request):
        if not request.user.is_staff:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        email = request.data.get('email')
        lab_group = request.data.get('lab_group')
        if User.objects.filter(email=email).exists():
            return Response({'error': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)
        signer = TimestampSigner()
        payload = {
            'email': email,
            'lab_group': lab_group
        }

        token = signer.sign(dumps(payload))
        signup_url = f"{settings.FRONTEND_URL}/#/accounts/signup/{token}"
        if settings.NOTIFICATION_EMAIL_FROM:
            send_mail(
                'Hello from Cupcake',
                f'Please use the following link to sign up: {signup_url}',
                settings.NOTIFICATION_EMAIL_FROM,
                [email],
                fail_silently=False,
            )

        return Response({'token': token}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def current(self, request):
        user = request.user
        data = UserSerializer(user).data
        return Response(data, status=status.HTTP_200_OK)


class ProtocolRatingViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = ProtocolRating.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ['id']
    filterset_fields = ['protocol__id', 'user__id']
    serializer_class = ProtocolRatingSerializer

    def create(self, request, *args, **kwargs):
        user = self.request.user
        protocol = ProtocolModel.objects.get(id=request.data['protocol'])
        rating = ProtocolRating()
        rating.user = user
        rating.protocol = protocol
        if "complexity_rating" in request.data:
            rating.complexity_rating = request.data['complexity_rating']
        if "duration_rating" in request.data:
            rating.duration_rating = request.data['duration_rating']
        rating.save()
        data = self.get_serializer(rating).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if "complexity_rating" in request.data:
            instance.complexity_rating = request.data['complexity_rating']
        if "duration_rating" in request.data:
            instance.duration_rating = request.data['duration_rating']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        user = self.request.user
        return ProtocolRating.objects.filter(user=user)

    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        if obj.user == user:
            return obj
        else:
            raise PermissionDenied

class ReagentViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Reagent.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name']
    filterset_fields = ['name']
    serializer_class = ReagentSerializer

    def create(self, request, *args, **kwargs):
        reagent = Reagent()
        reagent.name = request.data['name']
        reagent.unit = request.data['unit']
        reagent.save()
        data = self.get_serializer(reagent).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.name = request.data['name']
        instance.unit = request.data['unit']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProtocolTagViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = ProtocolTag.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['tag']
    ordering_fields = ['tag']
    filterset_fields = ['tag']
    serializer_class = ProtocolTagSerializer

    def create(self, request, *args, **kwargs):
        tag = ProtocolTag()
        tag.tag = request.data['tag']
        tag.save()
        data = self.get_serializer(tag).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.tag = request.data['tag']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StepTagViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = StepTag.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['tag']
    ordering_fields = ['tag']
    filterset_fields = ['tag']
    serializer_class = StepTagSerializer

    def create(self, request, *args, **kwargs):
        tag = StepTag()
        tag.tag = request.data['tag']
        tag.save()
        data = self.get_serializer(tag).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.tag = request.data['tag']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class TagViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Tag.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['tag']
    ordering_fields = ['tag']
    filterset_fields = ['tag']
    serializer_class = TagSerializer

    def create(self, request, *args, **kwargs):
        tag = Tag()
        tag.tag = request.data['tag']
        tag.save()
        data = self.get_serializer(tag).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.tag = request.data['tag']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AnnotationFolderViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = AnnotationFolder.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['folder_name']
    ordering_fields = ['folder_name']
    filterset_fields = ['folder_name']
    serializer_class = AnnotationFolderSerializer

    def create(self, request, *args, **kwargs):
        folder = AnnotationFolder()
        folder.folder_name = request.data['folder_name']
        folder.save()
        data = self.get_serializer(folder).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.folder_name = request.data['folder_name']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def get_children(self, request, pk=None):
        folder = self.get_object()
        children = AnnotationFolder.objects.filter(parent_folder=folder)
        data = AnnotationFolderSerializer(children, many=True).data
        return Response(data, status=status.HTTP_200_OK)


class ProjectViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Project.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['project_name', 'project_description']
    ordering_fields = ['project_name']
    filterset_fields = ['project_name']
    serializer_class = ProjectSerializer

    def get_queryset(self):
        user = self.request.user
        return Project.objects.filter(owner=user)

    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        if obj.owner == user:
            return obj
        else:
            raise PermissionDenied

    def create(self, request, *args, **kwargs):
        project = Project()
        user = self.request.user
        if "session" in request.data:
            session = Session.objects.filter(unique_id=request.data['session'], user=user)
            if not session.exists():
                return Response(status=status.HTTP_400_BAD_REQUEST)
            project.sessions.add(session.first())
        project.project_name = request.data['name']
        project.project_description = request.data['description']
        project.owner = user
        project.save()
        data = self.get_serializer(project).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if "name" in request.data:
            instance.project_name = request.data['name']
        if "description" in request.data:
            instance.project_description = request.data['description']

        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def remove_session(self, request, pk=None):
        project = self.get_object()
        user = self.request.user
        session = Session.objects.filter(unique_id=request.data['session'], user=user)
        if not session.exists():
            return Response(status=status.HTTP_400_BAD_REQUEST)
        project.sessions.remove(session.first())
        data = self.get_serializer(project).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_session(self, request, pk=None):
        project = self.get_object()
        user = self.request.user
        session = Session.objects.filter(unique_id=request.data['session'], user=user)
        if not session.exists():
            return Response(status=status.HTTP_400_BAD_REQUEST)
        project.sessions.add(session.first())
        data = self.get_serializer(project).data
        return Response(data, status=status.HTTP_200_OK)


class InstrumentViewSet(ModelViewSet, FilterMixin):
    permission_classes = [InstrumentViewSetPermission]
    queryset = Instrument.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['instrument_name', 'instrument_description']
    ordering_fields = ['instrument_name']
    filterset_fields = ['instrument_name']
    serializer_class = InstrumentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Instrument.objects.all()
        if user.is_authenticated:
            query_permission = Q(user=user)
            query_permission = query_permission & Q(Q(can_book=True) | Q(can_view=True) | Q(can_manage=True))
            i_permission = InstrumentPermission.objects.filter(query_permission)
            if i_permission.exists():
                instruments = []
                for i in i_permission:
                    instruments.append(i.instrument.id)
                return Instrument.objects.filter(id__in=instruments)

        return Instrument.objects.filter(enabled=True)

    def get_object(self):
        obj = super().get_object()
        return obj

    def create(self, request, *args, **kwargs):
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        if Instrument.objects.filter(instrument_name=request.data['name']).exists():
            return Response(status=status.HTTP_409_CONFLICT)
        instrument = Instrument()
        instrument.instrument_name = request.data['name']
        instrument.instrument_description = request.data['description']
        instrument.save()
        data = self.get_serializer(instrument).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not self.request.user.is_staff:
            i_permission = InstrumentPermission.objects.filter(instrument=instance, user=self.request.user)
            if i_permission.exists():
                if not i_permission.first().can_manage:
                    return Response(status=status.HTTP_401_UNAUTHORIZED)
            else:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        if "name" in request.data:
            instance.instrument_name = request.data['name']
        if "description" in request.data:
            instance.instrument_description = request.data['description']
        if 'max_days_ahead_pre_approval' in request.data:
            instance.max_days_ahead_pre_approval = request.data['max_days_ahead_pre_approval']
        if 'max_days_within_usage_pre_approval' in request.data:
            instance.max_days_within_usage_pre_approval = request.data['max_days_within_usage_pre_approval']
        if 'image' in request.data:
            instance.image = request.data['image']
        if 'days_before_maintenance_notification' in request.data:
            instance.days_before_maintenance_notification = request.data['days_before_maintenance_notification']
        if 'days_before_warranty_notification' in request.data:
            instance.days_before_warranty_notification = request.data['days_before_warranty_notification']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def assign_instrument_permission(self, request, pk=None):
        user = self.request.user
        instrument = self.get_object()
        target_user = User.objects.get(username=request.data['user'])
        current_user_permission = InstrumentPermission.objects.filter(instrument=instrument, user=user)
        if current_user_permission.exists():
            if not current_user_permission.first().can_manage and not user.is_staff:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
            else:
                can_manage = request.data['can_manage']
                can_book = request.data['can_book']
                can_view = request.data['can_view']
                permission = InstrumentPermission.objects.get_or_create(instrument=instrument, user=target_user)
                if user.is_staff:
                    permission[0].can_manage = can_manage
                permission[0].can_book = can_book
                permission[0].can_view = can_view
                permission[0].save()
                return Response(status=status.HTTP_200_OK)
        else:
            if user.is_staff:
                can_manage = request.data['can_manage']
                can_book = request.data['can_book']
                can_view = request.data['can_view']
                permission = InstrumentPermission.objects.get_or_create(instrument=instrument, user=target_user)
                permission[0].can_manage = can_manage
                permission[0].can_book = can_book
                permission[0].can_view = can_view
                permission[0].save()
                return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_401_UNAUTHORIZED)

    @action(detail=True, methods=['get'])
    def get_instrument_permission(self, request, pk=None):
        instrument = self.get_object()
        user = self.request.user
        permission = InstrumentPermission.objects.filter(instrument=instrument, user=user)
        data = {
            "can_view": False,
            "can_manage": False,
            "can_book": False
        }
        if permission.exists():
            permission = permission.first()
            data = {
                "can_view": permission.can_view,
                "can_manage": permission.can_manage,
                "can_book": permission.can_book
            }
            return Response(data, status=status.HTTP_200_OK)
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_instrument_permission_for(self, request, pk=None):
        instrument = Instrument.objects.get(id=pk)
        manager = self.request.user
        manager_permission = InstrumentPermission.objects.filter(instrument=instrument, user=manager)
        if manager_permission.exists():
            if not manager_permission.first().can_manage and not manager.is_staff:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        else:
            if not manager.is_staff:
                return Response(status=status.HTTP_401_UNAUTHORIZED)

        for_user = self.request.query_params.get('user', None)
        user = User.objects.filter(username=for_user)
        if not user.exists():
            return Response(status=status.HTTP_404_NOT_FOUND)
        user = user.first()
        permission = InstrumentPermission.objects.filter(instrument=instrument, user=user)
        data = {
            "can_view": False,
            "can_manage": False,
            "can_book": False
        }
        if permission.exists():
            permission = permission.first()
            data = {
                "can_view": permission.can_view,
                "can_manage": permission.can_manage,
                "can_book": permission.can_book
            }
            return Response(data, status=status.HTTP_200_OK)
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def delay_usage(self, request, pk=None):
        instrument = self.get_object()
        if not self.request.user.is_staff:
            i_permissions = InstrumentPermission.objects.filter(instrument=instrument, user=request.user)
            if not i_permissions.exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
            else:
                if not i_permissions.first().can_manage:
                    return Response(status=status.HTTP_401_UNAUTHORIZED)
        delay_start_time = request.data['start_date']
        # get usage that is active during or after the delay_start_time
        usage = InstrumentUsage.objects.filter(instrument=instrument, time_started__gte=delay_start_time)
        if usage.exists():
            for u in usage:
                u.time_started = u.time_started + timedelta(days=request.data['days'])
                u.time_ended = u.time_ended + timedelta(days=request.data['days'])
                u.save()
        return Response(InstrumentSerializer(instrument, many=False).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_support_information(self, request, pk=None):
        instrument = self.get_object()

        if not request.user.is_staff:
            permission = InstrumentPermission.objects.filter(
                user=request.user,
                instrument=instrument,
                can_manage=True
            )
            if not permission.exists():
                return Response(
                    {"error": "You don't have permission to add support information for this instrument"},
                    status=status.HTTP_403_FORBIDDEN
                )

        support_info_id = request.data.get('id')

        if not support_info_id:
            return Response(
                {"error": "No support_information_id provided"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            support_info = SupportInformation.objects.get(id=support_info_id)
        except SupportInformation.DoesNotExist:
            return Response(
                {"error": "Support information not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        instrument.support_information.add(support_info)

        return Response(
            {"message": "Support information added to instrument successfully"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def remove_support_information(self, request, pk=None):
        instrument = self.get_object()

        if not request.user.is_staff:
            permission = InstrumentPermission.objects.filter(
                user=request.user,
                instrument=instrument,
                can_manage=True
            )
            if not permission.exists():
                return Response(
                    {"error": "You don't have permission to remove support information from this instrument"},
                    status=status.HTTP_403_FORBIDDEN
                )

        support_info_id = request.data.get('id')

        if not support_info_id:
            return Response(
                {"error": "No support_information_id provided"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            support_info = SupportInformation.objects.get(id=support_info_id)
        except SupportInformation.DoesNotExist:
            return Response(
                {"error": "Support information not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if support_info not in instrument.support_information.all():
            return Response(
                {"error": "This support information is not associated with this instrument"},
                status=status.HTTP_400_BAD_REQUEST
            )

        instrument.support_information.remove(support_info)

        return Response(
            {"message": "Support information removed from instrument successfully"},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['get'])
    def list_support_information(self, request, pk=None):
        instrument = self.get_object()
        support_info = instrument.support_information.all()
        serializer = SupportInformationSerializer(support_info, many=True)

        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def create_support_information(self, request, pk=None):
        instrument = self.get_object()

        if not request.user.is_staff:
            permission = InstrumentPermission.objects.filter(
                user=request.user,
                instrument=instrument,
                can_manage=True
            )
            if not permission.exists():
                return Response(
                    {"error": "You don't have permission to add support information for this instrument"},
                    status=status.HTTP_403_FORBIDDEN
                )

        serializer = SupportInformationSerializer(data=request.data, context={'request': request})

        if serializer.is_valid():
            support_info = serializer.save()
            instrument.support_information.add(support_info)

            return Response(
                SupportInformationSerializer(support_info).data,
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def get_maintenance_status(self, request, pk=None):
        """
        Get maintenance status for an instrument including:
        - Days since last routine maintenance
        - Days until next scheduled maintenance
        - Whether maintenance is overdue
        """
        instrument = self.get_object()

        last_maintenance = MaintenanceLog.objects.filter(
            instrument=instrument,
            maintenance_type='routine',
            status='completed',
            is_template=False
        ).order_by('-maintenance_date').first()

        support_info = SupportInformation.objects.filter(instrument=instrument).first()
        maintenance_frequency = support_info.maintenance_frequency_days if support_info else None

        today = timezone.now().date()

        result = {
            'has_maintenance_record': last_maintenance is not None,
            'maintenance_frequency_days': maintenance_frequency,
        }

        if last_maintenance:
            last_date = last_maintenance.maintenance_date.date()
            days_since_last = (today - last_date).days
            result['last_maintenance_date'] = last_date
            result['days_since_last_maintenance'] = days_since_last

            if maintenance_frequency:
                next_date = last_date + timedelta(days=maintenance_frequency)
                days_until_next = (next_date - today).days
                result['next_maintenance_date'] = next_date
                result['days_until_next_maintenance'] = days_until_next
                result['is_overdue'] = days_until_next < 0
                result['overdue_days'] = abs(days_until_next) if days_until_next < 0 else 0
        elif maintenance_frequency:
            result['is_overdue'] = True
            result['overdue_days'] = None
            result['next_maintenance_date'] = today
            result['days_until_next_maintenance'] = 0

        return Response(result)

    @action(detail=True, methods=['post'])
    def notify_slack(self, request, pk=None):
        """Send a notification to Slack about an instrument issue or status"""
        instrument = self.get_object()
        message = request.data.get('message')

        if not message:
            return Response({"error": "Message is required"},
                            status=status.HTTP_400_BAD_REQUEST)

        # Format the message with instrument details
        formatted_message = f"*Instrument Alert:* {instrument.instrument_name}\n{message}"

        # Optional attachment with more details
        attachments = [{
            "color": "#FF0000" if request.data.get('urgent') else "#36a64f",
            "fields": [
                {
                    "title": "Reported by",
                    "value": request.user.username,
                    "short": True
                },
                {
                    "title": "Status",
                    "value": request.data.get('status', 'N/A'),
                    "short": True
                }
            ]
        }]

        # Send to Slack
        success = send_slack_notification(
            formatted_message,
            username="Instrument Bot",
            icon_emoji=":microscope:",
            attachments=attachments
        )

        if success:
            return Response({"status": "Message sent to Slack"})
        else:
            return Response({"error": "Failed to send message to Slack"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def trigger_instrument_check(self, request):
        """
        Manually trigger instrument checks for specific or all instruments.
        Only accessible by staff users.
        """
        if not request.user.is_staff:
            return Response({"error": "You don't have permission to trigger instrument checks"},
                            status=status.HTTP_403_FORBIDDEN)

        instrument_id = request.data.get('instrument_id', None)
        days_before_warranty_warning = request.data.get('days_before_warranty_warning', None)
        days_before_maintenance_warning = request.data.get('days_before_maintenance_warning', None)
        instance_id = request.data.get('instance_id', None)

        if instrument_id:
            try:
                instrument = Instrument.objects.get(id=instrument_id)
                job = check_instrument_warranty_maintenance.delay([instrument.id], days_before_warranty_warning, days_before_maintenance_warning, request.user.id, instance_id)
                return Response({
                    "message": f"Check triggered for instrument: {instrument.instrument_name}",
                    "task_id": job.id
                }, status=status.HTTP_200_OK)
            except Instrument.DoesNotExist:
                return Response({"error": "Instrument not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            job = check_instrument_warranty_maintenance.delay([], days_before_warranty_warning, days_before_maintenance_warning, request.user.id, instance_id)
            return Response({
                "message": "Check triggered for all instruments",
                "task_id": job.id
            }, status=status.HTTP_200_OK)

class InstrumentUsageViewSet(ModelViewSet, FilterMixin):
    permission_classes = [InstrumentUsagePermission]
    queryset = InstrumentUsage.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['instrument__instrument_name']
    ordering_fields = ['time_started', 'time_ended']
    filterset_fields = ['instrument__instrument_name']
    serializer_class = InstrumentUsageSerializer

    def get_queryset(self):
        time_started = self.request.query_params.get('time_started', None)
        time_ended = self.request.query_params.get('time_ended', None)
        instrument = self.request.query_params.get('instrument', None)
        users = self.request.query_params.get('users', None)
        search_type = self.request.query_params.get('search_type', None)
        if users:
            users = users.split(',')
        if instrument:
            instrument = instrument.split(',')
        if search_type in ['logs', 'usage']:
        # filter for any usage where time_started or time_ended of the usage falls within the range of the query
            if not time_started:
                time_started = timezone.now() - timedelta(days=1)

            if not time_ended:
                time_ended = timezone.now() + timedelta(days=1)
            query = Q()

            if users:
                query &= Q(user__username__in=users)

            query_time_started = Q(time_started__range=[time_started, time_ended])
            query_time_ended = Q(time_ended__range=[time_started, time_ended])
            if search_type == "logs":
                query_time_started = Q(created_at__range=[time_started, time_ended])
                query_time_ended = Q(created_at__range=[time_started, time_ended])
            # filter for only instruments that the user has permission to view
            if not self.request.user.is_staff:
                if instrument:
                    can_view = InstrumentPermission.objects.filter(instrument__id__in=instrument, user=self.request.user, can_view=True)
                else:
                    can_view = InstrumentPermission.objects.filter(user=self.request.user, can_view=True)
                if not can_view.exists():
                    return InstrumentUsage.objects.none()
                instruments_ids = [i.instrument.id for i in can_view]
                if instruments_ids:
                    query &= Q(instrument__id__in=instruments_ids)
            else:
                if instrument:
                    query &= Q(instrument__id__in=instrument)

            if self.request.user.is_staff:
                return self.queryset.filter((query_time_started | query_time_ended)&query).order_by('-created_at')

            return self.queryset.filter((query_time_started | query_time_ended)&query).order_by('-created_at')
        if not self.request.user.is_staff:
            can_view = InstrumentPermission.objects.filter(user=self.request.user, can_view=True)
            if not can_view.exists():
                return InstrumentUsage.objects.none()
            instruments_ids = [i.instrument.id for i in can_view]
            return self.queryset.filter(instrument__id__in=instruments_ids).order_by('-created_at')
        return self.queryset.order_by('-created_at')

    def get_object(self):
        obj = super().get_object()
        print(obj)
        return obj

    @action(detail=False, methods=['get'])
    def get_user_instrument_usage(self, request):
        user = self.request.user
        instrument_usage = self.queryset.filter(user=user)
        data = self.get_serializer(instrument_usage, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        time_started = parse_datetime(request.data['time_started'])
        time_ended = parse_datetime(request.data['time_ended'])
        if time_started and time_ended:
            if timezone.is_naive(time_started):
                time_started = timezone.make_aware(time_started, timezone.get_current_timezone())
            if timezone.is_naive(time_ended):
                time_ended = timezone.make_aware(time_ended, timezone.get_current_timezone())
        if InstrumentUsage.objects.filter(time_started__range=[time_started,time_ended]).exists() or InstrumentUsage.objects.filter(time_ended__range=[time_started, time_ended]).exists():
            return Response(status=status.HTTP_409_CONFLICT)
        if "time_started" in request.data:
            instance.time_started = time_started
        if "time_ended" in request.data:
            instance.time_ended = time_ended
        if request.user.is_staff:
            if "approved" in request.data:
                instance.approved = request.data['approved']
            if "maintenance" in request.data:
                instance.maintenance = request.data['maintenance']
        else:
            can_manage_permission = InstrumentPermission.objects.filter(instrument=instance.instrument, user=request.user, can_manage=True)
            if can_manage_permission.exists():
                if "approved" in request.data:
                    instance.approved = request.data['approved']
                if "maintenance" in request.data:
                    instance.maintenance = request.data['maintenance']

        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'])
    def delete_usage(self, request, pk=None):
        instance: InstrumentUsage = InstrumentUsage.objects.get(id=pk)
        # if not instance.annotation.user == self.request.user and not self.request.user.is_staff:
        #     return Response(status=status.HTTP_401_UNAUTHORIZED)
        # permission = InstrumentPermission.objects.filter(instrument=instance.instrument, user=self.request.user)
        # if not permission.exists():
        #     return Response(status=status.HTTP_401_UNAUTHORIZED)
        # else:
        #     if not permission.first().can_manage:
        #         return Response(status=status.HTTP_401_UNAUTHORIZED)
        instrument = instance.instrument
        if not self.request.user.is_staff:
            if not self.request.user == instance.user:
                i_permissions = InstrumentPermission.objects.filter(instrument=instrument, user=self.request.user)
                if not i_permissions.exists():
                    return Response(status=status.HTTP_401_UNAUTHORIZED)
                else:
                    if not i_permissions.first().can_manage:
                        return Response(status=status.HTTP_401_UNAUTHORIZED)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


    def create(self, request, *args, **kwargs):
        instrument = Instrument.objects.get(id=request.data['instrument'])
        user = self.request.user
        time_started = parse_datetime(request.data['time_started'])
        time_ended = parse_datetime(request.data['time_ended'])
        usage = InstrumentUsage()
        repeat = request.data.get('repeat', 0)
        repeat_until = request.data.get('repeat_until', None)
        if repeat and repeat_until:
            repeat_until = parse_datetime(repeat_until)
            if timezone.is_naive(repeat_until):
                repeat_until = timezone.make_aware(repeat_until, timezone.get_current_timezone())

        if time_started and time_ended:
            if timezone.is_naive(time_started):
                time_started = timezone.make_aware(time_started, timezone.get_current_timezone())
            if timezone.is_naive(time_ended):
                time_ended = timezone.make_aware(time_ended, timezone.get_current_timezone())

        if (InstrumentUsage.objects.filter(time_started__range=[time_started,time_ended]).exists()
                or
                InstrumentUsage.objects.filter(time_ended__range=[time_started, time_ended]).exists()):
            if not settings.ALLOW_OVERLAP_BOOKINGS:
                return Response(status=status.HTTP_409_CONFLICT)

        usage.instrument = instrument
        usage.user = user
        usage.time_started = time_started
        usage.time_ended = time_ended
        usage.description = request.data['description']
        duration = usage.time_ended - usage.time_started

        day_ahead = usage.time_started - timezone.now()

        if (
                duration.days +1
                <= instrument.max_days_within_usage_pre_approval
                #or instrument.max_days_within_usage_pre_approval == 0
        ) and (
                day_ahead.days+1 <=
                instrument.max_days_ahead_pre_approval
                # or instrument.max_days_ahead_pre_approval == 0
        ):
            usage.approved = True
        else:
            usage.approved = False

        if 'maintenance' in request.data:
            usage.maintenance = request.data['maintenance']
            if usage.maintenance:
                usage.approved = True
                if not request.user.is_staff:
                    can_manage = InstrumentPermission.objects.filter(instrument=instrument, user=request.user, can_manage=True)
                    if not can_manage.exists():
                        return Response(status=status.HTTP_401_UNAUTHORIZED)

        usage.save()
        if usage.maintenance and repeat and repeat_until:
            while usage.time_ended < repeat_until:
                # create a new usage object for each repeat
                new_usage = InstrumentUsage()
                new_usage.instrument = instrument
                new_usage.user = user
                new_usage.time_started = usage.time_started + timedelta(days=repeat)
                new_usage.time_ended = usage.time_ended + timedelta(days=repeat)
                new_usage.description = request.data['description']
                new_usage.approved = True
                new_usage.maintenance = True
                new_usage.save()
                usage = new_usage
        data = self.get_serializer(usage).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def delay_usage(self, request, pk=None):
        instance = InstrumentUsage.objects.get(id=pk)
        if not self.request.user.is_staff:
            i_permissions = InstrumentPermission.objects.filter(instrument=instance.instrument, user=request.user)
            if not i_permissions.exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
            else:
                if not i_permissions.first().can_manage:
                    return Response(status=status.HTTP_401_UNAUTHORIZED)
        days = request.data['days']
        instance.time_started = instance.time_started + timedelta(days=days)
        instance.time_ended = instance.time_ended + timedelta(days=days)
        instance.save()
        return Response(InstrumentUsageSerializer(instance, many=False).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def export_usage(self, request):
        instruments = request.data.get('instruments', [])
        usage = InstrumentUsage.objects.all()
        if instruments:
            usage = usage.filter(instrument__id__in=instruments)
        if not request.user.is_staff:
            can_manage = InstrumentPermission.objects.filter(user=request.user, can_manage=True)
            if instruments:
                can_manage = can_manage.filter(instrument__id__in=instruments)
            if not can_manage.exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)

            usage = usage.filter(instrument__id__in=[i.instrument.id for i in can_manage])

        instrument_ids = list(set([u.instrument.id for u in usage]))
        lab_group_id = request.data.get('lab_group', [])
        user_id = request.data.get('user', [])
        time_started = request.data.get('time_started', None)
        time_ended = request.data.get('time_ended', None)
        mode = request.data.get('mode', 'user')
        file_format = request.data.get('file_format', 'xlsx')
        calculate_duration_with_cutoff = request.data.get('calculate_duration_with_cutoff', False)
        instance_id = request.data.get('instance_id', None)
        includes_maintenance = request.data.get('includes_maintenance', False)
        approved_only = request.data.get('approved_only', True)
        job = export_instrument_usage.delay(instrument_ids, lab_group_id, user_id, mode, instance_id, time_started, time_ended, calculate_duration_with_cutoff, request.user.id, file_format, includes_maintenance, approved_only)
        return Response({'job_id': job.id}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def approve_usage_toggle(self, request, pk=None):
        instance = self.get_object()
        if not self.request.user.is_staff:
            i_permissions = InstrumentPermission.objects.filter(instrument=instance.instrument, user=request.user, can_manage=True)
            if not i_permissions.exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        instance.approved = not instance.approved
        instance.save()
        if instance.approved:
            instance.approved_by = request.user
            instance.save()
            # send email to user
            if instance.user.email and settings.NOTIFICATION_EMAIL_FROM:
                send_mail(
                    'Instrument Usage Approved',
                    f'Your usage of {instance.instrument.instrument_name} from {instance.time_started} to {instance.time_ended} has been approved',
                    settings.NOTIFICATION_EMAIL_FROM,
                    [instance.user.email]
                )
        return Response(InstrumentUsageSerializer(instance, many=False).data, status=status.HTTP_200_OK)


class StorageObjectViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticated]
    queryset = StorageObject.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['object_name', 'object_description', 'object_type']
    ordering_fields = ['object_name', 'object_type']
    filterset_fields = ['object_name', 'object_type']
    serializer_class = StorageObjectSerializer
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        query = Q()
        stored_at = self.request.query_params.get('stored_at', None)
        if stored_at:
            store_at = StorageObject.objects.get(id=stored_at)
            query &= Q(stored_at=store_at)

        root = self.request.query_params.get('root', None)
        if root:
            if root.lower() == 'true':
                query &= Q(stored_at__isnull=True)

        lab_group = self.request.query_params.get('lab_group', None)
        if lab_group:
            query &= Q(access_lab_groups=lab_group)

        exclude_objects = self.request.query_params.get('exclude_objects', None)
        if exclude_objects:
            query &= ~Q(id__in=exclude_objects.split(","))
        return self.queryset.filter(query)

    def get_object(self):
        obj = super().get_object()
        return obj

    def create(self, request, *args, **kwargs):

        stored_at = None
        if "stored_at" in request.data:
            stored_at = request.data['stored_at']
        if not stored_at:
            if not self.request.user.is_staff:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
            if StorageObject.objects.filter(object_name=request.data['name'], object_type=request.data['object_type'],
                                            stored_at__isnull=True).exists():
                return Response(status=status.HTTP_409_CONFLICT)
        else:
            stored_at = StorageObject.objects.get(id=stored_at)
            if StorageObject.objects.filter(object_name=request.data['name'], object_type=request.data['object_type'],
                                            stored_at=stored_at).exists():
                return Response(status=status.HTTP_409_CONFLICT)
        data = {
            "object_name": request.data.get('name', None),
            "object_description": request.data.get('description', None),
            "object_type": request.data.get('object_type', None),
            "stored_at": request.data.get('stored_at', None),
            "png_base64": request.data.get('png_base64', None)
        }
        if request.data.get('object_name', None):
            data['object_name'] = request.data['object_name']
        if request.data.get('object_description', None):
            data['object_description'] = request.data['object_description']


        serializer = self.get_serializer(data=data)
        #storage_object = StorageObject()
        #storage_object.object_name = request.data['name']
        #storage_object.object_description = request.data['description']
        #storage_object.object_type = request.data['object_type']
        #storage_object.user = self.request.user
        #storage_object.stored_at = stored_at
        #if "png_base64" in request.data:
        #    storage_object.png_base64 = request.data['png_base64']
        #storage_object.save()

        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user != self.request.user and not self.request.user.is_staff:
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        data = {}
        if "name" in request.data:
            data['object_name'] = request.data['name']
        if "object_name" in request.data:
            data['object_name'] = request.data['object_name']

        if "description" in request.data:
            data['object_description'] = request.data['description']
        if "object_description" in request.data:
            data['object_description'] = request.data['object_description']

        if "object_type" in request.data:
            data['object_type'] = request.data['object_type']

        serializer = self.get_serializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        #if "name" in request.data:
        #    instance.object_name = request.data['name']
        #if "description" in request.data:
        #    instance.object_description = request.data['description']
        #if "png_base64" in request.data:
        #    instance.png_base64 = request.data['png_base64']
        #instance.save()

        return Response(serializer.data, status=status.HTTP_200_OK)

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not self.request.user.is_staff and not instance.can_delete:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        all_children = instance.get_all_children()
        all_children = all_children + [instance]
        stored_within = StoredReagent.objects.filter(Q(storage_object__in=all_children) & ~Q(user=self.request.user))
        if stored_within.exists():
            return Response(data="Storage object are not empty and containing items not owned by the user",status=status.HTTP_409_CONFLICT)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def add_access_group(self, request, pk=None):
        instance = self.get_object()
        if not self.request.user.is_staff and instance.user == self.request.user:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        lab_group = LabGroup.objects.get(id=request.data['lab_group'])
        if not self.request.user.is_staff:
            if not lab_group.users.filter(id=self.request.user.id).exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        instance.access_lab_groups.add(lab_group)
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_access_group(self, request, pk=None):
        instance = self.get_object()
        if not self.request.user.is_staff and instance.user == self.request.user:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        lab_group = LabGroup.objects.get(id=request.data['lab_group'])
        if not lab_group.users.filter(id=self.request.user.id).exists():
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        instance.access_lab_groups.remove(lab_group)
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    # @action(detail=True, methods=['post'])
    # def store_reagent(self, request, pk=None):
    #     storage_object = self.get_object()
    #     quantity = self.request.data['quantity']
    #     user = self.request.user
    #     reagent = Reagent.objects.filter(reagent=self.request.data['reagent'], unit=self.request.data['unit'])
    #     if reagent.exists():
    #         reagent = reagent.first()
    #     else:
    #         reagent = Reagent()
    #         reagent.name = self.request.data['reagent']
    #         reagent.unit = self.request.data['unit']
    #         reagent.save()
    #     stored_reagent = StoredReagent()
    #
    #     stored_reagent.reagent = reagent
    #     stored_reagent.quantity = quantity
    #     stored_reagent.storage_object = storage_object
    #     stored_reagent.user = user
    #     stored_reagent.save()

    @action(detail=True, methods=['get'])
    def get_path_to_root(self, request, pk=None):
        storage_object = self.get_object()

        return Response(storage_object.get_path_to_root(), status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def export_reagent_actions(self, request, pk=None):
        storage_object: StorageObject = self.get_object()
        if not request.user.is_staff:
            if not storage_object.user == request.user:
                labGroups = LabGroup.objects.filter(users=self.request.user)
                if not storage_object.access_lab_groups.filter(id__in=labGroups).exists():
                    return Response(status=status.HTTP_401_UNAUTHORIZED)
        end_date = request.data.get('end_date', None)
        start_date = request.data.get('start_date', None)
        instance_id = request.data.get('instance_id', None)
        if end_date:
            end_date = parse_datetime(end_date)
            if timezone.is_naive(end_date):
                end_date = timezone.make_aware(end_date, timezone.get_current_timezone())
        if start_date:
            start_date = parse_datetime(start_date)
            if timezone.is_naive(start_date):
                start_date = timezone.make_aware(start_date, timezone.get_current_timezone())
        if not end_date:
            end_date = timezone.now()
        if not start_date:
            start_date = timezone.now() - timedelta(days=30)
        if start_date > end_date:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        job = export_reagent_actions.delay(start_date, end_date, storage_object.id, None, self.request.user.id, 'csv', instance_id)
        return Response({'job_id': job.id}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def download_report(self, request):
        """
        Download a report of the storage object from generated token encoded signed filename
        """
        token = request.query_params.get('token', None)
        if not token:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        signer = TimestampSigner()
        try:
            data = signer.unsign(token, max_age=60 * 30)
            response = HttpResponse(status=200)
            response["Content-Disposition"] = f'attachment; filename="{data}"'
            response["X-Accel-Redirect"] = f"/media/temp/{data}"
            return response
        except BadSignature:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        except SignatureExpired:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def move_storage_objects(self, request):
        """Move multiple storage objects to a new parent"""
        if not request.user.is_staff:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        target_parent_id = request.data.get('target_parent_id')
        storage_object_ids = request.data.get('storage_object_ids', [])

        if not storage_object_ids:
            return Response(
                {"detail": "No storage objects specified"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get target parent (can be None for root level)
        target_parent = None
        if target_parent_id:
            try:
                target_parent = StorageObject.objects.get(id=target_parent_id)
            except StorageObject.DoesNotExist:
                return Response(
                    {"detail": "Target parent not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Update each storage object
        updated_objects = []
        errors = []

        for obj_id in storage_object_ids:
            try:
                obj = StorageObject.objects.get(id=obj_id)
                if target_parent and target_parent.id in [c.id for c in obj.get_all_children()]:
                    errors.append({
                        'id': obj_id,
                        'errors': 'Cannot move object to be its own descendant'
                    })
                    continue

                obj.stored_at = target_parent
                obj.save()
                updated_objects.append(obj)
            except StorageObject.DoesNotExist:
                errors.append({
                    'id': obj_id,
                    'errors': 'Storage object not found'
                })
        result = {
            'updated': self.get_serializer(updated_objects, many=True).data
        }
        if errors:
            result['errors'] = errors

        return Response(result)

    @action(detail=True, methods=['post'])
    def import_reagent(self, request, pk=None):
        instance = self.get_object()
        file_upload_id = request.data.get('file_upload_id', None)
        if not file_upload_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        instance_id = request.data.get('instance_id', None)
        if not instance_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        file = ChunkedUpload.objects.get(id=file_upload_id)
        file_path = file.file.path
        job = import_reagents_from_file.delay(file_path, instance.id, self.request.user.id, None, instance.id)
        return Response({'job_id': job.id}, status=status.HTTP_200_OK)

class StoredReagentViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticated]
    queryset = StoredReagent.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['reagent__name', 'reagent__unit', 'barcode']
    ordering_fields = ['reagent__name', 'reagent__unit', 'barcode']
    filterset_fields = ['reagent__name', 'reagent__unit', 'barcode']
    serializer_class = StoredReagentSerializer
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        query = Q()
        stored_id = self.request.query_params.get('id', None)
        if stored_id:
            query &= Q(id=int(stored_id))
        if self.request.query_params.get('user_only', 'false') == 'true':
            query &= Q(user=self.request.user)
        if self.request.query_params.get('storage_object_name', None):
            storage_object = StorageObject.objects.filter(object_name__icontains=self.request.query_params.get('storage_object_name'))
            storage_object_list = []
            if storage_object.exists():

                for obj in storage_object:
                    storage_object_list += obj.get_all_children()
                    storage_object_list.append(obj)
            query &= Q(storage_object__in=storage_object_list)

        if self.request.query_params.get('storage_object', None):
            storage_object = StorageObject.objects.get(id=self.request.query_params.get('storage_object'))
            all_children = storage_object.get_all_children()
            all_children = all_children+[storage_object]
            if (len(all_children) == 1):
                query &= Q(storage_object=storage_object)
            else:
                query &= Q(storage_object__in=all_children)
            query &= Q(storage_object__in=all_children)

        lab_group = self.request.query_params.get('lab_group', None)
        if lab_group:
            lab_group = LabGroup.objects.get(id=lab_group)
            query &= Q(storage_object__in=lab_group.storage_objects.all())
        result = StoredReagent.objects.filter(query)
        return result

    def get_object(self):
        obj = super().get_object()
        return obj

    def create(self, request, *args, **kwargs):
        data = request.data.copy()

        if 'name' in data and 'unit' in data and 'reagent_id' not in data:
            reagent = Reagent.objects.filter(name=data['name'], unit=data['unit']).first()
            if not reagent:
                reagent = Reagent.objects.create(name=data['name'], unit=data['unit'])
            data['reagent_id'] = reagent.id

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        data = request.data.copy()

        if 'name' in data and 'unit' in data and 'reagent_id' not in data:
            reagent = Reagent.objects.filter(name=data['name'], unit=data['unit']).first()
            if not reagent:
                reagent = Reagent.objects.create(name=data['name'], unit=data['unit'])
            data['reagent_id'] = reagent.id

        serializer = self.get_serializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(serializer.data)

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        permission = self._get_user_permission(instance, self.request.user)
        if not permission["delete"]:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def get_reagent_actions(self, request, pk=None):
        stored_reagent = self.get_object()
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        if not start_date:
            start_date = datetime.now() - timedelta(days=1)
        if not end_date:
            end_date = datetime.now() + timedelta(days=1)
        actions = ReagentAction.objects.filter(reagent=stored_reagent, created_at__range=[start_date, end_date])
        data = ReagentActionSerializer(actions, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_access_user(self, request, pk=None):
        stored_reagent = self.get_object()
        user = User.objects.get(username=request.data['user'])
        if not self.request.user.is_staff:
            if not stored_reagent.user == self.request.user:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        stored_reagent.access_users.add(user)
        data = self.get_serializer(stored_reagent).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_access_user(self, request, pk=None):
        stored_reagent = self.get_object()
        user = User.objects.get(username=request.data['user'])
        if not self.request.user.is_staff:
            if not stored_reagent.user == self.request.user:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        stored_reagent.access_users.remove(user)
        data = self.get_serializer(stored_reagent).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_access_group(self, request, pk=None):
        stored_reagent = self.get_object()
        group = LabGroup.objects.get(id=request.data['lab_group'])
        if not self.request.user.is_staff:
            if not stored_reagent.user == self.request.user:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        stored_reagent.access_lab_groups.add(group)
        data = self.get_serializer(stored_reagent).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_access_group(self, request, pk=None):
        stored_reagent = self.get_object()
        group = LabGroup.objects.get(id=request.data['lab_group'])
        if not self.request.user.is_staff:
            if not stored_reagent.user == self.request.user:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        stored_reagent.access_lab_groups.remove(group)
        data = self.get_serializer(stored_reagent).data
        return Response(data, status=status.HTTP_200_OK)

    def _get_user_permission(self, stored_reagent, user):
        permission = {
            "edit": False,
            "delete": False
        }
        if user.is_staff:
            permission["edit"] = True
            permission["delete"] = True
            return permission
        if stored_reagent.user == user:
            permission["edit"] = True
            permission["delete"] = True
        elif stored_reagent.shareable:
            if stored_reagent.access_all:
                permission["edit"] = True
            elif user in stored_reagent.access_users.all():
                permission["edit"] = True
            elif user.lab_groups.filter(id__in=stored_reagent.access_lab_groups.all().values_list('id', flat=True)).exists():
                permission["edit"] = True
        return permission

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def subscribe(self, request, pk=None):
        stored_reagent = self.get_object()
        notify_low_stock = request.data.get('notify_on_low_stock', False)
        notify_expiry = request.data.get('notify_on_expiry', False)

        subscription = stored_reagent.subscribe_user(
            request.user,
            notify_low_stock=notify_low_stock,
            notify_expiry=notify_expiry
        )

        return Response({
            'success': True,
            'subscription': {
                'id': subscription.id,
                'notify_on_low_stock': subscription.notify_on_low_stock,
                'notify_on_expiry': subscription.notify_on_expiry
            }
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def unsubscribe(self, request, pk=None):
        stored_reagent = self.get_object()
        unsubscribe_low_stock = request.data.get('notify_on_low_stock', False)
        unsubscribe_expiry = request.data.get('notify_on_expiry', False)

        result = stored_reagent.unsubscribe_user(
            request.user,
            notify_low_stock=unsubscribe_low_stock,
            notify_expiry=unsubscribe_expiry
        )

        return Response({
            'success': True,
            'unsubscribed': {
                'notify_on_low_stock': unsubscribe_low_stock,
                'notify_on_expiry': unsubscribe_expiry
            }
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def subscribers(self, request, pk=None):
        stored_reagent = self.get_object()

        if request.user == stored_reagent.user or request.user.is_staff:
            subscribers = stored_reagent.subscriptions.all()
            data = [{
                'user_id': sub.user.id,
                'username': sub.user.username,
                'notify_on_low_stock': sub.notify_on_low_stock,
                'notify_on_expiry': sub.notify_on_expiry
            } for sub in subscribers]
            return Response(data)

        return Response({
            'error': 'You do not have permission to view subscribers'
        }, status=status.HTTP_403_FORBIDDEN)

class ReagentActionViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticated]
    queryset = ReagentAction.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['action_type', 'reagent__reagent__name', 'reagent__reagent__unit']
    ordering_fields = ['action_type', 'reagent__reagent__name', 'reagent__reagent__unit', 'created_at', 'updated_at']
    filterset_fields = ['action_type', 'reagent__reagent__name', 'reagent__reagent__unit']
    serializer_class = ReagentActionSerializer
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        if self.request.query_params.get('reagent', None):
            reagent = StoredReagent.objects.get(id=self.request.query_params.get('reagent'))
            return ReagentAction.objects.filter(reagent=reagent)
        return ReagentAction.objects.filter(user=self.request.user)

    def get_object(self):
        obj = super().get_object()
        return obj

    def create(self, request, *args, **kwargs):
        reagent_action = ReagentAction()

        reagent = StoredReagent.objects.get(id=request.data['reagent'])
        permission = self._get_user_permission(reagent, self.request.user)
        if not permission["edit"]:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        reagent_action.user = self.request.user
        reagent_action.reagent = reagent
        reagent_action.action_type = request.data['action_type']
        reagent_action.quantity = request.data['quantity']
        reagent_action.notes = request.data['notes']
        if "step_reagent" in request.data:
            step_reagent = StepReagent.objects.get(id=request.data['step_reagent'])
            reagent_action.step_reagent = step_reagent
        if "session" in request.data:
            session = Session.objects.get(unique_id=request.data['session'])
            reagent_action.session = session
        reagent_action.save()
        data = self.get_serializer(reagent_action).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        permission = self._get_user_permission(instance.reagent, self.request.user)
        if not permission["delete"]:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        # check if within 5 minutes of creation then allow delete if not method not allowed
        if (timezone.now() - instance.created_at).seconds > 300:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def get_reagent_action_range(self, request):
        stored_reagent = self.request.query_params.get('reagent', None)
        if not stored_reagent:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        stored_reagent = StoredReagent.objects.get(id=stored_reagent)
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        if not start_date:
            start_date = datetime.now() - timedelta(days=1)
        if not end_date:
            end_date = datetime.now() + timedelta(days=1)
        actions = ReagentAction.objects.filter(reagent=stored_reagent, created_at__range=[start_date, end_date])
        data = ReagentActionSerializer(actions, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    def _get_user_permission(self, stored_reagent, user):
        permission = {
            "edit": False,
            "delete": False
        }
        if user.is_staff:
            permission["edit"] = True
            permission["delete"] = True
            return permission
        if stored_reagent.user == user:
            permission["edit"] = True
            permission["delete"] = True
        elif stored_reagent.shareable:
            if stored_reagent.access_all:
                permission["edit"] = True
            elif user in stored_reagent.access_users.all():
                permission["edit"] = True
            elif user.lab_groups.filter(id__in=stored_reagent.access_lab_groups.all().values_list('id', flat=True)).exists():
                permission["edit"] = True
        return permission

class LabGroupViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = LabGroup.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name']
    filterset_fields = ['name']
    serializer_class = LabGroupSerializer

    def get_queryset(self):
        query = Q()
        stored_reagent_id = self.request.query_params.get('stored_reagent', None)
        is_professional = self.request.query_params.get('is_professional', None)
        if stored_reagent_id:
            stored_reagent = StoredReagent.objects.get(id=stored_reagent_id)
            return stored_reagent.access_lab_groups.all()
        storage_object_id = self.request.query_params.get('storage_object', None)
        if storage_object_id:
            storage_object = StorageObject.objects.get(id=storage_object_id)
            return storage_object.access_lab_groups.all()
        if is_professional:
            is_professional = is_professional == 'true'
            query &= Q(is_professional=is_professional)
        return self.queryset.filter(query)

    def get_object(self):
        obj = super().get_object()
        return obj

    def create(self, request, *args, **kwargs):
        group = LabGroup()
        user = self.request.user
        group.name = request.data['name']
        group.description = request.data['description']
        group.is_professional = request.data['is_professional']
        group.save()
        group.users.add(user)
        data = self.get_serializer(group).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if "name" in request.data:
            instance.name = request.data['name']
        if "description" in request.data:
            instance.description = request.data['description']
        if "default_storage" in request.data:
            instance.default_storage = StorageObject.objects.get(id=request.data['default_storage'])
        if "service_storage" in request.data:
            instance.service_storage = StorageObject.objects.get(id=request.data['service_storage'])
        if "is_professional" in request.data:
            instance.is_professional = request.data['is_professional']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def remove_user(self, request, pk=None):
        group = self.get_object()
        if not self.request.user.is_staff:
            if not group.managers.filter(id=request.data['user']).exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        user = User.objects.get(id=request.data['user'])
        group.users.remove(user)
        data = self.get_serializer(group).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_user(self, request, pk=None):
        group: LabGroup = self.get_object()
        if not self.request.user.is_staff:
            if not group.managers.filter(id=request.data['user']).exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)

        user = User.objects.get(id=request.data['user'])
        group.users.add(user)
        data = self.get_serializer(group).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_users(self, request, pk=None):
        group = self.get_object()
        users = group.users.all()
        data = UserSerializer(users, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_managers(self, request, pk=None):
        group = self.get_object()
        managers = group.managers.all()
        data = UserSerializer(managers, many=True).data
        return Response(data, status=status.HTTP_200_OK)

class SpeciesViewSet(ModelViewSet, FilterMixin):
    serializer_class = SpeciesSerializer
    queryset = Species.objects.all()
    permission_classes = [AllowAny]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SpeciesSearchFilter, OrderingFilter]
    ordering_fields = ['id', 'taxon', 'official_name', 'code', 'common_name', 'synonym']
    filterset_fields = ['taxon', 'official_name', 'code', 'common_name', 'synonym']
    search_fields = ['^common_name', '^official_name']

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        name = request.data['name']
        species = Species.objects.create(name=name)
        data = SpeciesSerializer(species).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        species = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if 'name' in request.data:
            species.name = request.data['name']
        species.save()
        return Response(SpeciesSerializer(species).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        species = self.get_object()
        species.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class SubcellularLocationViewSet(ModelViewSet, FilterMixin):
    serializer_class = SubcellularLocationSerializer
    queryset = SubcellularLocation.objects.all()
    permission_classes = [AllowAny]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SubcellularLocationSearchFilter, OrderingFilter]
    ordering_fields = ['location_identifier', 'synonyms']
    search_fields = ['^location_identifier', '^synonyms']

    def get_queryset(self):
        return super().get_queryset()

class TissueViewSet(ModelViewSet, FilterMixin):
    serializer_class = TissueSerializer
    queryset = Tissue.objects.all()
    permission_classes = [AllowAny]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, TissueSearchFilter, OrderingFilter]
    ordering_fields = ['identifier', 'synonyms']
    search_fields = ['^identifier', '^synonyms']

    def get_queryset(self):
        return super().get_queryset()


class HumanDiseaseViewSet(ModelViewSet, FilterMixin):
    serializer_class = HumanDiseaseSerializer
    queryset = HumanDisease.objects.all()
    permission_classes = [AllowAny]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, HumanDiseaseSearchFilter, OrderingFilter]
    ordering_fields = ['identifier', 'synonyms']
    search_fields = ['^identifier', '^synonyms', '^acronym']

    def get_queryset(self):
        return super().get_queryset()


class MetadataColumnViewSet(FilterMixin, ModelViewSet):
    serializer_class = MetadataColumnSerializer
    queryset = MetadataColumn.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    search_fields = ['name']

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        if "parent_id" not in request.data and "parent_type" not in request.data:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        parent_object = None
        if request.data['parent_type'] == 'stored_reagent':
            parent_object = StoredReagent.objects.get(id=request.data['parent_id'])
            if parent_object.user != request.user:
                if not request.user.is_staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
            metadata_column_data = {
                'stored_reagent': parent_object,
                'name': request.data.get('name'),
                'type': request.data.get('type'),
                'value': request.data.get('value')
            }
            metadata_columns = MetadataColumn.objects.filter(stored_reagent=parent_object)
            # get the last position in the metadata columns group by checking all the metadata columns of the stored_reagent
        elif request.data['parent_type'] == 'instrument':
            parent_object = Instrument.objects.get(id=request.data['parent_id'])
            instrument_permission = InstrumentPermission.objects.filter(instrument=parent_object, user=request.user)
            if not request.user.is_staff:
                if not instrument_permission.exists():
                    return Response(status=status.HTTP_403_FORBIDDEN)
                if not instrument_permission.first().can_manage:
                    return Response(status=status.HTTP_403_FORBIDDEN)
            metadata_column_data = {
                'instrument': parent_object,
                'name': request.data.get('name'),
                'type': request.data.get('type'),
                'value': request.data.get('value')
            }
            metadata_columns = MetadataColumn.objects.filter(instrument=parent_object)
        elif request.data['parent_type'] == 'annotation':
            parent_object = Annotation.objects.get(id=request.data['parent_id'])
            if parent_object.user != request.user:
                if not request.user.is_staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
            metadata_column_data = {
                'annotation': parent_object,
                'name': request.data.get('name'),
                'type': request.data.get('type'),
                'value': request.data.get('value')
            }
            metadata_columns = MetadataColumn.objects.filter(annotation=parent_object)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)


        if metadata_columns.exists():
            position = metadata_columns.aggregate(Max('column_position'))['column_position__max'] + 1
        else:
            position = 0

        metadata_column_data["column_position"] = position
        metadata_column = MetadataColumn.objects.create(**metadata_column_data)
        return Response(MetadataColumnSerializer(metadata_column).data, status=status.HTTP_201_CREATED)


    def update(self, request, *args, **kwargs):
        metadata_column = self.get_object()
        fields = ['name', 'description', 'value', 'not_applicable']
        for i in request.data:
            if i in fields:
                setattr(metadata_column, i, request.data[i])
        metadata_column.save()

        return Response(MetadataColumnSerializer(metadata_column).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        metadata_column: MetadataColumn = self.get_object()
        if metadata_column.stored_reagent:
            if metadata_column.stored_reagent.user != request.user:
                if not request.user.is_staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
        elif metadata_column.instrument:
            instrument_permission = InstrumentPermission.objects.filter(instrument=metadata_column.instrument, user=request.user)
            if not request.user.is_staff:
                if not instrument_permission.exists():
                    return Response(status=status.HTTP_403_FORBIDDEN)
                if not instrument_permission.first().can_manage:
                    return Response(status=status.HTTP_403_FORBIDDEN)
        elif metadata_column.annotation:
            if metadata_column.annotation.user != request.user:
                if not request.user.is_staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
        metadata_column.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class MSUniqueVocabulariesViewSet(FilterMixin, ModelViewSet):
    serializer_class = MSUniqueVocabulariesSerializer
    queryset = MSUniqueVocabularies.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, MSUniqueVocabulariesSearchFilter, OrderingFilter]
    ordering_fields = ['accession', 'name']
    search_fields = ['^name']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        term_type = self.request.query_params.get('term_type', None)
        if term_type:
            result = self.queryset.filter(term_type__iexact=term_type)
            return result
        return self.queryset

    def create(self, request, *args, **kwargs):
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        accession = request.data['accession']
        name = request.data['name']
        vocabulary = MSUniqueVocabularies.objects.create(accession=accession, name=name)
        data = MSUniqueVocabulariesSerializer(vocabulary).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        vocabulary = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if 'accession' in request.data:
            vocabulary.accession = request.data['accession']
        if 'name' in request.data:
            vocabulary.name = request.data['name']
        vocabulary.save()
        return Response(MSUniqueVocabulariesSerializer(vocabulary).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        vocabulary = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        vocabulary.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class UnimodViewSets(FilterMixin, ModelViewSet):
    serializer_class = UnimodSerializer
    queryset = Unimod.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, UnimodSearchFilter, OrderingFilter]
    filterset_class = UnimodFilter
    ordering_fields = ['accession', 'name']
    search_fields = ['^name', '^definition','^accession']
    pagination_class = LimitOffsetPagination


    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        accession = request.data['accession']
        name = request.data['name']
        unimod = Unimod.objects.create(accession=accession, name=name)
        data = UnimodSerializer(unimod).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        unimod = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if 'accession' in request.data:
            unimod.accession = request.data['accession']
        if 'name' in request.data:
            unimod.name = request.data['name']
        unimod.save()
        return Response(UnimodSerializer(unimod).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        unimod = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        unimod.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class InstrumentJobViewSets(FilterMixin, ModelViewSet):
    serializer_class = InstrumentJobSerializer
    queryset = InstrumentJob.objects.all()

    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'job_name', 'created_at']
    search_fields = ['job_name']

    def get_queryset(self):
        user = self.request.user
        query = Q()
        mode = self.request.query_params.get('mode', None)
        lab_group = self.request.query_params.get('lab_group', None)
        funder = self.request.query_params.get('funder', None)
        cost_center = self.request.query_params.get('cost_center', None)
        search_engine = self.request.query_params.get('search_engine', None)
        search_engine_version = self.request.query_params.get('search_engine_version', None)

        if mode == 'staff':
            query &= Q(staff=user)
        elif mode == 'service_lab_group':
            lab_group = LabGroup.objects.get(id=lab_group)
            query &= Q(service_lab_group=lab_group)
        elif mode == 'lab_group':
            lab_group = LabGroup.objects.get(id=lab_group)
            users = lab_group.users.all()
            query &= Q(user__in=users)
        else:
            query &= Q(user=user)
        status = self.request.query_params.get('status', None)
        if status:
            query &= Q(status=status)
        if funder:
            query &= Q(funder=funder)
        if cost_center:
            query &= Q(cost_center=cost_center)
        if search_engine:
            query &= Q(search_engine=search_engine)
        if search_engine_version:
            query &= Q(search_engine_version=search_engine_version)
        if mode != 'service_lab_group' and mode != 'lab_group':
            query &= ~Q(status='draft') | Q(user=user)

        return self.queryset.filter(query)


    def create(self, request, *args, **kwargs):
        name = request.data['job_name']

        instrument_job: InstrumentJob = InstrumentJob(
            job_name=name,
            user=self.request.user
        )
        if 'instrument' in request.data:
            instrument = Instrument.objects.get(id=request.data['instrument'])
            instrument_job.instrument = instrument
        if 'staff' in request.data:
            staff = User.objects.get(username=request.data['staff'])
            instrument_job.staff = staff
            instrument_job.assigned = True
        if 'project' in request.data:
            project = Project.objects.get(id=request.data['project'])
            instrument_job.project = project

        instrument_job.save()
        for metadata in user_metadata:
            metadata_column = MetadataColumn(
                name=metadata['name'],
                type=metadata['type'],
                mandatory=metadata['mandatory'],
            )
            if 'value' in metadata:
                metadata_column.value = metadata['value']
            metadata_column.save()
            instrument_job.user_metadata.add(metadata_column)

        for metadata in staff_metadata:
            metadata_column = MetadataColumn.objects.create(
                name=metadata['name'],
                type=metadata['type'],
                mandatory=metadata['mandatory'],
            )
            instrument_job.staff_metadata.add(metadata_column)

        data = InstrumentJobSerializer(instrument_job).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instrument_job = self.get_object()
        is_staff = False
        if not self.request.user.is_staff:
            if instrument_job.user != self.request.user:
                staff = instrument_job.staff.all()
                if staff.count() == 0:
                    if instrument_job.service_lab_group:
                        staff = instrument_job.service_lab_group.users.all()
                        if self.request.user not in staff:
                            return Response(status=status.HTTP_403_FORBIDDEN)
                        else:
                            is_staff = True
                else:
                    if self.request.user not in staff:
                        return Response(status=status.HTTP_403_FORBIDDEN)
                    else:
                        is_staff = True
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        else:
            is_staff = True
        if instrument_job.status != 'draft' and not is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)

        using = []
        old_sample_number = instrument_job.sample_number
        new_sample_number = instrument_job.sample_number
        if 'job_name' in request.data:
            instrument_job.job_name = request.data['job_name']
            using.append('job_name')
        if 'instrument' in request.data:
            instrument = Instrument.objects.get(id=request.data['instrument'])
            instrument_job.instrument = instrument
            using.append('instrument')
        if 'staff' in request.data:
            if len(request.data['staff']) > 0:
                staffs = User.objects.filter(id__in=request.data['staff'])
                instrument_job.staff.clear()
                instrument_job.staff.add(*staffs)
                instrument_job.assigned = True
            else:
                instrument_job.staff.clear()
                instrument_job.assigned = False
            using.append('assigned')
        if 'project' in request.data:
            project = Project.objects.get(id=request.data['project'])
            if not instrument_job.project:
                instrument_job.project = project
            elif instrument_job.project != project:
                instrument_job.project = project
            using.append('project')
        if 'cost_center' in request.data:
            instrument_job.cost_center = request.data['cost_center']
            using.append('cost_center')
        if 'funder' in request.data:
            instrument_job.funder = request.data['funder']
            using.append('funder')
        if 'sample_type' in request.data:
            instrument_job.sample_type = request.data['sample_type']
            using.append('sample_type')
        if 'sample_number' in request.data:
            instrument_job.sample_number = request.data['sample_number']
            new_sample_number = instrument_job.sample_number
            using.append('sample_number')

        if 'stored_reagent' in request.data:
            stored_reagent = StoredReagent.objects.get(id=request.data['stored_reagent'])
            instrument_job.stored_reagent = stored_reagent
            using.append('stored_reagent')
        if 'service_lab_group' in request.data:
            service_lab_group = LabGroup.objects.get(id=request.data['service_lab_group'])
            instrument_job.service_lab_group = service_lab_group
            using.append('service_lab_group')
        if 'user_metadata' in request.data:
            user_metadata = request.data['user_metadata']
            instrument_job.user_metadata.clear()
            for metadata in user_metadata:
                if 'id' in metadata:
                    if metadata['id']:
                        metadata_column = MetadataColumn.objects.get(id=metadata['id'])
                        if metadata_column.name == "Assay name":
                            if old_sample_number and new_sample_number:
                                if metadata_column.auto_generated and old_sample_number != new_sample_number:
                                    # genereated modifiers for each sample index with the run number i.e run 1, run 2, run 3,...
                                    modifiers = []
                                    for i in range(1, new_sample_number + 1):
                                        modifiers.append({'samples': str(i), 'value': f'run {i}'})
                                    metadata_column.modifiers = json.dumps(modifiers)
                                else:
                                    metadata_column.modifiers = json.dumps(metadata['modifiers'])
                                    metadata_column.value = metadata['value']
                            else:
                                metadata_column.modifiers = json.dumps(metadata['modifiers'])
                                metadata_column.value = metadata['value']
                        else:
                            if is_staff:
                                if metadata_column.hidden != metadata['hidden']:
                                    metadata_column.hidden = metadata['hidden']
                                if metadata_column.readonly != metadata['readonly']:
                                    metadata_column.readonly = metadata['readonly']
                                metadata_column.save()
                            if metadata_column.value != metadata['value'] or metadata_column.modifiers != json.dumps(metadata['modifiers']):
                                metadata_column.value = metadata['value']
                                metadata_column.modifiers = json.dumps(metadata['modifiers'])

                                metadata_column.save()
                        instrument_job.user_metadata.add(metadata_column)
                    else:
                        if 'modifiers' not in metadata:
                            metadata['modifiers'] = []
                        metadata_column = MetadataColumn.objects.create(
                            name=metadata['name'],
                            type=metadata['type'],
                            value=metadata['value'],
                            modifiers=json.dumps(metadata['modifiers']),
                            mandatory=metadata['mandatory'],
                            #hidden=metadata['hidden'],
                            #readonly=metadata['readonly'],
                        )
                        instrument_job.user_metadata.add(metadata_column)
                else:
                    metadata_column = MetadataColumn.objects.create(
                        name=metadata['name'],
                        type=metadata['type'],
                        value=metadata['value'],
                        mandatory=metadata['mandatory'],
                        modifiers=json.dumps(metadata['modifiers']),
                        #hidden=metadata['hidden'],
                        #readonly=metadata['readonly'],
                    )
                    instrument_job.user_metadata.add(metadata_column)

        instrument_job.save(update_fields=using)
        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def update_staff_data(self, request, pk=None):
        instrument_job = self.get_object()
        staffs = instrument_job.staff.all()
        if not request.user.is_staff:
            if staffs.count() == 0:
                if instrument_job.service_lab_group:
                    staffs = instrument_job.service_lab_group.users.all()
                    if request.user not in staffs:
                        return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                if request.user not in staffs:
                    return Response(status=status.HTTP_403_FORBIDDEN)
        using = []
        if 'staff_metadata' in request.data:
            staff_metadata = request.data['staff_metadata']
            instrument_job.staff_metadata.clear()
            for metadata in staff_metadata:
                if 'id' in metadata:
                    if metadata['id']:
                        metadata_column = MetadataColumn.objects.get(id=metadata['id'])
                        if metadata_column.hidden != metadata['hidden']:
                            metadata_column.hidden = metadata['hidden']
                            metadata_column.save()
                        if metadata_column.readonly != metadata['readonly']:
                            metadata_column.readonly = metadata['readonly']
                            metadata_column.save()
                        if metadata_column.value != metadata['value'] or metadata_column.modifiers != json.dumps(metadata['modifiers']):
                            metadata_column.value = metadata['value']
                            metadata_column.modifiers = json.dumps(metadata['modifiers'])

                            metadata_column.save()
                        instrument_job.staff_metadata.add(metadata_column)
                    else:
                        if 'modifiers' not in metadata:
                            metadata['modifiers'] = []
                        metadata_column = MetadataColumn.objects.create(
                            name=metadata['name'],
                            type=metadata['type'],
                            value=metadata['value'],
                            mandatory=metadata['mandatory'],
                            modifiers=json.dumps(metadata['modifiers']),
                        )
                        instrument_job.staff_metadata.add(metadata_column)
                else:
                    metadata_column = MetadataColumn.objects.create(
                        name=metadata['name'],
                        type=metadata['type'],
                        value=metadata['value'],
                        mandatory=metadata['mandatory'],
                        modifiers=json.dumps(metadata['modifiers']),
                    )
                    instrument_job.staff_metadata.add(metadata_column)
        if 'protocol' in request.data:
            protocol = ProtocolModel.objects.get(id=request.data['protocol'])

            if not instrument_job.protocol:
                instrument_job.protocol = protocol
            elif instrument_job.protocol != protocol:
                instrument_job.protocol = protocol
            using.append('protocol')
        if 'search_engine' in request.data:
            instrument_job.search_engine = request.data['search_engine']
            using.append('search_engine')
        if 'search_engine_version' in request.data:
            instrument_job.search_engine_version = request.data['search_engine_version']
            using.append('search_engine_version')
        if 'search_details' in request.data:
            instrument_job.search_details = request.data['search_details']
            using.append('search_details')
        if 'location' in request.data:
            instrument_job.location = request.data['location']
            using.append('location')
        if 'injection_volume' in request.data:
            instrument_job.injection_volume = request.data['injection_volume']
            using.append('injection_volume')
        if 'injection_unit' in request.data:
            instrument_job.injection_unit = request.data['injection_unit']
            using.append('injection_unit')
        instrument_job.save(update_fields=using)
        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        instrument_job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def set_project(self, request, pk=None):
        instrument_job = self.get_object()
        project = Project.objects.get(id=request.data['project'])
        instrument_job.project = project
        instrument_job.save()
        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def submit_job(self, request, pk=None):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if instrument_job.status != 'draft':
            return Response(status=status.HTTP_400_BAD_REQUEST)
        instrument_job.status = 'submitted'
        instrument_job.submitted_at = timezone.now()
        instrument_job.save()
        if settings.NOTIFICATION_EMAIL_FROM:
            staff = instrument_job.staff.all()
            subject = 'Instrument Job Submitted'
            message = f'Instrument Job {instrument_job.job_name} {settings.FRONTEND_URL}/#/instruments/{instrument_job.id} has been submitted by {instrument_job.user.username}'
            recipient_list = [staff.email for staff in staff if staff.email]
            if recipient_list:
                send_mail(subject, message, settings.NOTIFICATION_EMAIL_FROM, recipient_list)


        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def individual_field_typeahead(self, request):
        field_name = request.query_params.get('field_name', None)
        if field_name in ['cost_center', 'funder']:
            paginator = LimitOffsetPagination()
            paginator.default_limit = 10
            search_query = request.query_params.get('search', None)
            if field_name == 'cost_center' and search_query:
                queryset = InstrumentJob.objects.filter(
                    Q(cost_center__icontains=search_query)
                ).values_list('cost_center', flat=True).distinct().order_by('cost_center')
            elif field_name == 'funder' and search_query:
                queryset = InstrumentJob.objects.filter(
                    Q(funder__icontains=search_query)
                ).values_list('funder', flat=True).distinct().order_by('funder')
            page = paginator.paginate_queryset(queryset, request)
            return paginator.get_paginated_response(page)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)


    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            staff = instrument_job.staff.all()
            if staff.count() == 0:
                if instrument_job.service_lab_group:
                    staff = instrument_job.service_lab_group.users.all()
                    if self.request.user not in staff:
                        return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                if self.request.user not in staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
        status = request.data['status']
        instrument_job.status = status
        if status == 'completed':
            instrument_job.completed_at = timezone.now()
        instrument_job.save()
        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def export_metadata_to_tsv(self, request, pk=None):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            staff = instrument_job.staff.all()
            if staff.count() == 0:
                if instrument_job.service_lab_group:
                    staff = instrument_job.service_lab_group.users.all()
                    if self.request.user not in staff:
                        return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                if self.request.user not in staff:
                    if instrument_job.user != self.request.user:
                        return Response(status=status.HTTP_403_FORBIDDEN)

        job = export_instrument_job_metadata.delay(instrument_job.id, request.data["data_type"], request.user.id, request.data["instance_id"])
        return Response({"task_id": job.id}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def import_sdrf_metadata(self, request, pk=None):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            staff = instrument_job.staff.all()
            if staff.count() == 0:
                if instrument_job.service_lab_group:
                    staff = instrument_job.service_lab_group.users.all()
                    if self.request.user not in staff:
                        return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                if self.request.user not in staff:
                    if instrument_job.user != self.request.user:
                        return Response(status=status.HTTP_403_FORBIDDEN)
                    else:
                        if request.data["data_type"] != 'user_metadata':
                            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.data["data_type"].endswith('excel'):
            job = import_excel.delay(request.data["annotation"], request.user.id, instrument_job.id,  request.data["instance_id"], request.data["data_type"].replace("_excel", ""))
        else:
            job = import_sdrf_file.delay(request.data["annotation"], request.user.id, instrument_job.id, request.data["instance_id"], request.data["data_type"])

        return Response({"task_id": job.id}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def validate_sdrf_metadata(self, request, pk=None):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            staff = instrument_job.staff.all()
            if staff.count() == 0:
                if instrument_job.service_lab_group:
                    staff = instrument_job.service_lab_group.users.all()
                    if self.request.user not in staff:
                        return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                if self.request.user not in staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
        # get id of metadata column objects from instrument_job.user_metadata and instrument_job.staff_metadata
        user_metadata = instrument_job.user_metadata.all()
        staff_metadata = instrument_job.staff_metadata.all()
        user_metadata_ids = [metadata.id for metadata in user_metadata]
        staff_metadata_ids = [metadata.id for metadata in staff_metadata]
        job = validate_sdrf_file.delay(user_metadata_ids+staff_metadata_ids, instrument_job.sample_number, request.user.id, request.data['instance_id'])
        return Response({"task_id": job.id}, status=status.HTTP_200_OK)


    @action(detail=True, methods=['post'])
    def export_excel_template(self, request, pk=None):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            staff = instrument_job.staff.all()
            if staff.count() == 0:
                if instrument_job.service_lab_group:
                    staff = instrument_job.service_lab_group.users.all()
                    if self.request.user not in staff:
                        return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                if self.request.user not in staff:
                    if instrument_job.user != self.request.user:
                        return Response(status=status.HTTP_403_FORBIDDEN)
                    else:
                        if request.data["export_type"] != 'user_metadata':
                            return Response(status=status.HTTP_403_FORBIDDEN)
        job = export_excel_template.delay(request.user.id, request.data["instance_id"], instrument_job.id, request.data["export_type"])
        return Response({"task_id": job.id}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def selected_template(self, request, pk=None):
        instrument_job = self.get_object()
        # if not self.request.user.is_staff:
        #     staff = instrument_job.staff.all()
        #     if staff.count() == 0:
        #         if instrument_job.service_lab_group:
        #             staff = instrument_job.service_lab_group.users.all()
        #             if self.request.user not in staff:
        #                 return Response(status=status.HTTP_403_FORBIDDEN)
        #     else:
        #         if self.request.user not in staff:
        #             return Response(status=status.HTTP_403_FORBIDDEN)
        template = request.data['template']
        metadata_template = MetadataTableTemplate.objects.get(id=template)
        for metadata in instrument_job.user_metadata.all():
            metadata.delete()
        for metadata in metadata_template.user_columns.all():
            m = MetadataColumn(
                name=metadata.name,
                type=metadata.type,
                value=metadata.value,
                mandatory=metadata.mandatory,
                column_position=metadata.column_position,
                hidden=metadata.hidden,
                auto_generated=metadata.auto_generated,
                readonly=metadata.readonly,
            )
            if m.name == "Assay name" and m.auto_generated:
                modifiers = []
                for i in range(1, instrument_job.sample_number + 1):
                    modifiers.append({'samples': str(i), 'value': f'run {i}'})
                m.modifiers = json.dumps(modifiers)
            m.save()
            instrument_job.user_metadata.add(m)
        for metadata in instrument_job.staff_metadata.all():
            metadata.delete()
        for metadata in metadata_template.staff_columns.all():
            m = MetadataColumn(
                name=metadata.name,
                type=metadata.type,
                value=metadata.value,
                mandatory=metadata.mandatory,
                column_position=metadata.column_position,
                hidden=metadata.hidden,
                auto_generated=metadata.auto_generated,
                readonly=metadata.readonly,
            )
            m.save()
            instrument_job.staff_metadata.add(m)
        instrument_job.selected_template = metadata_template
        instrument_job.save()
        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_selected_template(self, request, pk=None):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            staff = instrument_job.staff.all()
            if staff.count() == 0:
                if instrument_job.service_lab_group:
                    staff = instrument_job.service_lab_group.users.all()
                    if self.request.user not in staff:
                        return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                if self.request.user not in staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
        for metadata in instrument_job.user_metadata.all():
            metadata.delete()
        for metadata in instrument_job.staff_metadata.all():
            metadata.delete()
        instrument_job.selected_template = None
        instrument_job.save()
        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def copy_metadata_from_protocol(self, request, pk=None):
        instrument_job = self.get_object()
        if not self.request.user.is_staff:
            staff = instrument_job.staff.all()
            if staff.count() == 0:
                if instrument_job.service_lab_group:
                    staff = instrument_job.service_lab_group.users.all()
                    if self.request.user not in staff:
                        return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                if self.request.user not in staff:
                    return Response(status=status.HTTP_403_FORBIDDEN)
        protocol = instrument_job.protocol
        metadata_ids = request.data['metadata_ids']
        metadata_columns = list(protocol.metadata_columns.filter(id__in=metadata_ids))
        # step through job user_metadata to see if there is one with the same type and name. If there is, update the value with one from the protocol then pop the metadata from the list
        used_metadata = {}
        for metadata in instrument_job.user_metadata.all():
            for protocol_metadata in metadata_columns:
                if metadata not in used_metadata:
                    if metadata.name == protocol_metadata.name and metadata.type == protocol_metadata.type:
                        metadata.value = protocol_metadata.value
                        metadata.save()
                        used_metadata[metadata.id] = metadata
        # remove the used metadata from the python array list not the database
        new_columns = []
        for metadata in metadata_columns:
            if metadata.id not in used_metadata:
                new_columns.append(metadata)

        if new_columns:
            # step through job staff_metadata to see if there is one with the same type and name. If there is, update the value with one from the protocol then pop the metadata from the list
            used_metadata = {}
            for metadata in instrument_job.staff_metadata.all():
                for protocol_metadata in new_columns:
                    if metadata not in used_metadata:
                        if metadata.name == protocol_metadata.name and metadata.type == protocol_metadata.type:
                            metadata.value = protocol_metadata.value
                            metadata.save()
                            used_metadata[metadata.id] = metadata

            # remove the used metadata from the python array list not the database
            for metadata in new_columns:
                if metadata.id not in used_metadata:
                    metadata_column = MetadataColumn.objects.create(
                        name=metadata.name,
                        type=metadata.type,
                        value=metadata.value,
                        mandatory=metadata.mandatory,
                        column_position=metadata.column_position,
                        hidden=metadata.hidden,
                        auto_generated=metadata.auto_generated,
                        readonly=metadata.readonly,
                    )
                    instrument_job.staff_metadata.add(metadata_column)

        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

class FavouriteMetadataOptionViewSets(FilterMixin, ModelViewSet):
    serializer_class = FavouriteMetadataOptionSerializer
    queryset = FavouriteMetadataOption.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    search_fields = ['value', 'display_value']

    def get_queryset(self):
        user = self.request.user
        mode = self.request.query_params.get('mode', None)
        metadata_name = self.request.query_params.get('name', None)
        lab_group = self.request.query_params.get('lab_group_id', None)
        user_id = self.request.query_params.get('user_id', None)
        get_global = self.request.query_params.get('get_global', 'false')

        query = Q()
        if get_global != 'true':
            if mode == 'service_lab_group' and lab_group:
                lab_group = LabGroup.objects.get(id=lab_group, is_professional=True)
                query &= Q(service_lab_group=lab_group)
            elif mode == 'lab_group' and lab_group:
                lab_group = LabGroup.objects.get(id=lab_group)
                query &= Q(lab_group=lab_group)
            elif mode == 'user':
                query &= Q(user=user, lab_group__isnull=True, service_lab_group__isnull=True)
            else:
                query &= Q(user=user)
        else:
            query &= Q(is_global=True)
        if metadata_name:
            query &= Q(name=metadata_name)
        return self.queryset.filter(query)

    def create(self, request, *args, **kwargs):
        user = self.request.user
        mode = request.data.get('mode', None)
        lab_group = request.data.get('lab_group', None)
        metadata_name = request.data.get('name', None)
        metadata_type = request.data.get('type', None)
        value = request.data.get('value', None)
        display_name = request.data.get('display_name', None)
        preset = request.data.get('preset', None)
        is_global = request.data.get('is_global', False)
        if not request.user.is_staff and is_global:
            return Response(status=status.HTTP_403_FORBIDDEN)

        if is_global:
            # check if there is already the same display_name
            if FavouriteMetadataOption.objects.filter(display_value=display_name, is_global=True).exists():
                return Response(status=status.HTTP_409_CONFLICT)

        if preset:
            preset = Preset.objects.get(id=preset)
        if mode == 'service_lab_group':

            lab_group = LabGroup.objects.get(id=lab_group, is_professional=True)
            if not lab_group.users.filter(id=user.id).exists():
                return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                option = FavouriteMetadataOption.objects.create(name=metadata_name, type=metadata_type, value=value, display_value=display_name, service_lab_group=lab_group, preset=preset, user=user, is_global=is_global)
        elif mode == 'lab_group':
            lab_group = LabGroup.objects.get(id=lab_group)
            if not lab_group.users.filter(id=user.id).exists():
                return Response(status=status.HTTP_403_FORBIDDEN)
            else:
                option = FavouriteMetadataOption.objects.create(name=metadata_name, type=metadata_type, value=value, display_value=display_name, lab_group=lab_group, preset=preset, user=user, is_global=is_global)
        else:
            option = FavouriteMetadataOption.objects.create(name=metadata_name, type=metadata_type, value=value, display_value=display_name, user=user, preset=preset, is_global=is_global)

        return Response(FavouriteMetadataOptionSerializer(option).data, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not request.user.is_staff:
            if instance.service_lab_group:
                if not instance.service_lab_group.users.filter(id=request.user.id).exists():
                    return Response(status=status.HTTP_403_FORBIDDEN)
            elif instance.lab_group:
                if not instance.lab_group.users.filter(id=request.user.id).exists():
                    return Response(status=status.HTTP_403_FORBIDDEN)
            elif instance.user != request.user:
                return Response(status=status.HTTP_403_FORBIDDEN)

        if 'value' in request.data:
            instance.value = request.data['value']
        if 'display_value' in request.data:
            instance.display_value = request.data['display_value']
        if 'is_global' in request.data:
            if request.user.is_staff:
                if instance.is_global != request.data['is_global'] and request.data['is_global']:
                    if FavouriteMetadataOption.objects.filter(display_value=instance.display_value, is_global=True).exists():
                        return Response(status=status.HTTP_409_CONFLICT)
                instance.is_global = request.data['is_global']
        instance.save()

        return Response(FavouriteMetadataOptionSerializer(instance).data, status=status.HTTP_200_OK)


    def destroy(self, request, *args, **kwargs):
        option = FavouriteMetadataOption.objects.get(id=kwargs['pk'])
        if option.service_lab_group:
            if not option.service_lab_group.users.filter(id=request.user.id).exists():
                return Response(status=status.HTTP_403_FORBIDDEN)
        elif option.lab_group:
            if not option.lab_group.users.filter(id=request.user.id).exists():
                return Response(status=status.HTTP_403_FORBIDDEN)
        elif option.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        else:
            if not request.user.is_staff:
                return Response(status=status.HTTP_403_FORBIDDEN)
        option.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PresetViewSet(ModelViewSet):
    serializer_class = PresetSerializer
    queryset = Preset.objects.all()
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    search_fields = ['name']

    def get_queryset(self):
        user = self.request.user
        query = Q()
        if not user.is_staff:
            query &= Q(user=user)
        return self.queryset.filter(query)

    def create(self, request, *args, **kwargs):
        user = self.request.user
        name = request.data['name']
        preset = Preset.objects.create(name=name, user=user)
        return Response(PresetSerializer(preset).data, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        preset = self.get_object()
        if preset.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        preset.name = request.data['name']
        preset.save()
        return Response(PresetSerializer(preset).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        preset = self.get_object()
        if preset.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        preset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MetadataTableTemplateViewSets(FilterMixin, ModelViewSet):
    queryset = MetadataTableTemplate.objects.all()
    serializer_class = MetadataTableTemplateSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    search_fields = ['name']

    def get_queryset(self):
        user = self.request.user
        query = Q()
        mode = self.request.query_params.get('mode', 'user')
        self_only = self.request.query_params.get('self_only', 'false')
        self_only = self_only.lower() == 'true'

        if mode == 'user':
            query &= Q(user=user, lab_group__isnull=True, service_lab_group__isnull=True)
        elif mode == 'service_lab_group':
            lab_group_id = self.request.query_params.get('lab_group_id', None)
            if lab_group_id:
                lab_group = LabGroup.objects.get(id=lab_group_id, is_professional=True)
                query &= Q(service_lab_group=lab_group)
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)
        else:
            if not user.is_staff:
                return Response(status=status.HTTP_403_FORBIDDEN)
        # add filter for only enabled templates that if not enabled will only be accessible by the user who created them
        # query &= (Q(enabled=True)|Q(user=user))
        if self_only and user.is_authenticated:
            query &= Q(user=user)
        return self.queryset.filter(query)

    def create(self, request, *args, **kwargs):
        user = self.request.user
        mode = request.data.get('mode', 'user')
        name = request.data['name']
        made_default = request.data.get('make_default', False)
        user_columns = []
        staff_columns = []
        if made_default:
            for column in user_metadata:
                m = MetadataColumn(name=column['name'], type=column['type'])
                if 'value' in column:
                    m.value = column['value']
                if 'auto_generated' in column:
                    m.auto_generated = column['auto_generated']
                if 'hidden' in column:
                    m.hidden = column['hidden']
                if 'readonly' in column:
                    m.readonly = column['readonly']
                m.save()
                user_columns.append(m)
            for column in staff_metadata:
                m = MetadataColumn(name=column['name'], type=column['type'])
                if 'value' in column:
                    m.value = column['value']
                if 'auto_generated' in column:
                    m.auto_generated = column['auto_generated']
                if 'hidden' in column:
                    m.hidden = column['hidden']
                if 'readonly' in column:
                    m.readonly = column['readonly']
                m.save()
                staff_columns.append(m)
        default_mask_mapping = [
            {
                "name": "Organism part",
                "mask": "Tissue"
            },
            {
                "name": "Cleavage agent details",
                "mask": "Protease"
            }
        ]
        template = MetadataTableTemplate.objects.create(name=name, user=user, field_mask_mapping=default_mask_mapping)
        template.user_columns.add(*user_columns)
        template.staff_columns.add(*staff_columns)
        if mode == 'service_lab_group':
            lab_group_id = request.data.get('lab_group', None)
            if lab_group_id:
                lab_group = LabGroup.objects.get(id=lab_group_id, is_professional=True)
                template.service_lab_group = lab_group
                template.save()
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)
        return Response(MetadataTableTemplateSerializer(template).data, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        template = self.get_object()
        if template.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if "name" in request.data:
            template.name = request.data['name']
        if "user_columns" in request.data:
            columns = request.data['user_columns']
            ids_from_submission = set()
            for c in columns:
                if 'id' in c:
                    if c['id']:
                        ids_from_submission.add(c['id'])
                        column = MetadataColumn.objects.get(id=c['id'])
                        column.name = c['name']
                        column.type = c['type']
                        column.auto_generated = c['auto_generated']
                        column.hidden = c['hidden']
                        column.readonly = c['readonly']
                        column.value = c['value']
                        if column.modifiers:
                            column.modifiers = json.dumps(c['modifiers'])
                        else:
                            column.modifiers = json.dumps([])
                        column.save()

                    else:
                        column = MetadataColumn(
                            name=c['name'],
                            type=c['type'],
                            auto_generated=c['auto_generated'],
                            hidden=c['hidden'],
                            readonly=c['readonly'],
                            value=c['value']
                        )
                        if c['modifiers']:
                            column.modifiers = json.dumps(c['modifiers'])
                        else:
                            column.modifiers = json.dumps([])
                        column.save()
                        ids_from_submission.add(column.id)
                    template.user_columns.add(column)
                else:
                    column = MetadataColumn(
                        name=c['name'],
                        type=c['type'],
                        auto_generated=c['auto_generated'],
                        hidden=c['hidden'],
                        readonly=c['readonly'],
                        value=c['value']
                    )
                    if c['modifiers']:
                        column.modifiers = json.dumps(c['modifiers'])
                    else:
                        column.modifiers = json.dumps([])
                    column.save()
                    template.user_columns.add(column)
            for column in template.user_columns.all():
                if column.id not in ids_from_submission:
                    template.user_columns.remove(column)
                    column.delete()
        if 'staff_columns' in request.data:
            columns = request.data['staff_columns']
            ids_from_submission = set()
            for c in columns:
                if 'id' in c:
                    if c['id']:
                        ids_from_submission.add(c['id'])
                        column = MetadataColumn.objects.get(id=c['id'])
                        column.name = c['name']
                        column.type = c['type']
                        column.auto_generated = c['auto_generated']
                        column.hidden = c['hidden']
                        column.readonly = c['readonly']
                        column.value = c['value']
                        if column.modifiers:
                            column.modifiers = json.dumps(c['modifiers'])
                        else:
                            column.modifiers = json.dumps([])
                        column.save()
                    else:
                        column = MetadataColumn(
                            name=c['name'],
                            type=c['type'],
                            auto_generated=c['auto_generated'],
                            hidden=c['hidden'],
                            readonly=c['readonly'],
                            value=c['value']
                        )
                        if c['modifiers']:
                            column.modifiers = json.dumps(c['modifiers'])
                        else:
                            column.modifiers = json.dumps([])
                        column.save()
                    template.staff_columns.add(column)
                else:
                    column = MetadataColumn(
                        name=c['name'],
                        type=c['type'],
                        auto_generated=c['auto_generated'],
                        hidden=c['hidden'],
                        readonly=c['readonly'],
                        value=c['value']
                    )
                    if c['modifiers']:
                        column.modifiers = json.dumps(c['modifiers'])
                    else:
                        column.modifiers = json.dumps([])
                    column.save()
                    ids_from_submission.add(column.id)
                    template.staff_columns.add(column)
            for column in template.staff_columns.all():
                if column.id not in ids_from_submission:
                    template.staff_columns.remove(column)
                    column.delete()
        if 'field_mask_mapping' in request.data:
            field_mask_mapping = request.data['field_mask_mapping']
            template.field_mask_mapping = json.dumps(field_mask_mapping)
        if 'enabled' in request.data:
            template.enabled = request.data['enabled']
        template.save()
        return Response(MetadataTableTemplateSerializer(template).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        template = self.get_object()
        if template.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        template = self.get_object()
        mode = request.data.get('mode', 'user')
        if mode == 'service_lab_group':
            lab_group_id = request.data.get('lab_group', None)
            if lab_group_id:
                lab_group = LabGroup.objects.get(id=lab_group_id, is_professional=True)
                new_template = MetadataTableTemplate.objects.create(name=template.name, service_lab_group=lab_group, user=request.user)
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)
        elif mode == 'user':
            new_template = MetadataTableTemplate.objects.create(name=template.name, user=request.user)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        for column in template.columns.all():
            new_column = MetadataColumn.objects.create(
                name=column.name,
                type=column.type,
                auto_generated=column.auto_generated,
                hidden=column.hidden,
                readonly=column.readonly,
                modifiers=column.modifiers
            )
            new_template.columns.add(new_column)
        return Response(MetadataTableTemplateSerializer(new_template).data, status=status.HTTP_200_OK)


    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
    def validate_sdrf_metadata(self, request):
        sdrf = request.data['sdrf']
        errors = sdrf_validate(sdrf)
        return Response({"errors": [str(e) for e in errors]}, status=status.HTTP_200_OK)


class MaintenanceLogViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticated]
    queryset = MaintenanceLog.objects.all()
    serializer_class = MaintenanceLogSerializer
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['maintenance_description', 'maintenance_notes']
    ordering_fields = ['maintenance_date', 'updated_at', 'instrument__instrument_name', 'maintenance_type']
    filterset_fields = ['instrument', 'maintenance_type', 'status']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        user = self.request.user
        query = Q()

        instrument_id = self.request.query_params.get('instrument_id', None)
        maintenance_type = self.request.query_params.get('maintenance_type', None)
        status = self.request.query_params.get('status', None)
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        is_template = self.request.query_params.get('is_template', None)

        if instrument_id:
            query &= Q(instrument_id=instrument_id)
        if maintenance_type:
            query &= Q(maintenance_type=maintenance_type)
        if status:
            query &= Q(status=status)
        if start_date:
            query &= Q(maintenance_date__gte=parse_datetime(start_date))
        if end_date:
            query &= Q(maintenance_date__lte=parse_datetime(end_date))
        if is_template is not None:
            query &= Q(is_template=(is_template.lower() == 'true'))
        else:
            query &= Q(is_template=False)

        if not user.is_staff:
            instrument_permissions = InstrumentPermission.objects.filter(user=user)
            if not instrument_permissions.exists():
                return self.queryset.none()

            accessible_instruments = [perm.instrument for perm in instrument_permissions if perm.can_view]
            query &= Q(instrument__in=accessible_instruments)

        return self.queryset.filter(query)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data['created_by'] = request.user.id

        instrument_id = data.get('instrument')
        if instrument_id:
            instrument = Instrument.objects.get(id=instrument_id)
            # Check if user has permission to create maintenance log for this instrument
            if not request.user.is_staff:
                permission = InstrumentPermission.objects.filter(
                    user=request.user, instrument=instrument, can_manage=True
                )
                if not permission.exists():
                    return Response(
                        {"error": "You don't have permission to create maintenance logs for this instrument"},
                        status=status.HTTP_403_FORBIDDEN
                    )

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        maintenance_log = serializer.save()

        maintenance_log.create_default_folders()

        headers = self.get_success_headers(serializer.data)

        if not serializer.data["is_template"] and hasattr(settings, 'SLACK_WEBHOOK_URL') and settings.SLACK_WEBHOOK_URL:
            try:
                instrument_name = Instrument.objects.get(id=instrument_id).instrument_name
                user = request.user.username
                maintenance_type = dict(maintenance_log.maintenance_type_choices).get(maintenance_log.maintenance_type)
                message = f"New {maintenance_type} maintenance log created for {instrument_name} by {user}"
                send_slack_notification(message, settings.SLACK_WEBHOOK_URL)
            except Exception:
                pass

        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        maintenance_log = self.get_object()

        if not request.user.is_staff:
            permission = InstrumentPermission.objects.filter(
                user=request.user, instrument=maintenance_log.instrument, can_manage=True
            )
            if not permission.exists() and maintenance_log.created_by != request.user:
                return Response(
                    {"error": "You don't have permission to update this maintenance log"},
                    status=status.HTTP_403_FORBIDDEN
                )

        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        maintenance_log = self.get_object()

        if not request.user.is_staff:
            permission = InstrumentPermission.objects.filter(
                user=request.user, instrument=maintenance_log.instrument, can_manage=True
            )
            if not permission.exists() and maintenance_log.created_by != request.user:
                return Response(
                    {"error": "You don't have permission to delete this maintenance log"},
                    status=status.HTTP_403_FORBIDDEN
                )

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update the status of a maintenance log"""
        maintenance_log = self.get_object()
        new_status = request.data.get('status')

        if not request.user.is_staff:
            permission = InstrumentPermission.objects.filter(
                user=request.user, instrument=maintenance_log.instrument, can_manage=True
            )
            if not permission.exists() and maintenance_log.created_by != request.user:
                return Response(
                    {"error": "You don't have permission to update the status of this maintenance log"},
                    status=status.HTTP_403_FORBIDDEN
                )

        if new_status not in dict(maintenance_log.status_choices):
            return Response(
                {"error": f"Invalid status. Must be one of: {', '.join(dict(maintenance_log.status_choices).keys())}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        maintenance_log.status = new_status
        maintenance_log.save()
        return Response(self.get_serializer(maintenance_log).data)

    @action(detail=False, methods=['get'])
    def get_maintenance_types(self, request):
        return Response([{'value': key, 'label': value} for key, value in MaintenanceLog.maintenance_type_choices])

    @action(detail=False, methods=['get'])
    def get_status_types(self, request):
        return Response([{'value': key, 'label': value} for key, value in MaintenanceLog.status_choices])

    @action(detail=True, methods=['post'])
    def create_from_template(self, request, pk=None):
        template = self.get_object()

        if not template.is_template:
            return Response(
                {"error": "This is not a template"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not request.user.is_staff:
            permission = InstrumentPermission.objects.filter(
                user=request.user, instrument=template.instrument, can_manage=True
            )
            if not permission.exists():
                return Response(
                    {"error": "You don't have permission to create a maintenance log from this template"},
                    status=status.HTTP_403_FORBIDDEN
                )

        new_log = MaintenanceLog.objects.create(
            instrument=template.instrument,
            maintenance_type=template.maintenance_type,
            maintenance_description=template.maintenance_description,
            maintenance_notes=template.maintenance_notes,
            created_by=request.user,
            status='pending',
            is_template=False
        )

        return Response(self.get_serializer(new_log).data)

    @action(detail=True, methods=['get'])
    def get_annotations(self, request, pk=None):
        """Get all annotations for a maintenance log"""
        maintenance_log = self.get_object()
        if maintenance_log.annotation_folder:
            annotations = maintenance_log.annotation_folder.annotations.all().order_by('-updated_at')
            return Response(AnnotationSerializer(annotations, many=True).data)
        return Response([])

    @action(detail=True, methods=['post'])
    def add_annotation(self, request, pk=None):
        """Add an annotation to the maintenance log"""
        maintenance_log = self.get_object()
        if not request.user.is_staff:
            if maintenance_log.created_by != request.user:
                return Response(
                    {"error": "You don't have permission to add annotations to this maintenance log"},
                    status=status.HTTP_403_FORBIDDEN
                )

        if not maintenance_log.annotation_folder:
            maintenance_log.create_default_folders()
            maintenance_log.refresh_from_db()

        annotation_data = request.data.copy()
        annotation_data['folder'] = maintenance_log.annotation_folder.id

        serializer = AnnotationSerializer(data=annotation_data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def notify_slack(self, request, pk=None):
        maintenance_log = self.get_object()

        if not hasattr(settings, 'SLACK_WEBHOOK_URL') or not settings.SLACK_WEBHOOK_URL:
            return Response({"error": "Slack webhook URL not configured"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        instrument_name = maintenance_log.instrument.instrument_name
        maintenance_type = maintenance_log.get_maintenance_type_display()
        message = request.data.get('message',
                                   f"Maintenance notification: {maintenance_type} maintenance for {instrument_name}")

        success = send_slack_notification(message, settings.SLACK_WEBHOOK_URL)

        if success:
            return Response({"message": "Notification sent successfully"})
        else:
            return Response({"error": "Failed to send notification"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SupportInformationViewSet(ModelViewSet):
    queryset = SupportInformation.objects.all()
    serializer_class = SupportInformationSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'vendor_name', 'manufacturer_name']
    search_fields = ['vendor_name', 'manufacturer_name']
    filterset_fields = ['vendor_name', 'manufacturer_name']
    ordering = ['vendor_name', 'manufacturer_name']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        queryset = self.queryset
        vendor_name = self.request.query_params.get('vendor_name', None)
        manufacturer_name = self.request.query_params.get('manufacturer_name', None)

        if vendor_name:
            queryset = queryset.filter(vendor_name__icontains=vendor_name)
        if manufacturer_name:
            queryset = queryset.filter(manufacturer_name__icontains=manufacturer_name)

        return queryset

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'])
    def add_vendor_contact(self, request, pk=None):
        """Add a vendor contact to support information"""
        support_info = self.get_object()
        serializer = ExternalContactSerializer(data=request.data)

        if serializer.is_valid():
            contact = serializer.save()
            support_info.vendor_contacts.add(contact)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def add_manufacturer_contact(self, request, pk=None):
        """Add a manufacturer contact to support information"""
        support_info = self.get_object()
        serializer = ExternalContactSerializer(data=request.data)

        if serializer.is_valid():
            contact = serializer.save()
            support_info.manufacturer_contacts.add(contact)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'])
    def remove_contact(self, request, pk=None):
        """Remove a contact from support information"""
        support_info = self.get_object()
        contact_id = request.data.get('contact_id')
        contact_type = request.data.get('contact_type', 'vendor')
        try:
            contact = ExternalContact.objects.get(id=contact_id)
            if contact_type == 'vendor':
                support_info.vendor_contacts.remove(contact)
            else:
                support_info.manufacturer_contacts.remove(contact)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ExternalContact.DoesNotExist:
            return Response({"error": "Contact not found"}, status=status.HTTP_404_NOT_FOUND)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class ExternalContactDetailsViewSet(ModelViewSet):
    queryset = ExternalContactDetails.objects.all()
    serializer_class = ExternalContactDetailsSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]


class ExternalContactViewSet(ModelViewSet):
    queryset = ExternalContact.objects.all()
    serializer_class = ExternalContactSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def add_contact_detail(self, request, pk=None):
        contact = self.get_object()
        serializer = ExternalContactDetailsSerializer(data=request.data)

        if serializer.is_valid():
            contact_detail = serializer.save()
            contact.contact_details.add(contact_detail)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'])
    def remove_contact_detail(self, request, pk=None):
        contact = self.get_object()
        detail_id = request.data.get('detail_id')

        try:
            detail = ExternalContactDetails.objects.get(id=detail_id)
            contact.contact_details.remove(detail)
            detail.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ExternalContactDetails.DoesNotExist:
            return Response({"error": "Contact detail not found"}, status=status.HTTP_404_NOT_FOUND)


class MessageThreadViewSet(ModelViewSet):
    serializer_class = MessageThreadSerializer
    permission_classes = [IsAuthenticated, IsParticipantOrAdmin]
    parser_classes = [MultiPartParser, JSONParser]
    queryset = MessageThread.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'created_at', 'updated_at']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        user = self.request.user
        #if user.is_staff and self.request.query_params.get('all') == 'true':
        #    return MessageThread.objects.all()
        message_type = self.request.query_params.get('message_type', None)
        unread_only = self.request.query_params.get('unread', None) == 'true'

        query = Q(participants=user) | Q(lab_group__in=user.lab_groups.all()) | Q(is_system_thread=True, messages__message_type="announcement") | Q(
            creator=user)
        if message_type:
            query &= Q(messages__message_type=message_type)
        if unread_only:
            thread_ids = MessageRecipient.objects.filter(
                user=user,
                is_read=False,
                is_deleted=False
            ).values_list('message__thread', flat=True).distinct()

            query &= Q(id__in=thread_ids)
        return MessageThread.objects.filter(query).distinct()

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return MessageThreadDetailSerializer
        return MessageThreadSerializer

    def create(self, request, *args, **kwargs):
        # Check if this is a reply to an existing thread
        thread_id = request.data.get('thread', None)
        if thread_id:
            try:
                thread = MessageThread.objects.get(id=thread_id)

                # Check if thread is system thread
                if thread.is_system_thread:
                    return Response(
                        {"error": "Cannot reply to system threads"},
                        status=status.HTTP_403_FORBIDDEN
                    )

                # Check if latest message is of a non-replyable type
                latest_message = thread.messages.order_by('-created_at').first()
                if latest_message and latest_message.message_type in ['system_notification', 'alert', 'announcement']:
                    return Response(
                        {"error": f"Cannot reply to {latest_message.message_type} messages"},
                        status=status.HTTP_403_FORBIDDEN
                    )

            except MessageThread.DoesNotExist:
                return Response(
                    {"error": "Thread not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        return super().create(request, *args, **kwargs)

    def is_thread_replyable(self, thread):
        if thread.is_system_thread:
            return False

        latest_message = thread.messages.order_by('-created_at').first()
        if latest_message and latest_message.message_type in ['system_notification', 'alert', 'announcement']:
            return False

        return True

    def perform_create(self, serializer):
        thread = serializer.save(creator=self.request.user)
        if self.request.user not in thread.participants.all():
            thread.participants.add(self.request.user)

    @action(detail=True, methods=['post'])
    def add_participant(self, request, pk=None):
        thread = self.get_object()
        user_id = request.data.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            thread.participants.add(user)
            return Response({'status': 'participant added'})
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def remove_participant(self, request, pk=None):
        thread = self.get_object()
        user_id = request.data.get('user_id')
        try:
            user = User.objects.get(id=user_id)
            if user == request.user:
                return Response({'error': 'Cannot remove yourself'}, status=status.HTTP_400_BAD_REQUEST)
            thread.participants.remove(user)
            return Response({'status': 'participant removed'})
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def mark_all_read(self, request, pk=None):
        thread = self.get_object()
        now = timezone.now()
        recipients = MessageRecipient.objects.filter(
            message__thread=thread,
            user=request.user,
            is_read=False
        )
        recipients.update(is_read=True, read_at=now)
        return Response({'status': 'all messages marked as read'})

    def unread_thread_count(self, request):
        user = request.user
        unread_count = MessageRecipient.objects.filter(
            user=user,
            is_read=False
        ).count()
        return Response({'unread_count': unread_count})


class MessageViewSet(ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, IsParticipantOrAdmin]
    parser_classes = [MultiPartParser, JSONParser]
    queryset = Message.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'created_at', 'updated_at']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        user = self.request.user
        if user.is_staff and self.request.query_params.get('all') == 'true':
            return Message.objects.all()

        thread_ids = MessageThread.objects.filter(
            Q(participants=user) | Q(lab_group__in=user.lab_groups.all())
        ).values_list('id', flat=True)

        return Message.objects.filter(thread_id__in=thread_ids)

    def create(self, request, *args, **kwargs):
        data = {k: v for k, v in request.data.items() if k != 'attachments'}
        thread_id = data.get('thread')

        try:
            thread = MessageThread.objects.get(id=thread_id)
            if not self.has_thread_permission(thread):
                return Response({'error': 'You do not have access to this thread'},
                                status=status.HTTP_403_FORBIDDEN)
        except MessageThread.DoesNotExist:
            return Response({'error': 'Thread not found'}, status=status.HTTP_404_NOT_FOUND)

        if 'sender_id' not in data:
            data['sender_id'] = request.user.id

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(thread=thread)

        for participant in thread.participants.all():
            MessageRecipient.objects.create(
                message=message,
                user=participant,
                is_read=(participant == request.user)
            )

        files = request.FILES.getlist('attachments')
        for file in files:
            MessageAttachment.objects.create(
                message=message,
                file=file,
                file_name=file.name,
                file_size=file.size,
                content_type=file.content_type
            )

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def has_thread_permission(self, thread):
        user = self.request.user
        return (user.is_staff or
                user in thread.participants.all() or
                (thread.lab_group and thread.lab_group in user.lab_groups.all()))

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        message = self.get_object()
        recipient = get_object_or_404(
            MessageRecipient, message=message, user=request.user
        )
        recipient.mark_as_read()
        return Response({'status': 'message marked as read'})

    @action(detail=True, methods=['post'])
    def mark_unread(self, request, pk=None):
        message = self.get_object()
        recipient = get_object_or_404(
            MessageRecipient, message=message, user=request.user
        )
        recipient.is_read = False
        recipient.read_at = None
        recipient.save()
        return Response({'status': 'message marked as unread'})


class MessageRecipientViewSet(ModelViewSet):
    serializer_class = MessageRecipientSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]
    queryset = MessageRecipient.objects.all()
    pagination_class = LimitOffsetPagination


    def get_queryset(self):
        user = self.request.user
        if user.is_staff and self.request.query_params.get('all') == 'true':
            return MessageRecipient.objects.all()
        return MessageRecipient.objects.filter(user=user)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        recipient = self.get_object()
        if recipient.user != request.user and not request.user.is_staff:
            return Response({'error': 'You do not have permission'},
                            status=status.HTTP_403_FORBIDDEN)
        recipient.is_archived = True
        recipient.save()
        return Response({'status': 'message archived'})

    @action(detail=True, methods=['post'])
    def unarchive(self, request, pk=None):
        recipient = self.get_object()
        if recipient.user != request.user and not request.user.is_staff:
            return Response({'error': 'You do not have permission'},
                            status=status.HTTP_403_FORBIDDEN)
        recipient.is_archived = False
        recipient.save()
        return Response({'status': 'message unarchived'})

    @action(detail=True, methods=['post'])
    def delete(self, request, pk=None):
        recipient = self.get_object()
        if recipient.user != request.user and not request.user.is_staff:
            return Response({'error': 'You do not have permission'},
                            status=status.HTTP_403_FORBIDDEN)
        recipient.is_deleted = True
        recipient.save()
        return Response({'status': 'message deleted'})

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        recipient = self.get_object()
        if recipient.user != request.user and not request.user.is_staff:
            return Response({'error': 'You do not have permission'},
                            status=status.HTTP_403_FORBIDDEN)
        recipient.is_deleted = False
        recipient.save()
        return Response({'status': 'message restored'})


class MessageAttachmentViewSet(ReadOnlyModelViewSet):
    serializer_class = MessageAttachmentSerializer
    permission_classes = [IsAuthenticated, IsParticipantOrAdmin]
    parser_classes = [MultiPartParser, JSONParser]
    queryset = MessageAttachment.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'created_at', 'updated_at']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        user = self.request.user
        if user.is_staff and self.request.query_params.get('all') == 'true':
            return MessageAttachment.objects.all()

        return MessageAttachment.objects.filter(
            Q(message__thread__participants=user) |
            Q(message__thread__lab_group__in=user.lab_groups.all())
        ).distinct()

    class ReagentSubscriptionViewSet(ModelViewSet):
        serializer_class = ReagentSubscriptionSerializer

        def get_queryset(self):
            user = self.request.user
            if user.is_staff:
                return ReagentSubscription.objects.all()
            return ReagentSubscription.objects.filter(user=user)

        def perform_create(self, serializer):
            serializer.save(user=self.request.user)

        @action(detail=False, methods=['post'])
        def subscribe(self, request):
            reagent_id = request.data.get('stored_reagent')
            notify_low_stock = request.data.get('notify_on_low_stock', True)
            notify_expiry = request.data.get('notify_on_expiry', True)

            try:
                stored_reagent = StoredReagent.objects.get(id=reagent_id)
                subscription = stored_reagent.subscribe_user(
                    request.user,
                    notify_low_stock=notify_low_stock,
                    notify_expiry=notify_expiry
                )
                return Response(
                    ReagentSubscriptionSerializer(subscription).data,
                    status=status.HTTP_201_CREATED
                )
            except StoredReagent.DoesNotExist:
                return Response(
                    {'error': 'Reagent not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

        @action(detail=False, methods=['post'])
        def unsubscribe(self, request):
            reagent_id = request.data.get('stored_reagent')
            try:
                stored_reagent = StoredReagent.objects.get(id=reagent_id)
                result = stored_reagent.unsubscribe_user(request.user)
                return Response({'success': result}, status=status.HTTP_200_OK)
            except StoredReagent.DoesNotExist:
                return Response(
                    {'error': 'Reagent not found'},
                    status=status.HTTP_404_NOT_FOUND
                )


class ReagentDocumentViewSet(ModelViewSet):
    serializer_class = AnnotationSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]
    queryset = Annotation.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['annotation', 'annotation_name']
    ordering_fields = ['id', 'created_at', 'updated_at']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        user = self.request.user
        if user.is_staff and self.request.query_params.get('all') == 'true':
            return Annotation.objects.all()

        reagent_id = self.request.query_params.get('reagent_id')
        folder_name = self.request.query_params.get('folder_name')

        if not reagent_id:
            return Annotation.objects.none()

        try:
            reagent = StoredReagent.objects.get(id=reagent_id)
            if not self.has_reagent_permission_view(reagent):
                return Annotation.objects.none()

            if folder_name:
                folder = AnnotationFolder.objects.filter(
                    stored_reagent=reagent,
                    folder_name=folder_name
                ).first()

                if folder:
                    return Annotation.objects.filter(folder=folder)

            return Annotation.objects.filter(
                folder__stored_reagent=reagent
            )
        except StoredReagent.DoesNotExist:
            return Annotation.objects.none()

    def create(self, request, *args, **kwargs):
        reagent_id = request.data.get('reagent_id')
        folder_name = request.data.get('folder_name', '')
        file = request.FILES.get('file')

        try:
            reagent = StoredReagent.objects.get(id=reagent_id)
            if not self.has_reagent_permission_edit(reagent):
                return Response(
                    {'error': 'You do not have permission to add documents to this reagent'},
                    status=status.HTTP_403_FORBIDDEN
                )

            folder = AnnotationFolder.objects.filter(
                stored_reagent=reagent,
                folder_name=folder_name
            ).first()

            if not folder:
                return Response(
                    {'error': f'Folder "{folder_name}" not found for this reagent'},
                    status=status.HTTP_404_NOT_FOUND
                )


            annotation_data = {
                'annotation': request.data.get('annotation', ''),
                'annotation_name': file.name if file else request.data.get('annotation_name', ''),
                'file': file,
                'folder': folder.id,
                'user': request.user.id,
                'annotation_type': "file"
            }

            serializer = self.get_serializer(data=annotation_data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)

            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

        except StoredReagent.DoesNotExist:
            return Response(
                {'error': 'Reagent not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    def has_reagent_permission_edit(self, reagent):
        user = self.request.user
        return (
                user.is_staff or
                user == reagent.user
        )

    def has_reagent_permission_view(self, reagent):
        user = self.request.user
        return (
            user.is_staff or
            user == reagent.user or
            (reagent.lab_group and reagent.lab_group in user.lab_groups.all()) or reagent.access_all or user in reagent.access_users
        )

    @action(detail=False, methods=['get'])
    def folder_list(self, request):
        """Return list of available folders for a reagent"""
        reagent_id = request.query_params.get('reagent_id')

        try:
            reagent = StoredReagent.objects.get(id=reagent_id)
            if not self.has_reagent_permission_edit(reagent):
                return Response(
                    {'error': 'You do not have permission to view this reagent'},
                    status=status.HTTP_403_FORBIDDEN
                )

            folders = reagent.annotation_folders.all()
            return Response([{
                'id': folder.id,
                'name': folder.folder_name
            } for folder in folders])

        except StoredReagent.DoesNotExist:
            return Response(
                {'error': 'Reagent not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    def destroy(self, request, *args, **kwargs):
        annotation = self.get_object()
        if not self.has_reagent_permission_edit(annotation.folder.stored_reagent):
            return Response(
                {'error': 'You do not have permission to delete this document'},
                status=status.HTTP_403_FORBIDDEN
            )

        if annotation.file:
            annotation.file.delete(save=False)

        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'])
    def bind_chunked_file(self, request):
        """
        Bind a file that was uploaded in chunks to a reagent document
        """
        upload_id = request.data.get('upload_id')
        reagent_id = request.data.get('reagent_id')
        folder_name = request.data.get('folder_name', '')
        annotation_name = request.data.get('annotation_name', '')
        annotation_text = request.data.get('annotation', '')

        if not upload_id or not reagent_id:
            return Response(
                {'error': 'Both upload_id and reagent_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            chunked_upload = ChunkedUpload.objects.get(id=upload_id)
            if chunked_upload.user != request.user and not request.user.is_staff:
                return Response(
                    {'error': 'You do not have permission to use this upload'},
                    status=status.HTTP_403_FORBIDDEN
                )

            reagent = StoredReagent.objects.get(id=reagent_id)
            if not self.has_reagent_permission_edit(reagent):
                return Response(
                    {'error': 'You do not have permission to add documents to this reagent'},
                    status=status.HTTP_403_FORBIDDEN
                )

            folder = AnnotationFolder.objects.filter(
                stored_reagent=reagent,
                folder_name=folder_name
            ).first()

            if not folder:
                return Response(
                    {'error': f'Folder {folder_name} not found for this reagent'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Create a proper file name if not provided
            if not annotation_name:
                annotation_name = chunked_upload.filename

            # Create the annotation
            annotation_data = {
                'annotation': annotation_text,
                'annotation_name': annotation_name,
                'folder': folder.id,
                'user': request.user.id,
                'annotation_type': "file"
            }

            # Save the chunked file to the annotation
            with open(chunked_upload.file.path, 'rb') as file:
                django_file = djangoFile(file)
                annotation = Annotation(
                    annotation=annotation_data['annotation'],
                    annotation_name=annotation_data['annotation_name'],
                    folder_id=annotation_data['folder'],
                    user_id=annotation_data['user'],
                    annotation_type=annotation_data['annotation_type']
                )
                annotation.file.save(annotation_name, django_file, save=True)
            chunked_upload.delete()

            serializer = self.get_serializer(annotation)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except ChunkedUpload.DoesNotExist:
            return Response(
                {'error': 'Upload not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except StoredReagent.DoesNotExist:
            return Response(
                {'error': 'Reagent not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': f'An error occurred: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def get_download_token(self, request, pk=None):
        """Generate a signed URL for downloading the reagent document"""
        annotation = request.query_params.get('annotation_id', None)
        if not annotation:
            return Response({"error": "No annotation ID provided"}, status=status.HTTP_400_BAD_REQUEST)

        annotation = Annotation.objects.get(id=annotation)
        if not annotation.file:
            return Response({"error": "No file attached to this document"}, status=status.HTTP_404_NOT_FOUND)


        signer = TimestampSigner()
        token = signer.sign(str(annotation.id))

        return Response({"token": token}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def download_signed(self, request):
        """Download a file using a signed token"""
        token = request.query_params.get('token', None)
        if not token:
            return Response({"error": "No token provided"}, status=status.HTTP_400_BAD_REQUEST)

        signer = TimestampSigner()
        try:
            annotation_id = signer.unsign(token, max_age=60 * 30)  # 30 minute expiration
            response = HttpResponse(status=200)
            annotation = Annotation.objects.get(id=annotation_id)
            if not annotation.file:
                return Response({"error": "No file attached to this document"}, status=status.HTTP_404_NOT_FOUND)
            filename = annotation.file.name.split('/')[-1]

            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            response["X-Accel-Redirect"] = f"/media/annotations/{filename}"
            return response
        except (BadSignature, SignatureExpired) as e:
            return Response({"error": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)