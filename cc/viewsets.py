import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta
from django.core.mail import send_mail
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.models import User
from django.core.signing import TimestampSigner, loads, dumps
from django.db.models import Q, Max
from django.db.models.expressions import result
from django.http import HttpResponse
from django.utils import timezone
from django_filters.views import FilterMixin
from drf_chunked_upload.models import ChunkedUpload
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.viewsets import ModelViewSet
from rest_framework.filters import SearchFilter, OrderingFilter
from django.core.files.base import File as djangoFile
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination

from cc.filters import UnimodFilter
from cc.models import ProtocolModel, ProtocolStep, Annotation, Session, StepVariation, TimeKeeper, ProtocolSection, \
    ProtocolRating, Reagent, StepReagent, ProtocolReagent, ProtocolTag, StepTag, Tag, AnnotationFolder, Project, \
    Instrument, InstrumentUsage, InstrumentPermission, StorageObject, StoredReagent, ReagentAction, LabGroup, Species, \
    SubcellularLocation, HumanDisease, Tissue, MetadataColumn, MSUniqueVocabularies, Unimod, InstrumentJob
from cc.permissions import OwnerOrReadOnly, InstrumentUsagePermission, InstrumentViewSetPermission
from cc.rq_tasks import transcribe_audio_from_video, transcribe_audio, create_docx, llama_summary, remove_html_tags, \
    ocr_b64_image, export_data, import_data, llama_summary_transcript, export_sqlite
from cc.serializers import ProtocolModelSerializer, ProtocolStepSerializer, AnnotationSerializer, \
    SessionSerializer, StepVariationSerializer, TimeKeeperSerializer, ProtocolSectionSerializer, UserSerializer, \
    ProtocolRatingSerializer, ReagentSerializer, StepReagentSerializer, ProtocolReagentSerializer, \
    ProtocolTagSerializer, StepTagSerializer, TagSerializer, AnnotationFolderSerializer, ProjectSerializer, \
    InstrumentSerializer, InstrumentUsageSerializer, StorageObjectSerializer, StoredReagentSerializer, \
    ReagentActionSerializer, LabGroupSerializer, SpeciesSerializer, SubcellularLocationSerializer, \
    HumanDiseaseSerializer, TissueSerializer, MetadataColumnSerializer, MSUniqueVocabulariesSerializer, \
    UnimodSerializer, InstrumentJobSerializer


class ProtocolViewSet(ModelViewSet, FilterMixin):
    permission_classes = [OwnerOrReadOnly]
    queryset = ProtocolModel.objects.all()
    authentication_classes = [TokenAuthentication]
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

class StepViewSet(ModelViewSet, FilterMixin):
    permission_classes = [OwnerOrReadOnly]
    queryset = ProtocolStep.objects.all()
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['annotation']
    ordering_fields = ['created_at']
    serializer_class = AnnotationSerializer
    filterset_fields = ['step', 'session__unique_id']

    def create(self, request, *args, **kwargs):
        step = None
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        annotation = Annotation()
        if 'step' in request.data:
            if request.data['step']:
                step = ProtocolStep.objects.get(id=request.data['step'])
                annotation.step = step
        if 'session' in request.data:
            if request.data['session'] != "":
                session = Session.objects.get(unique_id=request.data['session'])
                annotation.session = session
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
            instrument_permission = InstrumentPermission.objects.filter(instrument=instrument, user=request.user)
            if not instrument_permission.exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
            instrument_permission = instrument_permission.first()
            if not instrument_permission.can_manage and not instrument_permission.can_book:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
            if "time_started" in request.data and "time_ended" in request.data:
                time_started = request.data['time_started']
                time_ended = request.data['time_ended']
                # check if the instrument is available at this time by checking if submitted time_started is between the object time_started and time_ended or time_ended is between the object time_started and time_ended
                if time_started and time_ended:
                    if InstrumentUsage.objects.filter(instrument=instrument, time_started__range=[time_started, time_ended]).exists() or InstrumentUsage.objects.filter(instrument=instrument, time_ended__range=[time_started, time_ended]).exists():
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
                transcribe_audio_from_video.delay(annotation.file.path, settings.WHISPERCPP_DEFAULT_MODEL, annotation.id, custom_id)
            elif annotation.annotation_type == "audio":
                transcribe_audio.delay(annotation.file.path, settings.WHISPERCPP_DEFAULT_MODEL, annotation.id, custom_id)
        if annotation.annotation_type == "instrument":
            usage = InstrumentUsage.objects.create(
                instrument=instrument,
                annotation=annotation,
                time_started=time_started,
                time_ended=time_ended,
                user=request.user,
                description=annotation.annotation
            )
        if 'instrument_job' in request.data and 'instrument_user_type' in request.data:
            instrument_job = InstrumentJob.objects.get(id=request.data['instrument_job'])
            if request.data['instrument_user_type'] == "staff_annotation":
                instrument_job.staff_annotations.add(annotation)
            elif request.data['instrument_user_type'] == "user_annotation":
                instrument_job.user_annotations.add(annotation)
        data = self.get_serializer(annotation).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
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
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        # Check if session is enabled, and if the user is the owner of the session
        queryset = self.queryset
        user = self.request.user
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
        file_name = annotation.file.name
        response = HttpResponse(status=200)
        response["Content-Disposition"] = f'attachment; filename="{file_name.split("/")[-1]}"'
        response["X-Accel-Redirect"] = f"/media/{file_name}"
        return response

    def get_object(self):
        obj = super().get_object()
        user = self.request.user

        if obj.user == user or obj.session.user == user:
            return obj

        if obj.session.viewers.filter(id=user.id).exists():
            return obj

        if obj.session.editors.filter(id=user.id).exists():
            return obj

        if obj.session.enabled:
            return obj

        raise PermissionDenied

    @action(detail=True, methods=['post'])
    def get_signed_url(self, request, pk=None):
        signer = TimestampSigner()
        annotation = Annotation.objects.get(id=pk)
        user = self.request.user
        file = {'file': annotation.file.name, 'id': annotation.id}
        signed_token = signer.sign_object(file)
        if annotation.session:
            if annotation.session.enabled:
                if not annotation.scratched:
                    return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)

        if user.is_authenticated:
            if annotation.session:
                if user in annotation.session.viewers.all() or user in annotation.session.editors.all() or user == annotation.session.user or user == annotation.user:
                    if annotation.scratched:
                        if user not in annotation.session.editors.all() and user != annotation.user and user != annotation.session.user:
                            return Response(status=status.HTTP_401_UNAUTHORIZED)
                    else:
                        return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
                    return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
            else:
                instrument_jobs = annotation.instrument_jobs.all()
                for instrument_job in instrument_jobs:
                    if user == instrument_job.user:
                        return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
                    else:
                        lab_group = instrument_job.service_lab_group
                        staff =  instrument_job.staff.all()
                        if staff.count() > 0:
                            if user in staff:
                                return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
                        else:
                            if user in lab_group.users.all():
                                return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
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
        if folder:
            anntation_folder = AnnotationFolder.objects.get(id=folder)
            annotations = Annotation.objects.filter(folder=anntation_folder)
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
        if "instrument_user_type" in request.data and "instrument_job" in request.data:
            instrument_job = InstrumentJob.objects.get(id=request.data['instrument_job'])
            if request.data['instrument_user_type'] == "staff_annotation":
                instrument_job.staff_annotations.add(annotation)
            elif request.data['instrument_user_type'] == "user_annotation":
                instrument_job.user_annotations.add(annotation)

        annotation.annotation_name = annotation_name
        annotation.annotation_type = "file"
        with open(upload.file.path, "rb") as f:
            annotation.file.save(file_name, f)
        annotation.save()
        upload.delete()
        data = self.get_serializer(annotation).data
        return Response(data, status=status.HTTP_201_CREATED)



class SessionViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Session.objects.all()
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
    serializer_class = TimeKeeperSerializer

    def get_queryset(self):
        user = self.request.user
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
        # check if timekeeper already exists
        timekeeper = TimeKeeper.objects.filter(user=user, session__unique_id=request.data['session'], step=request.data['step'])
        if timekeeper.exists():
            return Response({"error": "TimeKeeper already exists"}, status=status.HTTP_400_BAD_REQUEST)
        session = Session.objects.get(unique_id=request.data['session'])
        step = ProtocolStep.objects.get(id=request.data['step'])
        started = False
        if "started" in request.data:
            started = request.data['started']
        start_time = None
        if "start_time" in request.data:
            start_time = request.data['start_time']
        current_duration = 0
        if "current_duration" in request.data:
            current_duration = request.data['current_duration']
        time_keeper = TimeKeeper()
        time_keeper.session = session
        time_keeper.step = step
        time_keeper.user = user
        if start_time:
            time_keeper.start_time = start_time
        time_keeper.started = started
        time_keeper.current_duration = current_duration
        time_keeper.save()
        data = self.get_serializer(time_keeper).data
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"timer_{session.unique_id}",
            {
                "type": "timer_message",
                "message": data
            }
        )
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if "start_time" in request.data:
            instance.start_time = request.data['start_time']
        if "started" in request.data:
            instance.started = request.data['started']
        if "current_duration" in request.data:
            instance.current_duration = request.data['current_duration']
        instance.save()
        data = self.get_serializer(instance).data
        channel_layer = get_channel_layer()
        session = instance.session
        async_to_sync(channel_layer.group_send)(
            f"timer_{session.unique_id}",
            {
                "type": "timer_message",
                "message": data
            }
        )
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProtocolSectionViewSet(ModelViewSet):
    permission_classes = [OwnerOrReadOnly]
    queryset = ProtocolSection.objects.all()
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
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
            if a.user == request.user or a.session.user == request.user or request.user in a.session.editors.all():
                permission['edit'] = True
                permission['view'] = True
                permission['delete'] = True

            elif request.user in a.session.viewers.all() or a.session.enabled:
                permission['view'] = True
            permission_list.append({"permission": permission, "annotation": a.id})
        return Response(permission_list, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def check_stored_reagent_permission(self, request):
        stored_reagent_ids = request.data["stored_reagents"]
        stored_reagents = StoredReagent.objects.filter(id__in=stored_reagent_ids)
        permission_list = []
        for sr in stored_reagents:
            permission = {
                "edit": False,
                "view": True,
                "delete": False
            }
            if sr.user == request.user:
                permission['delete'] = True
                permission['edit'] = True
            else:
                if sr.shareable:
                    if request.user in sr.access_users:
                        permission['edit'] = True
                    else:
                        lab_groups = request.user.lab_groups.all()
                        if sr.access_lab_groups.filter(
                            id__in=lab_groups.values_list('id', flat=True)).exists():
                            permission['edit'] = True
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
        return Response({"use_coturn": use_coturn, "use_llm": use_llm, "use_ocr": use_ocr, "use_whisper": use_whisper}, status=status.HTTP_200_OK)

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
        data = LabGroupSerializer(lab_groups, many=True).data
        return Response(data, status=status.HTTP_200_OK)

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
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['instrument_name', 'instrument_description']
    ordering_fields = ['instrument_name']
    filterset_fields = ['instrument_name']
    serializer_class = InstrumentSerializer

    def get_queryset(self):
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
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        if "name" in request.data:
            instance.instrument_name = request.data['name']
        if "description" in request.data:
            instance.instrument_description = request.data['description']

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
            print(data)
            return Response(data, status=status.HTTP_200_OK)
        return Response(data, status=status.HTTP_200_OK)




class InstrumentUsageViewSet(ModelViewSet, FilterMixin):
    permission_classes = [InstrumentUsagePermission]
    queryset = InstrumentUsage.objects.all()
    authentication_classes = [TokenAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['instrument__instrument_name']
    ordering_fields = ['time_started', 'time_ended']
    filterset_fields = ['instrument__instrument_name']
    serializer_class = InstrumentUsageSerializer

    def get_queryset(self):
        time_started = self.request.query_params.get('time_started', None)
        time_ended = self.request.query_params.get('time_ended', None)
        instrument = self.request.query_params.get('instrument', None)

        # filter for any usage where time_started or time_ended of the usage falls within the range of the query
        if not time_started:
            time_started = datetime.now() - timedelta(days=1)

        if not time_ended:
            time_ended = datetime.now() + timedelta(days=1)

        query_time_started = Q(time_started__range=[time_started, time_ended])
        query_time_ended = Q(time_ended__range=[time_started, time_ended])

        if instrument:
            return self.queryset.filter((query_time_started | query_time_ended), instrument__id=instrument)
        return self.queryset.filter((query_time_started | query_time_ended))

    def get_object(self):
        obj = super().get_object()
        return obj

    @action(detail=False, methods=['get'])
    def get_user_instrument_usage(self, request):
        user = self.request.user
        instrument_usage = self.queryset.filter(user=user)
        data = self.get_serializer(instrument_usage, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        time_started = request.data['time_started']
        time_ended = request.data['time_ended']
        if InstrumentUsage.objects.filter(time_started__range=[time_started,time_ended]).exists() or InstrumentUsage.objects.filter(time_ended__range=[time_started, time_ended]).exists():
            return Response(status=status.HTTP_409_CONFLICT)
        if "time_started" in request.data:
            instance.time_started = time_started
        if "time_ended" in request.data:
            instance.time_ended = time_ended
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

        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


    def create(self, request, *args, **kwargs):
        instrument = Instrument.objects.get(id=request.data['instrument'])
        user = self.request.user
        time_started = request.data['time_started']
        time_ended = request.data['time_ended']
        if InstrumentUsage.objects.filter(time_started__range=[time_started,time_ended]).exists() or InstrumentUsage.objects.filter(time_ended__range=[time_started, time_ended]).exists():
            return Response(status=status.HTTP_409_CONFLICT)
        usage = InstrumentUsage()
        usage.instrument = instrument
        usage.user = user
        usage.time_started = time_started
        usage.time_ended = time_ended
        usage.description = request.data['description']
        usage.save()
        data = self.get_serializer(usage).data
        return Response(data, status=status.HTTP_201_CREATED)


class StorageObjectViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticated]
    queryset = StorageObject.objects.all()
    authentication_classes = [TokenAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['object_name', 'object_description', 'object_type']
    ordering_fields = ['object_name', 'object_type']
    filterset_fields = ['object_name', 'object_type']
    serializer_class = StorageObjectSerializer
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        query = Q()

        if self.request.query_params.get('stored_at', None):
            store_at = StorageObject.objects.get(id=self.request.query_params.get('stored_at'))
            query &= Q(stored_at=store_at)

        if self.request.query_params.get('root', 'false') == 'true':
            query &= Q(stored_at__isnull=True)

        if self.request.query_params.get('lab_group', None):
            lab_group = LabGroup.objects.get(id=self.request.query_params.get('lab_group'))
            query &= Q(access_lab_groups=lab_group)
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
        storage_object = StorageObject()
        storage_object.object_name = request.data['name']
        storage_object.object_description = request.data['description']
        storage_object.object_type = request.data['object_type']
        storage_object.user = self.request.user
        storage_object.stored_at = stored_at
        if "png_base64" in request.data:
            storage_object.png_base64 = request.data['png_base64']
        storage_object.save()
        data = self.get_serializer(storage_object).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user != self.request.user and not self.request.user.is_staff:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        if "name" in request.data:
            instance.object_name = request.data['name']
        if "description" in request.data:
            instance.object_description = request.data['description']
        if "png_base64" in request.data:
            instance.png_base64 = request.data['png_base64']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

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
        path = [{"id": storage_object.id, "name": storage_object.object_name[:]}]
        while storage_object.stored_at:
            storage_object = storage_object.stored_at
            path.append({"id": storage_object.id, "name": storage_object.object_name[:]})
            path.reverse()
        return Response(path, status=status.HTTP_200_OK)



class StoredReagentViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticated]
    queryset = StoredReagent.objects.all()
    authentication_classes = [TokenAuthentication]
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
        stored_reagent = StoredReagent()
        reagent = Reagent.objects.filter(name=self.request.data['name'], unit=self.request.data['unit'])
        if reagent.exists():
            reagent = reagent.first()
        else:
            reagent = Reagent()
            reagent.name = self.request.data['name']
            reagent.unit = self.request.data['unit']
            reagent.save()

        storage_object = StorageObject.objects.get(id=request.data['storage_object'])
        stored_reagent.reagent = reagent
        stored_reagent.storage_object = storage_object
        if "quantity" in request.data:
            stored_reagent.quantity = request.data['quantity']
        else:
            stored_reagent.quantity = 1
        stored_reagent.user = self.request.user
        if "notes" in request.data:
            stored_reagent.notes = request.data['notes']
        if "png_base64" in request.data:
            stored_reagent.png_base64 = request.data['png_base64']
        if "barcode" in request.data:
            stored_reagent.barcode = request.data['barcode']
        if "shareable" in request.data:
            stored_reagent.shareable = request.data['shareable']
        if "created_by_project" in request.data:
            project = Project.objects.get(id=request.data['created_by_project'])
            stored_reagent.created_by_project = project
        if "created_by_step" in request.data:
            step = ProtocolStep.objects.get(id=request.data['created_by_step'])
            stored_reagent.created_by_step = step
        if "created_by_protocol" in request.data:
            protocol = ProtocolModel.objects.get(id=request.data['created_by_protocol'])
            stored_reagent.created_by_protocol = protocol
        if "created_by_session" in request.data:
            session = Session.objects.get(id=request.data['created_by_session'])
            stored_reagent.created_by_session = session
        if "expiration_date" in request.data:
            expiration_date = datetime.strptime(request.data['expiration_date'], '%Y-%m-%d')
            stored_reagent.expiration_date = expiration_date.date()
        if "access_all" in request.data:
            stored_reagent.access_all = request.data['access_all']
        stored_reagent.save()
        data = self.get_serializer(stored_reagent).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if not self.request.user.is_staff:
            if not self.request.user == instance.user:
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        if "quantity" in request.data:
            instance.quantity = request.data['quantity']
        if "notes" in request.data:
            instance.notes = request.data['notes']
        if "png_base64" in request.data:
            instance.png_base64 = request.data['png_base64']
        if "barcode" in request.data:
            instance.barcode = request.data['barcode']
        if "shareable" in request.data:
            instance.shareable = request.data['shareable']
        if "created_by_project" in request.data:
            project = Project.objects.get(id=request.data['created_by_project'])
            instance.created_by_project = project
        if "created_by_protocol" in request.data:
            protocol = ProtocolModel.objects.get(id=request.data['created_by_protocol'])
            instance.created_by_protocol = protocol
        if "created_by_session" in request.data:
            session = Session.objects.get(id=request.data['created_by_session'])
            instance.created_by_session = session
        if "created_by_step" in request.data:
            step = ProtocolStep.objects.get(id=request.data['created_by_step'])
            instance.created_by_step = step
        if "expiration_date" in request.data:
            expiration_date = datetime.strptime(request.data['expiration_date'], '%Y-%m-%d')
            instance.expiration_date = expiration_date.date()
        if "access_all" in request.data:
            instance.access_all = request.data['access_all']
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

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

class ReagentActionViewSet(ModelViewSet, FilterMixin):
    permission_classes = [IsAuthenticated]
    queryset = ReagentAction.objects.all()
    authentication_classes = [TokenAuthentication]
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
    permission_classes = [IsAuthenticated]
    queryset = LabGroup.objects.all()
    authentication_classes = [TokenAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name']
    filterset_fields = ['name']
    serializer_class = LabGroupSerializer

    def get_queryset(self):
        query = Q()
        stored_reagent_id = self.request.query_params.get('stored_reagent', None)
        if stored_reagent_id:
            stored_reagent = StoredReagent.objects.get(id=stored_reagent_id)
            return stored_reagent.access_lab_groups.all()
        storage_object_id = self.request.query_params.get('storage_object', None)
        if storage_object_id:
            storage_object = StorageObject.objects.get(id=storage_object_id)
            return storage_object.access_lab_groups.all()
        return self.queryset

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
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
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
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['location_identifier', 'synonyms']
    search_fields = ['^location_identifier', '^synonyms']

    def get_queryset(self):
        return super().get_queryset()

class TissueViewSet(ModelViewSet, FilterMixin):
    serializer_class = TissueSerializer
    queryset = Tissue.objects.all()
    permission_classes = [AllowAny]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['identifier', 'synonyms']
    search_fields = ['^identifier', '^synonyms']

    def get_queryset(self):
        return super().get_queryset()


class HumanDiseaseViewSet(ModelViewSet, FilterMixin):
    serializer_class = HumanDiseaseSerializer
    queryset = HumanDisease.objects.all()
    permission_classes = [AllowAny]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['identifier', 'synonyms']
    search_fields = ['^identifier', '^synonyms', '^acronym']

    def get_queryset(self):
        return super().get_queryset()


class MetadataColumnViewSet(FilterMixin, ModelViewSet):
    serializer_class = MetadataColumnSerializer
    queryset = MetadataColumn.objects.all()
    permission_classes = [IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
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
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['accession', 'name']
    search_fields = ['^name']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        term_type = self.request.query_params.get('term_type', None)
        print(term_type)
        print(self.request)
        if term_type:
            result = self.queryset.filter(term_type__iexact=term_type)
            print(result)
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
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = UnimodFilter
    ordering_fields = ['accession', 'name']
    search_fields = ['^name']
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
    authentication_classes = [TokenAuthentication]
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
        user_metadata = [
            {
                "name": "Organism", "type": "Characteristics", "mandatory": True
            },
            {
                "name": "Tissue", "type": "Characteristics", "mandatory": True
            },
            {
                "name": "Cell type", "type": "Characteristics", "mandatory": True
            },
            {
                "name": "Sample type", "type": "Characteristics", "mandatory": True
            }
            ,
            {
                "name": "Cleaveage agent details", "type": "Comment", "mandatory": True
            },
            {
                "name": "Enrichment process", "type": "Comment", "mandatory": True
            }
        ]
        instrument_job.save()
        for metadata in user_metadata:
            metadata_column = MetadataColumn.objects.create(
                name=metadata['name'],
                type=metadata['type'],
                mandatory=metadata['mandatory'],
            )
            instrument_job.user_metadata.add(metadata_column)
        staff_metadata = [
            {
                "name": "Label",
                "type": "Comment",
                "mandatory": True
            }
        ]
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
            using.append('sample_number')
        if 'protocol' in request.data:
            protocol = ProtocolModel.objects.get(id=request.data['protocol'])

            if not instrument_job.protocol:
                instrument_job.protocol = protocol
            elif instrument_job.protocol != protocol:
                instrument_job.protocol = protocol
            using.append('protocol')
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
                        )
                        instrument_job.user_metadata.add(metadata_column)
                else:
                    metadata_column = MetadataColumn.objects.create(
                        name=metadata['name'],
                        type=metadata['type'],
                        value=metadata['value'],
                        mandatory=metadata['mandatory'],
                        modifiers=json.dumps(metadata['modifiers']),
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
        instrument_job.save()
        if settings.NOTIFICATION_EMAIL_FROM:
            staff = instrument_job.staff.all()
            subject = 'Instrument Job Submitted'
            message = f'Instrument Job {instrument_job.job_name} has been submitted by {instrument_job.user.username}'
            recipient_list = [staff.email for staff in staff if staff.email]
            if recipient_list:
                send_mail(subject, message, settings.NOTIFICATION_EMAIL_FROM, recipient_list)

        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def individual_field_typeahead(selfself, request):
        field_name = request.query_params.get('field_name', None)
        if field_name in ['cost_center', 'funder']:
            paginator = LimitOffsetPagination()
            paginator.default_limit = 10
            search_query = request.query_params.get('search', None)
            if field_name == 'cost_center' and search_query:
                queryset = InstrumentJob.objects.filter(cost_center__startswith=search_query).values_list('cost_center', flat=True).distinct()
            elif field_name == 'funder' and search_query:
                queryset = InstrumentJob.objects.filter(funder__startswith=search_query).values_list('funder', flat=True).distinct()
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
        instrument_job.save()
        return Response(InstrumentJobSerializer(instrument_job).data, status=status.HTTP_200_OK)