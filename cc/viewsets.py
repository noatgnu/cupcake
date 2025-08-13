import base64
import hashlib
import hmac
import io
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.mail import send_mail
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q, Max, Count, Sum
from django_rq import get_queue
from django.core.signing import TimestampSigner, loads, dumps, BadSignature, SignatureExpired
from django.db.models.expressions import result
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django_filters.views import FilterMixin
from drf_chunked_upload.models import ChunkedUpload
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.filters import SearchFilter, OrderingFilter
from django.core.files.base import File as djangoFile
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny, IsAdminUser
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination
from rq.job import Job

from cc.filters import UnimodFilter, UnimodSearchFilter, MSUniqueVocabulariesSearchFilter, HumanDiseaseSearchFilter, \
    TissueSearchFilter, SubcellularLocationSearchFilter, SpeciesSearchFilter
from cc.models import ProtocolModel, ProtocolStep, Annotation, Session, StepVariation, TimeKeeper, ProtocolSection, \
    ProtocolRating, Reagent, StepReagent, ProtocolReagent, ProtocolTag, StepTag, Tag, AnnotationFolder, Project, \
    Instrument, InstrumentUsage, InstrumentPermission, StorageObject, StoredReagent, ReagentAction, LabGroup, Species, \
    SubcellularLocation, HumanDisease, Tissue, MetadataColumn, MSUniqueVocabularies, Unimod, InstrumentJob, \
    FavouriteMetadataOption, Preset, MetadataTableTemplate, MaintenanceLog, SupportInformation, ExternalContact, \
    ExternalContactDetails, Message, MessageRecipient, MessageAttachment, MessageRecipient, MessageThread, \
    ReagentSubscription, SiteSettings, BackupLog, DocumentPermission, ImportTracker, ServiceTier, ServicePrice, \
    BillingRecord, ProtocolStepSuggestionCache, SamplePool, RemoteHost
from cc.permissions import OwnerOrReadOnly, InstrumentUsagePermission, InstrumentViewSetPermission, IsParticipantOrAdmin, IsCoreFacilityPermission
from cc.rq_tasks import transcribe_audio_from_video, transcribe_audio, create_docx, llama_summary, remove_html_tags, \
    ocr_b64_image, export_data, import_data, dry_run_import_data, llama_summary_transcript, export_sqlite, export_instrument_job_metadata, \
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
    MessageRecipientSerializer, MessageThreadSerializer, MessageThreadDetailSerializer, ReagentSubscriptionSerializer, \
    SiteSettingsSerializer, BackupLogSerializer, DocumentPermissionSerializer, SharedDocumentSerializer, \
    UserBasicSerializer, ImportTrackerSerializer, ImportTrackerListSerializer, HistoricalRecordSerializer, \
    ServiceTierSerializer, ServicePriceSerializer, BillingRecordSerializer, SamplePoolSerializer, RemoteHostSerializer
from cc.rq_tasks import analyze_protocol_step_task, analyze_full_protocol_task
from cc.utils import user_metadata, staff_metadata, send_slack_notification
from cc.utils.user_data_import_revised import ImportReverter
from mcp_server.tools.protocol_analyzer import ProtocolAnalyzer


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
        """
        Create a new protocol from URL or manual data.
        
        Supports two creation methods:
        - From URL: Automatically imports protocol data from protocols.io URL
        - Manual: Creates protocol with provided title and description
        
        For manual creation, also creates a default section and step.
        Associates protocol with authenticated user if available.
        
        Request Data:
            url (str): protocols.io URL for automatic import (optional)
            protocol_title (str): Title for manual creation (required if no URL)
            protocol_description (str): Description for manual creation (required if no URL)
            
        Returns:
            Response: Created protocol data with 201 status
        """
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
        """
        Get all sessions associated with this protocol.
        
        Returns sessions linked to the protocol, filtered by user permissions.
        
        Returns:
            Response: List of session data for the protocol
        """
        protocol = self.get_object()
        sessions = protocol.sessions.all()
        user = self.request.user

        if user.is_authenticated:
            data = SessionSerializer(sessions.filter(Q(user=user)|Q(enabled=True)), many=True).data
        else:
            data = SessionSerializer(sessions.filter(enabled=True), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    def get_queryset(self):
        """
        Filter protocols based on user permissions.
        
        Returns protocols that the user owns, are public, or the user has
        been granted viewer/editor access to.
        
        Returns:
            QuerySet: Filtered protocol queryset
        """
        user = self.request.user
        
        # Vaulting logic: exclude vaulted items by default unless include_vaulted=true
        include_vaulted = self.request.query_params.get('include_vaulted', 'false').lower() == 'true'
        vault_filter = Q() if include_vaulted else Q(is_vaulted=False)
        
        if user.is_authenticated:
            permission_filter = Q(user=user)|Q(enabled=True)|Q(viewers=user)|Q(editors=user)
            return ProtocolModel.objects.filter(permission_filter & vault_filter)
        else:
            return ProtocolModel.objects.filter(Q(enabled=True) & vault_filter)

    def get_object(self):
        """
        Get protocol object with permission checks.
        
        Enforces permission-based access control for protocol retrieval.
        Raises PermissionDenied if user lacks access.
        
        Returns:
            ProtocolModel: Protocol instance if user has access
            
        Raises:
            PermissionDenied: If user lacks permission to access protocol
        """
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
        """
        Update protocol with permission checks.
        
        Allows protocol owners and editors to update protocol details.
        Staff users can update any protocol.
        Vaulted protocols cannot be updated.
        
        Request Data:
            protocol_title (str): New protocol title
            protocol_description (str): New protocol description
            enabled (bool): Protocol visibility status (optional)
            
        Returns:
            Response: Updated protocol data
        """
        instance = self.get_object()
        
        # Check if protocol is vaulted - vaulted protocols cannot be updated (unless allowed by settings)
        if hasattr(instance, 'is_vaulted') and instance.is_vaulted:
            from .models import SiteSettings
            site_settings = SiteSettings.get_or_create_default()
            if not site_settings.can_modify_vaulted_object(request.user, 'update'):
                return Response(
                    {'error': 'Vaulted protocols cannot be updated. Please unvault first or contact an administrator.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
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

    def destroy(self, request, *args, **kwargs):
        """
        Delete protocol with vaulting checks.
        
        Vaulted protocols cannot be deleted.
        """
        instance = self.get_object()
        
        # Check if protocol is vaulted - vaulted protocols cannot be deleted (unless allowed by settings)
        if hasattr(instance, 'is_vaulted') and instance.is_vaulted:
            from .models import SiteSettings
            site_settings = SiteSettings.get_or_create_default()
            if not site_settings.can_modify_vaulted_object(request.user, 'delete'):
                return Response(
                    {'error': 'Vaulted protocols cannot be deleted. Please unvault first or contact an administrator.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Check permissions (reuse existing logic from get_object)
        user = request.user
        if not user.is_staff:
            if instance.user != user and not instance.editors.filter(id=user.id).exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def unvault(self, request, pk=None):
        """
        Unvault a protocol, making it accessible in normal queries.
        
        Only the protocol owner or staff can unvault protocols.
        
        Returns:
            Response: Success message with updated protocol data
        """
        instance = self.get_object()
        
        # Check if protocol is actually vaulted
        if not hasattr(instance, 'is_vaulted') or not instance.is_vaulted:
            return Response(
                {'error': 'This protocol is not vaulted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check permissions - only owner or staff can unvault
        user = request.user
        if not user.is_staff and instance.user != user:
            return Response(
                {'error': 'Only the protocol owner or staff can unvault protocols.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Unvault the protocol
        instance.is_vaulted = False
        instance.save()
        
        data = self.get_serializer(instance).data
        return Response({
            'message': 'Protocol unvaulted successfully.',
            'protocol': data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], pagination_class=LimitOffsetPagination)
    def get_user_protocols(self, request):
        """
        Get protocols owned by the authenticated user and optionally shared protocols.
        
        Supports search filtering by title and description.
        Returns paginated results with customizable limit.
        
        Query Parameters:
            search (str): Search term for protocol title/description
            limit (int): Number of protocols per page (default: 5)
            include_vaulted (bool): Include vaulted protocols in results (default: false)
            vaulted_only (bool): Show only vaulted protocols (default: false)
            include_shared (bool): Include protocols shared with user (default: false)
            
        Returns:
            Response: Paginated list of user's protocols
        """
        if self.request.user.is_anonymous:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        user = request.user
        search = request.query_params.get('search', None)
        
        # Apply vaulting logic: exclude vaulted items by default unless include_vaulted=true
        include_vaulted = request.query_params.get('include_vaulted', 'false').lower() == 'true'
        vaulted_only = request.query_params.get('vaulted_only', 'false').lower() == 'true'
        
        if vaulted_only:
            vault_filter = Q(is_vaulted=True)
        elif include_vaulted:
            vault_filter = Q()  # Include both vaulted and non-vaulted
        else:
            vault_filter = Q(is_vaulted=False)  # Exclude vaulted items
        
        # Include shared protocols if requested
        include_shared = request.query_params.get('include_shared', 'false').lower() == 'true'
        
        # Base query: user's own protocols
        protocols_filter = Q(user=user) & vault_filter
        
        # Add shared protocols if requested
        if include_shared:
            shared_filter = (Q(viewers=user) | Q(editors=user)) & vault_filter
            protocols_filter = protocols_filter | shared_filter
        
        protocols = ProtocolModel.objects.filter(protocols_filter).distinct()
        
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
        """
        Create export jobs for protocol or session data.
        
        Supports multiple export formats (docx, tar.gz, sqlite) and types
        (protocol, session, session-sqlite). Exports are processed asynchronously.
        
        Request Data:
            export_type (str): Type of export (protocol, session, session-sqlite)
            format (str): Export format (docx, tar.gz)
            session (int): Session ID for session-based exports
            
        Returns:
            Response: 200 if export job queued successfully
        """
        protocol = self.get_object()
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        if "export_type" in request.data:
            if "session" == self.request.data["export_type"]:
                if "session" in self.request.data:
                    session_id = self.request.data['session']
                    if "format" in self.request.data:
                        if "docx" == self.request.data["format"]:
                            create_docx.delay(protocol.id, session_id, self.request.user.id, custom_id)
                            return Response(status=status.HTTP_200_OK)
                        elif "tar.gz" == self.request.data["format"]:
                            export_data.delay(self.request.user.id, session_ids=[session_id], instance_id=custom_id, export_type="session", format_type="tar.gz")
                            return Response(status=status.HTTP_200_OK)
            elif "protocol" == self.request.data["export_type"]:
                if "format" in self.request.data:
                    if "docx" == self.request.data["format"]:
                        create_docx.delay(protocol.id, None, self.request.user.id, custom_id)
                        return Response(status=status.HTTP_200_OK)
                    elif "tar.gz" == self.request.data["format"]:
                        export_data.delay(self.request.user.id, protocol_ids=[protocol.id], instance_id=custom_id, export_type="protocol", format_type="tar.gz")
                        return Response(status=status.HTTP_200_OK)
            elif "session-sqlite" == self.request.data["export_type"]:
                if "session" in self.request.data:
                    session_id = self.request.data['session']
                    export_sqlite.delay(self.request.user.id, session_id, custom_id)
                    return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def download_temp_file(self, request):
        """
        Download temporary file using signed token.
        
        Uses Django's TimestampSigner for secure temporary file access.
        Token expires after 30 minutes.
        
        Query Parameters:
            token (str): Signed token for file access
            
        Returns:
            Response: File download response with X-Accel-Redirect header
        """
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
        """
        Clone an existing protocol with all its sections, steps, and reagents.
        
        Creates a deep copy of the protocol including all related objects.
        The cloned protocol is owned by the requesting user.
        
        Request Data:
            protocol_title (str): Title for cloned protocol (optional)
            protocol_description (str): Description for cloned protocol (optional)
            
        Returns:
            Response: Created protocol data
        """
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
        """
        Check if a protocol title already exists in the system.
        
        Used for validation before creating new protocols.
        
        Request Data:
            protocol_title (str): Title to check for uniqueness
            
        Returns:
            Response: 409 if title exists, 200 if available
        """
        title = request.data['protocol_title']
        protocol = ProtocolModel.objects.filter(protocol_title=title)
        if protocol.exists():
            return Response(status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_user_role(self, request, pk=None):
        """
        Add user permission role to protocol.
        
        Allows protocol owners to grant viewer or editor access to other users.
        
        Request Data:
            user (str): Username to grant access to
            role (str): Role to grant (viewer or editor)
            
        Returns:
            Response: 200 if role added, 409 if user already has role
        """
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
        """
        Get list of users with editor access to this protocol.
        
        Returns:
            Response: List of users with editor permissions
        """
        protocol = self.get_object()
        data = UserSerializer(protocol.editors.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_viewers(self, request, pk=None):
        """
        Get list of users with viewer access to this protocol.
        
        Returns:
            Response: List of users with viewer permissions
        """
        protocol = self.get_object()
        data = UserSerializer(protocol.viewers.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_user_role(self, request, pk=None):
        """
        Remove user permission role from protocol.
        
        Allows protocol owners to revoke viewer or editor access.
        
        Request Data:
            user (str): Username to revoke access from
            role (str): Role to revoke (viewer or editor)
            
        Returns:
            Response: 200 if role removed successfully
        """
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
        """
        Get all reagents used in this protocol.
        
        Returns:
            Response: List of protocol reagents with quantities
        """
        protocol = self.get_object()
        data = ProtocolReagentSerializer(protocol.reagents.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_tag(self, request, pk=None):
        """
        Add tag to protocol.
        
        Creates new tag if it doesn't exist, then associates it with the protocol.
        
        Request Data:
            tag (str): Tag name to add
            
        Returns:
            Response: Tag data if added, 409 if tag already exists on protocol
        """
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

    @action(detail=True, methods=['post'])
    def suggest_sdrf(self, request, pk=None):
        """
        Generate SDRF suggestions for all steps in a protocol.
        
        Supports both synchronous and asynchronous processing.
        Uses existing ProtocolAnalyzer logic with optional AI enhancement.
        
        Request parameters:
        - use_anthropic (bool): Enable AI-powered analysis
        - use_async (bool): Use async processing with RQ (default: True)
        - anthropic_api_key (str): Optional API key for Anthropic
        
        Returns:
        - Async: task_id and job_id for progress tracking
        - Sync: Aggregated SDRF suggestions and analysis results for all steps
        """
        protocol = self.get_object()
        use_anthropic = request.data.get('use_anthropic', False)
        use_async = request.data.get('use_async', True)
        anthropic_api_key = request.data.get('anthropic_api_key')
        
        # Check if we should use async processing
        if use_async:
            # Use RQ task for async processing
            # Generate unique task ID
            task_id = str(uuid.uuid4())
            
            # Get user ID for WebSocket updates
            user_id = request.user.id if request.user.is_authenticated else None
            
            # Enqueue task using delay syntax
            job = analyze_full_protocol_task.delay(
                task_id=task_id,
                protocol_id=protocol.id,
                use_anthropic=use_anthropic,
                anthropic_api_key=anthropic_api_key,
                user_id=user_id
            )
            
            return Response({
                'success': True,
                'task_id': task_id,
                'job_id': job.id,
                'protocol_id': protocol.id,
                'status': 'queued',
                'message': 'Full protocol SDRF analysis task queued successfully. Use WebSocket for progress updates.'
            }, status=status.HTTP_202_ACCEPTED)
        
        # Synchronous processing (fallback)
        try:
            # Get user token from request
            user_token = None
            if request.user.is_authenticated:
                user_token = str(request.user.id)
            
            # Get API key for AI analysis
            api_key = None
            if use_anthropic:
                api_key = anthropic_api_key or os.getenv('ANTHROPIC_API_KEY')
                if not api_key:
                    use_anthropic = False
            
            # Initialize protocol analyzer with existing logic
            analyzer = ProtocolAnalyzer(
                use_anthropic=use_anthropic,
                anthropic_api_key=api_key
            )
            
            # Use existing logic similar to management command
            steps = protocol.get_step_in_order()
            results = []
            
            # Process each step
            for step_index, step in enumerate(steps, 1):
                try:
                    # Get SDRF suggestions for this step
                    suggestions = analyzer.get_step_sdrf_suggestions(step.id, user_token)
                    
                    if suggestions.get('success'):
                        step_result = {
                            'step_id': step.id,
                            'step_order': step_index,
                            'step_description': step.step_description,
                            'success': True,
                            'sdrf_suggestions': suggestions.get('sdrf_suggestions', {}),
                            'analysis_metadata': suggestions.get('analysis_metadata', {})
                        }
                        results.append(step_result)
                    else:
                        results.append({
                            'step_id': step.id,
                            'step_order': step_index,
                            'step_description': step.step_description,
                            'success': False,
                            'error': suggestions.get('error', 'Unknown error')
                        })
                        
                except Exception as e:
                    results.append({
                        'step_id': step.id,
                        'step_order': step_index,
                        'step_description': step.step_description,
                        'success': False,
                        'error': f'Step processing failed: {str(e)}'
                    })
            
            # Aggregate protocol-level SDRF suggestions
            protocol_sdrf_suggestions = self._aggregate_protocol_suggestions(results)
            
            # Calculate summary statistics
            successful_steps = [r for r in results if r.get('success')]
            total_columns = sum(len(r.get('sdrf_suggestions', {})) for r in successful_steps)
            total_suggestions = sum(
                sum(len(suggestions_list) for suggestions_list in r.get('sdrf_suggestions', {}).values())
                for r in successful_steps
            )
            
            result = {
                'success': True,
                'protocol_id': protocol.id,
                'protocol_title': protocol.protocol_title,
                'total_steps': len(results),
                'successful_steps': len(successful_steps),
                'total_sdrf_columns': total_columns,
                'total_suggestions': total_suggestions,
                'protocol_sdrf_suggestions': protocol_sdrf_suggestions,
                'step_results': results
            }
            
            return Response(result, status=status.HTTP_200_OK)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Protocol SDRF analysis failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _aggregate_protocol_suggestions(self, step_results):
        """Aggregate SDRF suggestions across all protocol steps."""
        aggregated = {}
        
        for step_result in step_results:
            if not step_result.get('success'):
                continue
                
            suggestions = step_result.get('sdrf_suggestions', {})
            for sdrf_column, suggestions_list in suggestions.items():
                if sdrf_column not in aggregated:
                    aggregated[sdrf_column] = []
                
                # Add high-confidence matches
                for suggestion in suggestions_list:
                    if suggestion.get("confidence", 0) >= 0.7:
                        # Check if we already have this ontology term
                        existing = False
                        for existing_suggestion in aggregated[sdrf_column]:
                            if (existing_suggestion.get("ontology_id") == suggestion.get("ontology_id") and 
                                existing_suggestion.get("ontology_type") == suggestion.get("ontology_type")):
                                # Update confidence if this one is higher
                                if suggestion.get("confidence", 0) > existing_suggestion.get("confidence", 0):
                                    existing_suggestion.update(suggestion)
                                existing = True
                                break
                        
                        if not existing:
                            aggregated[sdrf_column].append(suggestion)
        
        # Sort each column by confidence
        for sdrf_column in aggregated:
            aggregated[sdrf_column].sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return aggregated

    @action(detail=True, methods=['get'])
    def cached_sdrf_suggestions(self, request, pk=None):
        """
        Get cached SDRF suggestions for all steps in a protocol.
        
        Query parameters:
        - analyzer_type (str): Filter by analyzer type ('standard_nlp' or 'mcp_claude')
        
        Returns:
        - Aggregated cached suggestions data with metadata
        """
        from cc.serializers import ProtocolStepSuggestionCacheSerializer
        protocol = self.get_object()
        analyzer_type = request.query_params.get('analyzer_type')
        
        try:
            # Get all steps in the protocol
            steps = protocol.get_step_in_order()
            step_ids = [step.id for step in steps]
            
            # Get cached suggestions for all protocol steps
            cache_queryset = ProtocolStepSuggestionCache.objects.filter(step_id__in=step_ids)
            
            if analyzer_type:
                cache_queryset = cache_queryset.filter(analyzer_type=analyzer_type)
            
            cached_suggestions = cache_queryset.order_by('step_id', '-updated_at')
            
            if cached_suggestions.exists():
                # Group by step for easier processing
                suggestions_by_step = {}
                for cache_entry in cached_suggestions:
                    step_id = cache_entry.step_id
                    if step_id not in suggestions_by_step:
                        suggestions_by_step[step_id] = []
                    suggestions_by_step[step_id].append(cache_entry)
                
                # Serialize the cached suggestions
                all_cached_data = []
                for step_id, step_cache_entries in suggestions_by_step.items():
                    step = next((s for s in steps if s.id == step_id), None)
                    if step:
                        step_data = {
                            'step_id': step_id,
                            'step_description': step.step_description,
                            'cached_entries': ProtocolStepSuggestionCacheSerializer(step_cache_entries, many=True).data
                        }
                        all_cached_data.append(step_data)
                
                return Response({
                    'success': True,
                    'protocol_id': protocol.id,
                    'protocol_title': protocol.protocol_title,
                    'total_steps': len(steps),
                    'steps_with_cache': len(suggestions_by_step),
                    'total_cache_entries': cached_suggestions.count(),
                    'cached_suggestions_by_step': all_cached_data
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': True,
                    'protocol_id': protocol.id,
                    'protocol_title': protocol.protocol_title,
                    'total_steps': len(steps),
                    'steps_with_cache': 0,
                    'total_cache_entries': 0,
                    'cached_suggestions_by_step': [],
                    'message': 'No cached suggestions found for any steps in this protocol'
                }, status=status.HTTP_200_OK)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to retrieve cached suggestions: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StepViewSet(ModelViewSet, FilterMixin):
    """
    ViewSet for managing protocol steps.
    
    Provides CRUD operations for protocol steps with proper permission checks.
    Only protocol owners and users with access can view/modify steps.
    
    Supports:
    - Creating new steps within protocol sections
    - Searching and filtering steps
    - Managing step ordering and dependencies
    """
    permission_classes = [OwnerOrReadOnly]
    queryset = ProtocolStep.objects.all()
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['step_description', 'step_section']
    ordering_fields = ['step_description', 'step_section']
    filterset_fields = ['step_description', 'step_section']
    serializer_class = ProtocolStepSerializer

    def get_queryset(self):
        """
        Filter steps based on protocol permissions.
        
        Returns steps from protocols that the user owns or are public.
        
        Returns:
            QuerySet: Filtered protocol steps
        """
        user = self.request.user
        return ProtocolStep.objects.filter(Q(protocol__user=user)|Q(protocol__enabled=True))

    def get_object(self):
        """
        Get step object with permission checks.
        
        Ensures user has access to the step's parent protocol.
        
        Returns:
            ProtocolStep: Step instance if user has access
            
        Raises:
            PermissionDenied: If user lacks permission to access step
        """
        obj = super().get_object()
        user = self.request.user
        if obj.protocol.user == user or obj.protocol.enabled:
            return obj
        else:
            raise PermissionDenied


    def create(self, request, *args, **kwargs):
        """
        Create a new protocol step within a section.
        
        Handles step ordering and insertion into the protocol section.
        Automatically links steps in proper sequence.
        
        Request Data:
            protocol (int): Protocol ID
            step_section (int): Section ID where step belongs
            step_description (str): Step description
            step_duration (int): Step duration in seconds
            step_id (str): Optional step identifier
            
        Returns:
            Response: Created step data
        """
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

    @action(detail=True, methods=['post'])
    def suggest_sdrf(self, request, pk=None):
        """
        Generate SDRF suggestions for a protocol step.
        
        Supports both synchronous and asynchronous processing.
        Uses existing ProtocolAnalyzer logic with optional AI enhancement.
        
        Request parameters:
        - use_anthropic (bool): Enable AI-powered analysis
        - use_async (bool): Use async processing with RQ (default: True)
        - anthropic_api_key (str): Optional API key for Anthropic
        
        Returns:
        - Async: task_id and job_id for progress tracking
        - Sync: SDRF suggestions and analysis results
        """
        step = self.get_object()
        use_anthropic = request.data.get('use_anthropic', False)
        use_async = request.data.get('use_async', True)
        anthropic_api_key = request.data.get('anthropic_api_key')
        
        # Check if we should use async processing
        if use_async:
            # Use RQ task for async processing
            # Generate unique task ID
            task_id = str(uuid.uuid4())
            
            # Get user ID for WebSocket updates
            user_id = request.user.id if request.user.is_authenticated else None
            
            # Enqueue task using delay syntax
            job = analyze_protocol_step_task.delay(
                task_id=task_id,
                step_id=step.id,
                use_anthropic=use_anthropic,
                anthropic_api_key=anthropic_api_key,
                user_id=user_id
            )
            
            return Response({
                'success': True,
                'task_id': task_id,
                'job_id': job.id,
                'step_id': step.id,
                'status': 'queued',
                'message': 'SDRF analysis task queued successfully. Use WebSocket for progress updates.'
            }, status=status.HTTP_202_ACCEPTED)
        
        # Synchronous processing (fallback)
        try:
            # Get user token from request
            user_token = None
            if request.user.is_authenticated:
                user_token = str(request.user.id)
            
            # Get API key for AI analysis
            api_key = None
            if use_anthropic:
                api_key = anthropic_api_key or os.getenv('ANTHROPIC_API_KEY')
                if not api_key:
                    use_anthropic = False
            
            # Initialize protocol analyzer with existing logic
            analyzer = ProtocolAnalyzer(
                use_anthropic=use_anthropic,
                anthropic_api_key=api_key
            )
            
            # Use existing method from management command
            suggestions = analyzer.get_step_sdrf_suggestions(step.id, user_token)
            
            if suggestions.get('success'):
                # Process the suggestions similar to management command
                analysis = analyzer.analyze_protocol_step(step.id, user_token)
                
                # Build the main result using existing patterns
                result = {
                    "success": True,
                    "step_id": step.id,
                    "sdrf_suggestions": suggestions.get("sdrf_suggestions", {}),
                    "analysis_summary": {
                        "total_matches": len(analysis.get('ontology_matches', [])),
                        "high_confidence_matches": analysis.get('analysis_metadata', {}).get('high_confidence_matches', 0),
                        "sdrf_specific_suggestions": sum(len(suggestions_list) for suggestions_list in suggestions.get("sdrf_suggestions", {}).values())
                    },
                    "detailed_analysis": {
                        "extracted_terms": analysis.get("extracted_terms", []),
                        "ontology_matches": analysis.get("ontology_matches", []),
                        "categorized_matches": analysis.get("categorized_matches", {}),
                        "analysis_metadata": analysis.get("analysis_metadata", {})
                    }
                }
                
                # Extract and preserve important fields from the analysis
                analysis_metadata = analysis.get("analysis_metadata", {})
                if "analyzer_type" in analysis_metadata:
                    result["analyzer_type"] = analysis_metadata["analyzer_type"]
                
                # Include Claude analysis if present
                if "claude_analysis" in analysis:
                    result["claude_analysis"] = analysis["claude_analysis"]
                
                # Include enhanced SDRF suggestions if present
                if "sdrf_suggestions_enhanced" in analysis:
                    result["sdrf_suggestions_enhanced"] = analysis["sdrf_suggestions_enhanced"]
                
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(suggestions, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': f'SDRF analysis failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def cached_sdrf_suggestions(self, request, pk=None):
        """
        Get cached SDRF suggestions for a protocol step.
        
        Query parameters:
        - analyzer_type (str): Filter by analyzer type ('standard_nlp' or 'mcp_claude')
        
        Returns:
        - Cached suggestions data with metadata
        """
        from cc.serializers import ProtocolStepSuggestionCacheSerializer
        step = self.get_object()
        analyzer_type = request.query_params.get('analyzer_type')
        
        try:
            # Get cached suggestions
            cache_queryset = ProtocolStepSuggestionCache.objects.filter(step=step)
            
            if analyzer_type:
                cache_queryset = cache_queryset.filter(analyzer_type=analyzer_type)
            
            cached_suggestions = cache_queryset.order_by('-updated_at')
            
            if cached_suggestions.exists():
                serializer = ProtocolStepSuggestionCacheSerializer(cached_suggestions, many=True)
                return Response({
                    'success': True,
                    'step_id': step.id,
                    'cached_suggestions': serializer.data,
                    'total_cache_entries': cached_suggestions.count()
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': True,
                    'step_id': step.id,
                    'cached_suggestions': [],
                    'total_cache_entries': 0,
                    'message': 'No cached suggestions found for this step'
                }, status=status.HTTP_200_OK)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to retrieve cached suggestions: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AnnotationViewSet(ModelViewSet, FilterMixin):
    """
    ViewSet for managing annotations.
    
    Handles various annotation types including text, audio, video, and instrument bookings.
    Supports file uploads and integrates with external services for transcription and AI processing.
    
    Annotation types:
    - text: Basic text annotations
    - audio: Audio recordings with transcription
    - video: Video recordings with transcription
    - instrument: Instrument booking annotations
    - image: Image annotations with OCR
    - maintenance: Maintenance-related annotations
    """
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Annotation.objects.all()
    parser_classes = [MultiPartParser, JSONParser]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['annotation']
    ordering_fields = ['created_at']
    serializer_class = AnnotationSerializer
    filterset_fields = ['step', 'session__unique_id']
    pagination_class = LimitOffsetPagination

    def create(self, request, *args, **kwargs):
        """
        Create a new annotation with file upload support.
        
        Handles various annotation types and triggers background processing
        for audio/video transcription and AI analysis.
        
        Request Data:
            annotation (str): Annotation text content
            annotation_type (str): Type of annotation (text, audio, video, instrument, image, maintenance)
            step (int): Associated protocol step ID (optional)
            session (str): Session unique ID (optional)
            stored_reagent (int): Associated stored reagent ID (optional)
            instrument (int): Instrument ID for booking annotations
            file uploads: Audio/video/image files
            
        Returns:
            Response: Created annotation data
        """
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
            if not instrument.accepts_bookings:
                return Response(
                    {'error': 'This instrument does not accept bookings'},
                    status=status.HTTP_400_BAD_REQUEST
                )
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
        view = request.query_params.get('view', None)

        if annotation.folder and annotation.folder.is_shared_document_folder:
            if not DocumentPermission.user_can_access_annotation_with_folder_inheritance(user, annotation, 'can_download'):
                return Response(status=status.HTTP_403_FORBIDDEN)
        
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
        if view:
            if file_name.endswith(".pdf"):
                content_type = "application/pdf"
                response["Content-Disposition"] = f'inline; filename="{file_name.split("/")[-1]}"'
        else:
            response["Content-Disposition"] = f'attachment; filename="{file_name.split("/")[-1]}"'
        response["X-Accel-Redirect"] = f"/media/{file_name}"
        return response

    def get_object(self):
        obj: Annotation = super().get_object()
        user = self.request.user
        
        # Check if this is a shared document and validate permissions
        if obj.folder and obj.folder.is_shared_document_folder:
            if DocumentPermission.user_can_access_annotation_with_folder_inheritance(user, obj, 'can_view'):
                return obj
            raise PermissionDenied
        
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
        """
        Generate a signed URL token for secure file access.
        
        Creates a time-limited signed token for accessing annotation files.
        Validates user permissions including shared document access rights.
        
        Returns:
            Response: Signed token for file access or 401 if unauthorized
        """
        signer = TimestampSigner()
        annotation = Annotation.objects.get(id=pk)
        user = self.request.user
        
        if annotation.folder and annotation.folder.is_shared_document_folder:
            if not DocumentPermission.user_can_access_annotation_with_folder_inheritance(user, annotation, 'can_view'):
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        
        file = {'file': annotation.file.name, 'id': annotation.id}
        signed_token = signer.sign_object(file)
        if annotation.check_for_right(user, "view"):
            return Response({"signed_token": signed_token}, status=status.HTTP_200_OK)
        return Response(status=status.HTTP_401_UNAUTHORIZED)


    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def download_signed(self, request, *args, **kwargs):
        token = request.query_params.get('token', None)
        if not token:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        signer = TimestampSigner()
        view = request.query_params.get('view', None)
        try:
            data = signer.unsign_object(token, max_age=60*30)
            annotation = Annotation.objects.get(id=data['id'])
            if annotation.file:
                response = HttpResponse(status=200)
                response["Content-Disposition"] = f'attachment; filename="{annotation.file.name.split("/")[-1]}"'
                content_type = "application/octet-stream"
                if annotation.file.name.endswith(".pdf"):
                    content_type = "application/pdf"
                    response["Content-Disposition"] = f'inline; filename="{annotation.file.name.split("/")[-1]}"'
                elif annotation.file.name.endswith(".m4a"):
                    content_type = "audio/mp4"
                    response["Content-Disposition"] = f'inline; filename="{annotation.file.name.split("/")[-1]}"'
                elif annotation.file.name.endswith(".mp3"):
                    content_type = "audio/mpeg"
                    response["Content-Disposition"] = f'inline; filename="{annotation.file.name.split("/")[-1]}"'
                elif annotation.file.name.endswith(".mp4"):
                    content_type = "video/mp4"
                    response["Content-Disposition"] = f'inline; filename="{annotation.file.name.split("/")[-1]}"'
                response["Content-Type"] = content_type
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
        """
        Update session with permission and vaulting checks.
        
        Sessions connected to vaulted protocols cannot be updated.
        """
        instance = self.get_object()
        if instance.user != request.user:
            raise PermissionDenied
        
        # Check if session is connected to any vaulted protocols
        vaulted_protocols = instance.protocols.filter(is_vaulted=True)
        if vaulted_protocols.exists():
            from .models import SiteSettings
            site_settings = SiteSettings.get_or_create_default()
            if not site_settings.can_modify_vaulted_session(request.user, 'update'):
                vaulted_names = [p.protocol_title for p in vaulted_protocols[:3]]  # Show up to 3 names
                protocol_list = ', '.join(vaulted_names)
                if vaulted_protocols.count() > 3:
                    protocol_list += f' and {vaulted_protocols.count() - 3} more'
                
                return Response(
                    {
                        'error': f'Sessions connected to vaulted protocols cannot be updated. '
                                f'Vaulted protocols: {protocol_list}. Please unvault the protocols first or contact an administrator.'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
        
        for i in request.data:
            if i in ['enabled', 'created_at', 'updated_at', 'protocols', 'name', 'started_at', 'ended_at']:
                setattr(instance, i, request.data[i])
        instance.save()
        data = self.get_serializer(instance).data
        return Response(data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        """
        Delete session with vaulting checks.
        
        Sessions connected to vaulted protocols cannot be deleted.
        """
        instance = self.get_object()
        
        # Check if session is connected to any vaulted protocols
        vaulted_protocols = instance.protocols.filter(is_vaulted=True)
        if vaulted_protocols.exists():
            from .models import SiteSettings
            site_settings = SiteSettings.get_or_create_default()
            if not site_settings.can_modify_vaulted_session(request.user, 'delete'):
                vaulted_names = [p.protocol_title for p in vaulted_protocols[:3]]  # Show up to 3 names
                protocol_list = ', '.join(vaulted_names)
                if vaulted_protocols.count() > 3:
                    protocol_list += f' and {vaulted_protocols.count() - 3} more'
                
                return Response(
                    {
                        'error': f'Sessions connected to vaulted protocols cannot be deleted. '
                                f'Vaulted protocols: {protocol_list}. Please unvault the protocols first or contact an administrator.'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
        
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def unvault_protocols(self, request, pk=None):
        """
        Unvault all protocols associated with this session.
        
        Only the session owner or staff can unvault session protocols.
        Each protocol will only be unvaulted if the user has permission.
        
        Returns:
            Response: Summary of unvaulted protocols and any errors
        """
        instance = self.get_object()
        
        # Check permissions - only owner or staff can unvault session protocols
        user = request.user
        if not user.is_staff and instance.user != user:
            return Response(
                {'error': 'Only the session owner or staff can unvault session protocols.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get all vaulted protocols associated with this session
        vaulted_protocols = instance.protocols.filter(is_vaulted=True)
        
        if not vaulted_protocols.exists():
            return Response(
                {'message': 'No vaulted protocols found for this session.'},
                status=status.HTTP_200_OK
            )
        
        unvaulted_protocols = []
        permission_errors = []
        
        for protocol in vaulted_protocols:
            # Check if user can unvault this specific protocol
            if user.is_staff or protocol.user == user:
                protocol.is_vaulted = False
                protocol.save()
                unvaulted_protocols.append({
                    'id': protocol.id,
                    'title': protocol.protocol_title
                })
            else:
                permission_errors.append({
                    'id': protocol.id,
                    'title': protocol.protocol_title,
                    'error': 'Permission denied - only protocol owner or staff can unvault'
                })
        
        response_data = {
            'message': f'Unvaulted {len(unvaulted_protocols)} protocol(s) for session {instance.unique_id}.',
            'unvaulted_protocols': unvaulted_protocols,
            'total_unvaulted': len(unvaulted_protocols)
        }
        
        if permission_errors:
            response_data['permission_errors'] = permission_errors
            response_data['total_permission_errors'] = len(permission_errors)
        
        return Response(response_data, status=status.HTTP_200_OK)

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
        """
        Get sessions owned by the authenticated user and optionally shared sessions.
        
        Query Parameters:
            search (str): Search term for session name/unique_id
            limit (int): Number of sessions per page (default: 5)
            include_vaulted (bool): Include sessions with vaulted protocols (default: false)
            vaulted_only (bool): Show only sessions with vaulted protocols (default: false)
            include_shared (bool): Include sessions shared with user (default: false)
            
        Returns:
            Response: Paginated list of user's sessions
        """
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        user = request.user
        
        # Vaulting logic: exclude sessions associated with vaulted protocols by default unless include_vaulted=true
        include_vaulted = request.query_params.get('include_vaulted', 'false').lower() == 'true'
        vaulted_only = request.query_params.get('vaulted_only', 'false').lower() == 'true'
        
        # Include shared sessions if requested
        include_shared = request.query_params.get('include_shared', 'false').lower() == 'true'
        
        # Base query: user's own sessions
        sessions_filter = Q(user=user)
        
        # Add shared sessions if requested
        if include_shared:
            shared_filter = Q(viewers=user) | Q(editors=user)
            sessions_filter = sessions_filter | shared_filter
        
        sessions = Session.objects.filter(sessions_filter).distinct()
        
        # Apply vault filtering logic
        if vaulted_only:
            sessions = sessions.filter(protocols__is_vaulted=True)
        elif not include_vaulted:
            sessions = sessions.exclude(protocols__is_vaulted=True)
        
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
        started = self.request.query_params.get('started', None)
        print(started)
        if started is not None:
            started = started.lower() == 'true'
            query &= Q(started=started)
        return self.queryset.filter(query)

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
        """
        Export user data in various formats and scopes.

        Supports three export types:
        - Protocol-specific: Export data for specified protocols only
        - Session-specific: Export data for specified sessions only
        - Complete: Export all user data (default)

        Request Data:
            protocol_ids (list): Protocol IDs to export (optional)
            session_ids (list): Session IDs to export (optional)
            format (str): Export format - 'zip' (default), 'tar.gz'

        Returns:
            Response: 200 OK when export task is queued
        """
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)

        protocol_ids = request.data.get('protocol_ids', None)
        session_ids = request.data.get('session_ids', None)
        export_options = request.data.get('export_options', None)
        format_type = "zip"
        if export_options:
            if "format" in export_options:
                format_type = export_options.get('format', 'zip')


        if protocol_ids:
            export_data.delay(
                request.user.id,
                protocol_ids=protocol_ids,
                instance_id=custom_id,
                export_type="protocol",
                format_type=format_type
            )
        elif session_ids:
            export_data.delay(
                request.user.id,
                session_ids=session_ids,
                instance_id=custom_id,
                export_type="session",
                format_type=format_type
            )
        else:
            export_data.delay(
                request.user.id,
                instance_id=custom_id,
                export_type="complete",
                format_type=format_type
            )

        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def import_user_data(self, request):
        """
        Import user data from uploaded archive file.

        Processes a previously uploaded chunked file and imports data
        based on provided import options and file contents.

        Request Data:
            upload_id (str): ID of completed chunked upload
            import_options (dict): Import configuration options (optional)
            storage_object_mappings (dict): Map of original storage IDs to nominated storage IDs (optional)
            bulk_transfer_mode (bool): If True, import everything as-is without user-centric modifications (optional)

        Returns:
            Response: 200 OK when import task is queued
        """
        user = self.request.user
        chunked_upload_id = request.data['upload_id']
        import_options = request.data.get('import_options', None)
        storage_object_mappings = request.data.get('storage_object_mappings', None)
        bulk_transfer_mode = request.data.get('bulk_transfer_mode', False)
        vault_items = request.data.get('vault_items', True)  # Default to True for security
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)
        chunked_upload = ChunkedUpload.objects.get(id=chunked_upload_id, user=user)
        if chunked_upload.completed_at:
            file_path = chunked_upload.file.path
            import_data.delay(user.id, file_path, custom_id, import_options, storage_object_mappings, bulk_transfer_mode, vault_items)
            return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def get_available_storage_objects(self, request):
        """
        Get available storage objects for the current user for import nomination.
        
        Returns:
            Response: List of storage objects the user can access
        """
        user = self.request.user
        
        # Vaulting logic: exclude vaulted items by default unless include_vaulted=true
        include_vaulted = request.query_params.get('include_vaulted', 'false').lower() == 'true'
        vault_filter = Q() if include_vaulted else Q(is_vaulted=False)
        
        # Get storage objects the user owns or has access to via lab groups
        accessible_storage = StorageObject.objects.filter(
            (Q(user=user) | Q(access_lab_groups__users=user)) & vault_filter
        ).distinct().values(
            'id', 'object_name', 'object_type', 'object_description'
        )
        
        return Response({
            'storage_objects': list(accessible_storage)
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def dry_run_import_user_data(self, request):
        """
        Perform a dry run analysis of user data import without making any changes.
        Returns a detailed report of what would be imported.
        """
        user = self.request.user
        chunked_upload_id = request.data['upload_id']
        import_options = request.data.get('import_options', None)
        bulk_transfer_mode = request.data.get('bulk_transfer_mode', False)
        custom_id = self.request.META.get('HTTP_X_CUPCAKE_INSTANCE_ID', None)

        try:
            chunked_upload = ChunkedUpload.objects.get(id=chunked_upload_id, user=user)
        except ChunkedUpload.DoesNotExist:
            return Response(
                {"error": "Upload not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if chunked_upload.completed_at:
            # get completed file path
            file_path = chunked_upload.file.path
            dry_run_import_data.delay(user.id, file_path, custom_id, import_options, bulk_transfer_mode)
            return Response({
                "message": "Dry run analysis started",
                "instance_id": custom_id
            }, status=status.HTTP_200_OK)

        return Response(
            {"error": "Upload not completed yet"},
            status=status.HTTP_400_BAD_REQUEST
        )

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
        can_perform_ms_analysis = request.query_params.get('can_perform_ms_analysis', None)
        can_perform_ms_analysis = True if can_perform_ms_analysis == "true" else False
        if can_perform_ms_analysis:
            lab_groups = lab_groups.filter(can_perform_ms_analysis=True)
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
            user.is_active = True
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
        lab_group = request.data.get('lab_group', None)
        if User.objects.filter(email=email).exists():
            return Response({'error': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)
        signer = TimestampSigner()
        payload = {
            'email': email,
        }
        if lab_group:
            payload['lab_group'] = lab_group

        token = signer.sign(dumps(payload))
        return Response({'token': token}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def generate_signup_token_and_send_email(self, request):
        if not request.user.is_staff:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        email = request.data.get('email')
        lab_group = request.data.get('lab_group', None)
        if User.objects.filter(email=email).exists():
            return Response({'error': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)
        signer = TimestampSigner()
        payload = {
            'email': email
        }
        if lab_group:
            payload['lab_group'] = lab_group

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
        """
        Get current authenticated user's profile information.

        Returns:
            Response: User profile data including username, email, and staff status
        """
        user = request.user
        data = UserSerializer(user).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def user_activity_summary(self, request):
        """
        Get comprehensive summary of user's activity across the platform.

        Returns activity counts across all major platform features including
        total resource counts and recent activity over the last 30 days.

        Returns:
            Response: Activity summary containing:
                - total_counts: Overall resource counts (protocols, sessions, annotations, projects, stored_reagents)
                - recent_activity: Activity counts for last 30 days
                - lab_groups: Lab group membership statistics
        """
        user = request.user

        protocols_count = ProtocolModel.objects.filter(user=user).count()
        sessions_count = Session.objects.filter(user=user).count()
        annotations_count = Annotation.objects.filter(user=user).count()
        projects_count = Project.objects.filter(owner=user).count()

        thirty_days_ago = datetime.now() - timedelta(days=30)

        recent_protocols = ProtocolModel.objects.filter(
            user=user,
            protocol_created_on__gte=thirty_days_ago
        ).count()
        recent_sessions = Session.objects.filter(
            user=user,
            created_at__gte=thirty_days_ago
        ).count()
        recent_annotations = Annotation.objects.filter(
            user=user,
            created_at__gte=thirty_days_ago
        ).count()

        stored_reagents_count = StoredReagent.objects.filter(
            user=user
        ).count()

        activity_summary = {
            'total_counts': {
                'protocols': protocols_count,
                'sessions': sessions_count,
                'annotations': annotations_count,
                'projects': projects_count,
                'stored_reagents': stored_reagents_count,
            },
            'recent_activity': {
                'protocols_last_30_days': recent_protocols,
                'sessions_last_30_days': recent_sessions,
                'annotations_last_30_days': recent_annotations,
            },
            'lab_groups': {
                'member_of': user.lab_groups.count(),
                'managing': user.managed_lab_groups.count(),
            }
        }

        return Response(activity_summary, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def search_users(self, request):
        """
        Enhanced user search with multiple filtering criteria.

        Supports text search across username, first name, last name, and email,
        plus filtering by lab group membership, user role, and activity status.

        Query Parameters:
            q (str): Text search query across user fields
            lab_group (int): Filter by lab group ID membership
            role (str): Filter by role - 'staff' or 'regular'
            active (bool): Filter for active users only (default: true)

        Returns:
            Response: Paginated list of users matching search criteria
        """
        query = request.query_params.get('q', '')
        lab_group_id = request.query_params.get('lab_group', None)
        role = request.query_params.get('role', None)
        active_only = request.query_params.get('active', 'true').lower() == 'true'

        queryset = User.objects.all()

        if query:
            queryset = queryset.filter(
                Q(username__icontains=query) |
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(email__icontains=query)
            )

        if lab_group_id:
            try:
                lab_group = LabGroup.objects.get(id=lab_group_id)
                queryset = queryset.filter(lab_groups=lab_group)
            except LabGroup.DoesNotExist:
                return Response(
                    {'error': 'Lab group not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

        if role == 'staff':
            queryset = queryset.filter(is_staff=True)
        elif role == 'regular':
            queryset = queryset.filter(is_staff=False)

        if active_only:
            thirty_days_ago = datetime.now() - timedelta(days=30)
            active_user_ids = set()

            active_user_ids.update(
                Session.objects.filter(created_at__gte=thirty_days_ago)
                .values_list('user_id', flat=True)
            )
            active_user_ids.update(
                ProtocolModel.objects.filter(protocol_created_on__gte=thirty_days_ago)
                .values_list('user_id', flat=True)
            )
            active_user_ids.update(
                Annotation.objects.filter(created_at__gte=thirty_days_ago)
                .values_list('user_id', flat=True)
            )

            queryset = queryset.filter(id__in=active_user_ids)

        paginator = LimitOffsetPagination()
        paginator.default_limit = 20
        paginated_users = paginator.paginate_queryset(queryset, request)
        if request.user.is_staff:
            return paginator.get_paginated_response(
                UserSerializer(paginated_users, many=True).data
            )
        return paginator.get_paginated_response(
            UserBasicSerializer(paginated_users, many=True).data
        )

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def user_statistics(self, request, pk=None):
        """
        Get detailed statistics for a specific user (staff only or own profile)
        """
        try:
            target_user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Permission check: staff can view any user, users can only view themselves
        if not request.user.is_staff and request.user != target_user:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Time ranges for statistics
        now = datetime.now()
        last_week = now - timedelta(days=7)
        last_month = now - timedelta(days=30)
        last_year = now - timedelta(days=365)

        # Protocol statistics
        protocol_stats = {
            'total': ProtocolModel.objects.filter(user=target_user).count(),
            'enabled': ProtocolModel.objects.filter(user=target_user, enabled=True).count(),
            'last_week': ProtocolModel.objects.filter(
                user=target_user, protocol_created_on__gte=last_week
            ).count(),
            'last_month': ProtocolModel.objects.filter(
                user=target_user, protocol_created_on__gte=last_month
            ).count(),
        }

        # Session statistics
        session_stats = {
            'total': Session.objects.filter(user=target_user).count(),
            'enabled': Session.objects.filter(user=target_user, enabled=True).count(),
            'last_week': Session.objects.filter(
                user=target_user, created_at__gte=last_week
            ).count(),
            'last_month': Session.objects.filter(
                user=target_user, created_at__gte=last_month
            ).count(),
        }

        # Annotation statistics
        annotation_stats = {
            'total': Annotation.objects.filter(user=target_user).count(),
            'with_files': Annotation.objects.filter(
                user=target_user, file__isnull=False
            ).exclude(file='').count(),
            'last_week': Annotation.objects.filter(
                user=target_user, created_at__gte=last_week
            ).count(),
            'last_month': Annotation.objects.filter(
                user=target_user, created_at__gte=last_month
            ).count(),
        }

        # Project statistics
        project_stats = {
            'owned': Project.objects.filter(owner=target_user).count(),
            'last_month': Project.objects.filter(
                owner=target_user, created_at__gte=last_month
            ).count(),
        }

        # Lab group participation
        lab_group_stats = {
            'member_of': target_user.lab_groups.count(),
            'managing': target_user.managed_lab_groups.count(),
        }

        # Storage statistics
        storage_stats = {
            'stored_reagents': StoredReagent.objects.filter(user=target_user).count(),
            'storage_objects': StorageObject.objects.filter(user=target_user).count(),
        }

        statistics = {
            'user_info': {
                'id': target_user.id,
                'username': target_user.username,
                'full_name': f"{target_user.first_name} {target_user.last_name}".strip(),
                'email': target_user.email,
                'is_staff': target_user.is_staff,
                'date_joined': target_user.date_joined,
                'last_login': target_user.last_login,
            },
            'protocols': protocol_stats,
            'sessions': session_stats,
            'annotations': annotation_stats,
            'projects': project_stats,
            'lab_groups': lab_group_stats,
            'storage': storage_stats,
        }

        return Response(statistics, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def user_dashboard_data(self, request):
        """
        Get comprehensive dashboard data for current user
        """
        user = request.user

        # Recent activity
        last_week = datetime.now() - timedelta(days=7)

        # Get recent items
        recent_protocols = ProtocolModel.objects.filter(
            user=user, protocol_created_on__gte=last_week
        ).order_by('-protocol_created_on')[:5]

        recent_sessions = Session.objects.filter(
            user=user, created_at__gte=last_week
        ).order_by('-created_at')[:5]

        recent_annotations = Annotation.objects.filter(
            user=user, created_at__gte=last_week
        ).order_by('-created_at')[:5]

        # Lab groups with member counts
        lab_groups_data = []
        for lab_group in user.lab_groups.all():
            lab_groups_data.append({
                'id': lab_group.id,
                'name': lab_group.name,
                'member_count': lab_group.users.count(),
                'can_perform_ms_analysis': getattr(lab_group, 'can_perform_ms_analysis', False),
            })

        dashboard_data = {
            'user_info': {
                'username': user.username,
                'full_name': f"{user.first_name} {user.last_name}".strip(),
                'email': user.email,
                'is_staff': user.is_staff,
            },
            'quick_stats': {
                'total_protocols': ProtocolModel.objects.filter(user=user).count(),
                'total_sessions': Session.objects.filter(user=user).count(),
                'total_annotations': Annotation.objects.filter(user=user).count(),
                'lab_groups_count': user.lab_groups.count(),
            },
            'recent_activity': {
                'protocols': [{
                    'id': p.id,
                    'title': p.protocol_title,
                    'created': p.protocol_created_on,
                } for p in recent_protocols],
                'sessions': [{
                    'id': s.id,
                    'name': s.name,
                    'created': s.created_at,
                } for s in recent_sessions],
                'annotations': [{
                    'id': a.id,
                    'annotation': a.annotation[:50] + '...' if len(a.annotation) > 50 else a.annotation,
                    'created': a.created_at,
                } for a in recent_annotations],
            },
            'lab_groups': lab_groups_data,
        }

        return Response(dashboard_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def bulk_user_permissions_check(self, request):
        """
        Check permissions for multiple users and resources at once
        """
        user_ids = request.data.get('user_ids', [])
        resource_type = request.data.get('resource_type')  # 'protocol', 'session', 'annotation'
        resource_ids = request.data.get('resource_ids', [])

        if not user_ids or not resource_type or not resource_ids:
            return Response(
                {'error': 'user_ids, resource_type, and resource_ids are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Only staff can check other users' permissions
        if not request.user.is_staff:
            user_ids = [request.user.id]

        users = User.objects.filter(id__in=user_ids)
        permission_matrix = []

        for user in users:
            user_permissions = {
                'user_id': user.id,
                'username': user.username,
                'permissions': []
            }

            if resource_type == 'protocol':
                protocols = ProtocolModel.objects.filter(id__in=resource_ids)
                for protocol in protocols:
                    permission = {
                        'resource_id': protocol.id,
                        'edit': False,
                        'view': False,
                        'delete': False
                    }

                    if protocol.user == user:
                        permission.update({'edit': True, 'view': True, 'delete': True})
                    elif user in protocol.editors.all():
                        permission.update({'edit': True, 'view': True})
                    elif user in protocol.viewers.all():
                        permission['view'] = True

                    if protocol.enabled:
                        permission['view'] = True

                    user_permissions['permissions'].append(permission)

            elif resource_type == 'session':
                sessions = Session.objects.filter(id__in=resource_ids)
                for session in sessions:
                    permission = {
                        'resource_id': session.id,
                        'edit': False,
                        'view': False,
                        'delete': False
                    }

                    if session.user == user:
                        permission.update({'edit': True, 'view': True, 'delete': True})
                    elif user in session.editors.all():
                        permission.update({'edit': True, 'view': True})
                    elif user in session.viewers.all():
                        permission['view'] = True

                    if session.enabled:
                        permission['view'] = True

                    user_permissions['permissions'].append(permission)

            permission_matrix.append(user_permissions)

        return Response(permission_matrix, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def user_preferences(self, request):
        """
        Get user preferences (can be extended to include custom settings)
        """
        user = request.user

        # For now, return basic user settings that could be considered preferences
        preferences = {
            'profile': {
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
            },
            'lab_settings': {
                'default_lab_groups': [group.id for group in user.lab_groups.all()],
                'managed_lab_groups': [group.id for group in user.managed_lab_groups.all()],
            },
            'permissions': {
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
            }
        }

        return Response(preferences, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def deactivate_user(self, request):
        """
        Deactivate a user account (staff only)
        """
        if not request.user.is_staff:
            return Response(
                {'error': 'Only staff can deactivate users'},
                status=status.HTTP_403_FORBIDDEN
            )

        user_id = request.data.get('user_id')
        reason = request.data.get('reason', '')

        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Prevent deactivating superusers or self
        if target_user.is_superuser:
            return Response(
                {'error': 'Cannot deactivate superuser accounts'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if target_user == request.user:
            return Response(
                {'error': 'Cannot deactivate your own account'},
                status=status.HTTP_400_BAD_REQUEST
            )

        target_user.is_active = False
        target_user.save()

        return Response(
            {'message': f'User {target_user.username} has been deactivated'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def reactivate_user(self, request):
        """
        Reactivate a user account (staff only)
        """
        if not request.user.is_staff:
            return Response(
                {'error': 'Only staff can reactivate users'},
                status=status.HTTP_403_FORBIDDEN
            )

        user_id = request.data.get('user_id')

        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        target_user.is_active = True
        target_user.save()

        # Log the reactivation
        print(f"User {target_user.username} reactivated by {request.user.username}")

        return Response(
            {'message': f'User {target_user.username} has been reactivated'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def user_lab_group_management(self, request):
        """
        Get lab groups where user has management permissions
        """
        user = request.user

        # Lab groups user manages
        managed_groups = user.managed_lab_groups.all()

        # Lab groups user is member of
        member_groups = user.lab_groups.all()

        # For each managed group, get member details
        managed_groups_data = []
        for group in managed_groups:
            group_data = {
                'id': group.id,
                'name': group.name,
                'description': getattr(group, 'description', ''),
                'can_perform_ms_analysis': getattr(group, 'can_perform_ms_analysis', False),
                'member_count': group.users.count(),
                'members': [{
                    'id': member.id,
                    'username': member.username,
                    'full_name': f"{member.first_name} {member.last_name}".strip(),
                    'email': member.email,
                    'is_staff': member.is_staff,
                } for member in group.users.all()]
            }
            managed_groups_data.append(group_data)

        # Basic info for member groups
        member_groups_data = [{
            'id': group.id,
            'name': group.name,
            'description': getattr(group, 'description', ''),
            'is_professional': getattr(group, 'is_professional', False),
            'member_count': group.users.count(),
        } for group in member_groups]

        lab_group_info = {
            'managed_groups': managed_groups_data,
            'member_groups': member_groups_data,
            'summary': {
                'managing_count': len(managed_groups_data),
                'member_count': len(member_groups_data),
                'total_managed_members': sum(group['member_count'] for group in managed_groups_data),
            }
        }

        return Response(lab_group_info, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def platform_analytics(self, request):
        """
        Get platform-wide analytics (staff only)
        """
        if not request.user.is_staff:
            return Response(
                {'error': 'Only staff can access platform analytics'},
                status=status.HTTP_403_FORBIDDEN
            )

        # User statistics
        total_users = User.objects.count()
        active_users = User.objects.filter(is_active=True).count()
        staff_users = User.objects.filter(is_staff=True).count()

        # Activity in last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)

        recent_users = User.objects.filter(date_joined__gte=thirty_days_ago).count()

        # Resource counts
        total_protocols = ProtocolModel.objects.count()
        total_sessions = Session.objects.count()
        total_annotations = Annotation.objects.count()
        total_projects = Project.objects.count()
        total_lab_groups = LabGroup.objects.count()

        # Recent activity
        recent_protocols = ProtocolModel.objects.filter(
            protocol_created_on__gte=thirty_days_ago
        ).count()
        recent_sessions = Session.objects.filter(
            created_at__gte=thirty_days_ago
        ).count()
        recent_annotations = Annotation.objects.filter(
            created_at__gte=thirty_days_ago
        ).count()

        # Top active users (by recent activity)
        active_user_data = []
        for user in User.objects.filter(is_active=True)[:10]:
            user_activity = {
                'id': user.id,
                'username': user.username,
                'protocols': ProtocolModel.objects.filter(user=user).count(),
                'sessions': Session.objects.filter(user=user).count(),
                'annotations': Annotation.objects.filter(user=user).count(),
            }
            user_activity['total_activity'] = (
                user_activity['protocols'] +
                user_activity['sessions'] +
                user_activity['annotations']
            )
            active_user_data.append(user_activity)

        # Sort by total activity
        active_user_data.sort(key=lambda x: x['total_activity'], reverse=True)

        analytics = {
            'users': {
                'total': total_users,
                'active': active_users,
                'staff': staff_users,
                'new_last_30_days': recent_users,
            },
            'resources': {
                'protocols': total_protocols,
                'sessions': total_sessions,
                'annotations': total_annotations,
                'projects': total_projects,
                'lab_groups': total_lab_groups,
            },
            'recent_activity': {
                'protocols_last_30_days': recent_protocols,
                'sessions_last_30_days': recent_sessions,
                'annotations_last_30_days': recent_annotations,
            },
            'top_active_users': active_user_data[:5],
        }

        return Response(analytics, status=status.HTTP_200_OK)


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

    def get_queryset(self):
        # Vaulting logic: exclude vaulted items by default unless include_vaulted=true
        include_vaulted = self.request.query_params.get('include_vaulted', 'false').lower() == 'true'
        if not include_vaulted:
            return Tag.objects.filter(is_vaulted=False)
        return Tag.objects.all()

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
        query = Q(owner=user)
        
        # Vaulting logic: exclude vaulted items by default unless include_vaulted=true
        include_vaulted = self.request.query_params.get('include_vaulted', 'false').lower() == 'true'
        if not include_vaulted:
            query &= Q(is_vaulted=False)
        
        return Project.objects.filter(query)

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

    @action(detail=True, methods=['get'])
    def step_metadata(self, request, pk=None):
        """
        Retrieve annotated metadata information for all protocol steps within this project.
        
        Query Parameters:
        - metadata_name (str): Filter by metadata column name (optional)
        - annotation_type (str): Filter by annotation type (optional)
        - step_id (int): Filter by specific step ID (optional)
        
        Returns:
        - List of protocol steps with their associated metadata annotations
        """
        project = self.get_object()
        
        # Get all protocol steps associated with this project through instrument jobs
        instrument_jobs = project.instrument_jobs.all()
        protocol_ids = instrument_jobs.values_list('protocol_id', flat=True).distinct()
        
        # Get all steps from protocols used in this project
        steps = ProtocolStep.objects.filter(
            protocol_id__in=protocol_ids
        ).select_related('protocol').prefetch_related(
            'annotations__metadata_columns'
        )
        
        # Apply filters
        metadata_name = request.query_params.get('metadata_name')
        annotation_type = request.query_params.get('annotation_type')
        step_id = request.query_params.get('step_id')
        
        if step_id:
            steps = steps.filter(id=step_id)
        
        if annotation_type:
            steps = steps.filter(annotations__annotation_type=annotation_type)
        
        # Build response data
        result = []
        for step in steps:
            step_data = {
                'step_id': step.id,
                'step_description': step.step_description,
                'protocol_id': step.protocol.id,
                'protocol_title': step.protocol.protocol_title,
                'annotations': []
            }
            
            # Get annotations with metadata
            annotations = step.annotations.filter(annotation_type='metadata')
            
            for annotation in annotations:
                metadata_columns = annotation.metadata_columns.all()
                
                # Filter by metadata name if specified
                if metadata_name:
                    metadata_columns = metadata_columns.filter(name__icontains=metadata_name)
                
                if metadata_columns.exists():
                    annotation_data = {
                        'annotation_id': annotation.id,
                        'annotation_name': annotation.annotation_name,
                        'annotation_type': annotation.annotation_type,
                        'created_at': annotation.created_at,
                        'updated_at': annotation.updated_at,
                        'metadata_columns': []
                    }
                    
                    for metadata_column in metadata_columns:
                        metadata_data = {
                            'id': metadata_column.id,
                            'name': metadata_column.name,
                            'type': metadata_column.type,
                            'value': metadata_column.value,
                            'column_position': metadata_column.column_position,
                            'mandatory': metadata_column.mandatory,
                            'hidden': metadata_column.hidden,
                            'readonly': metadata_column.readonly,
                            'created_at': metadata_column.created_at,
                            'updated_at': metadata_column.updated_at
                        }
                        annotation_data['metadata_columns'].append(metadata_data)
                    
                    step_data['annotations'].append(annotation_data)
            
            # Only include steps that have metadata annotations
            if step_data['annotations']:
                result.append(step_data)
        
        return Response({
            'project_id': project.id,
            'project_name': project.project_name,
            'steps_with_metadata': result,
            'total_steps': len(result)
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def unvault(self, request, pk=None):
        """
        Unvault a project, making it accessible in normal queries.
        
        Only the project owner or staff can unvault projects.
        
        Returns:
            Response: Success message with updated project data
        """
        instance = self.get_object()
        
        # Check if project is actually vaulted
        if not hasattr(instance, 'is_vaulted') or not instance.is_vaulted:
            return Response(
                {'error': 'This project is not vaulted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check permissions - only owner or staff can unvault
        user = request.user
        if not user.is_staff and instance.owner != user:
            return Response(
                {'error': 'Only the project owner or staff can unvault projects.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Unvault the project
        instance.is_vaulted = False
        instance.save()
        
        data = self.get_serializer(instance).data
        return Response({
            'message': 'Project unvaulted successfully.',
            'project': data
        }, status=status.HTTP_200_OK)

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

    @action(detail=True, methods=['get'])
    def sdrf_metadata_collection(self, request, pk=None):
        """
        Collect all SDRF metadata columns used across a project.
        This includes metadata from:
        - Protocol step annotations
        - Session annotations  
        - Stored reagent annotations
        
        Query Parameters:
        - metadata_name: Filter by specific metadata column name(s). Can be comma-separated for multiple names.
        - unique_values_only: If true, returns only unique values for the filtered metadata columns.
        """
        project = self.get_object()
        
        # Check permissions
        print(f"SDRF Collection Debug: project.owner={project.owner}, request.user={request.user}")
        if project.owner != request.user:
            return Response(
                {'error': 'You do not have permission to access this project'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Parse query parameters
        metadata_name_filter = request.query_params.get('metadata_name', '')
        unique_values_only = request.query_params.get('unique_values_only', '').lower() == 'true'
        
        # Process metadata name filter
        filter_names = []
        if metadata_name_filter:
            filter_names = [name.strip() for name in metadata_name_filter.split(',') if name.strip()]
        
        # Helper function to check if metadata should be included
        def should_include_metadata(metadata_name):
            if not filter_names:
                return True
            return any(filter_name.lower() in metadata_name.lower() for filter_name in filter_names)
        
        # Helper function to process metadata
        def process_metadata(metadata, source_info=None):
            if not should_include_metadata(metadata.name):
                return False
                
            if unique_values_only and filter_names:
                # Unique values mode - group by metadata name (not name_type combination)
                base_name = metadata.name
                if base_name not in metadata_collection['metadata_columns']:
                    metadata_collection['metadata_columns'][base_name] = {
                        'name': metadata.name,
                        'types': {},  # Track different types for this metadata name
                        'unique_values': set(),
                        'value_count': 0
                    }
                
                # Track the type
                if metadata.type not in metadata_collection['metadata_columns'][base_name]['types']:
                    metadata_collection['metadata_columns'][base_name]['types'][metadata.type] = 0
                metadata_collection['metadata_columns'][base_name]['types'][metadata.type] += 1
                
                if metadata.value:  # Only add non-empty values
                    metadata_collection['metadata_columns'][base_name]['unique_values'].add(metadata.value)
                    metadata_collection['metadata_columns'][base_name]['value_count'] += 1
            else:
                # Standard mode - add to unique columns collection
                column_key = f"{metadata.name}_{metadata.type}"
                if column_key not in metadata_collection['unique_metadata_columns']:
                    metadata_collection['unique_metadata_columns'][column_key] = {
                        'name': metadata.name,
                        'type': metadata.type,
                        'occurrences': 0,
                        'sources': []
                    }
                
                metadata_collection['unique_metadata_columns'][column_key]['occurrences'] += 1
                if source_info:
                    metadata_collection['unique_metadata_columns'][column_key]['sources'].append(source_info)
            
            return True
        
        # Initialize response structure based on mode
        if unique_values_only and filter_names:
            # For unique values mode, use a simpler structure
            metadata_collection = {
                'project_id': project.id,
                'project_name': project.project_name,
                'filter_applied': filter_names,
                'unique_values_only': True,
                'metadata_columns': {},
                'statistics': {
                    'filtered_columns_count': 0,
                    'total_unique_values': 0
                }
            }
        else:
            # Standard full collection mode
            metadata_collection = {
                'project_id': project.id,
                'project_name': project.project_name,
                'filter_applied': filter_names if filter_names else None,
                'unique_values_only': False,
                'metadata_sources': {
                    'protocol_step_annotations': [],
                    'session_annotations': [],
                    'stored_reagent_annotations': []
                },
                'unique_metadata_columns': {},
                'statistics': {
                    'total_metadata_columns': 0,
                    'unique_column_names': 0,
                    'sources_count': {
                        'protocol_steps': 0,
                        'sessions': 0,
                        'stored_reagents': 0
                    }
                }
            }
        
        try:
            print(f"SDRF Collection Debug: Starting collection for project {project.id}")
            # Get all sessions in this project
            project_sessions = project.sessions.all()
            print(f"SDRF Collection Debug: Found {project_sessions.count()} sessions")
            
            # 1. Collect metadata from protocol step annotations
            for session in project_sessions:
                for annotation in session.annotations.all():
                    if annotation.step:  # This is a protocol step annotation
                        step_metadata = annotation.metadata_columns.all()
                        if step_metadata.exists():
                            if unique_values_only and filter_names:
                                # Unique values mode - collect only values for filtered columns
                                for metadata in step_metadata:
                                    process_metadata(metadata)
                            else:
                                # Standard mode - collect full details
                                step_data = {
                                    'session_id': session.id,
                                    'session_name': session.name,
                                    'step_id': annotation.step.id,
                                    'annotation_id': annotation.id,
                                    'annotation_type': annotation.annotation_type,
                                    'metadata_columns': []
                                }
                                
                                for metadata in step_metadata:
                                    source_info = {
                                        'type': 'protocol_step',
                                        'session_id': session.id,
                                        'step_id': annotation.step.id,
                                        'annotation_id': annotation.id
                                    }
                                    
                                    if process_metadata(metadata, source_info):
                                        metadata_info = {
                                            'id': metadata.id,
                                            'name': metadata.name,
                                            'type': metadata.type,
                                            'value': metadata.value,
                                            'column_position': metadata.column_position,
                                            'mandatory': metadata.mandatory,
                                            'hidden': metadata.hidden,
                                            'auto_generated': metadata.auto_generated,
                                            'readonly': metadata.readonly,
                                            'modifiers': metadata.modifiers,
                                            'created_at': metadata.created_at,
                                            'updated_at': metadata.updated_at
                                        }
                                        step_data['metadata_columns'].append(metadata_info)
                                
                                if step_data['metadata_columns']:
                                    metadata_collection['metadata_sources']['protocol_step_annotations'].append(step_data)
                                    metadata_collection['statistics']['sources_count']['protocol_steps'] += 1
            
            # 2. Collect metadata from session annotations (not linked to specific steps)
            for session in project_sessions:
                for annotation in session.annotations.filter(step__isnull=True):
                    session_metadata = annotation.metadata_columns.all()
                    if session_metadata.exists():
                        session_data = {
                            'session_id': session.id,
                            'session_name': session.name,
                            'annotation_id': annotation.id,
                            'annotation_type': annotation.annotation_type,
                            'metadata_columns': []
                        }
                        
                        for metadata in session_metadata:
                            metadata_info = {
                                'id': metadata.id,
                                'name': metadata.name,
                                'type': metadata.type,
                                'value': metadata.value,
                                'column_position': metadata.column_position,
                                'mandatory': metadata.mandatory,
                                'hidden': metadata.hidden,
                                'auto_generated': metadata.auto_generated,
                                'readonly': metadata.readonly,
                                'modifiers': metadata.modifiers,
                                'created_at': metadata.created_at,
                                'updated_at': metadata.updated_at
                            }
                            session_data['metadata_columns'].append(metadata_info)
                            
                            # Add to unique columns collection
                            column_key = f"{metadata.name}_{metadata.type}"
                            if column_key not in metadata_collection['unique_metadata_columns']:
                                metadata_collection['unique_metadata_columns'][column_key] = {
                                    'name': metadata.name,
                                    'type': metadata.type,
                                    'occurrences': 0,
                                    'sources': []
                                }
                            
                            metadata_collection['unique_metadata_columns'][column_key]['occurrences'] += 1
                            metadata_collection['unique_metadata_columns'][column_key]['sources'].append({
                                'type': 'session_annotation',
                                'session_id': session.id,
                                'annotation_id': annotation.id
                            })
                        
                        if session_data['metadata_columns']:
                            metadata_collection['metadata_sources']['session_annotations'].append(session_data)
                            metadata_collection['statistics']['sources_count']['sessions'] += 1
            
            # 3. Collect metadata from stored reagents used in project sessions
            stored_reagents_with_metadata = set()
            for session in project_sessions:
                # Get stored reagents from session annotations
                for annotation in session.annotations.all():
                    if annotation.stored_reagent:
                        stored_reagents_with_metadata.add(annotation.stored_reagent.id)
                
                # Also check if any protocol steps in this session reference stored reagents through reagent actions
                for protocol in session.protocols.all():
                    for step in protocol.steps.all():
                        for step_reagent in step.reagents.all():
                            # Get reagent actions for this step reagent
                            for reagent_action in step_reagent.reagent_actions.all():
                                if reagent_action.reagent:  # reagent_action.reagent is a StoredReagent
                                    stored_reagents_with_metadata.add(reagent_action.reagent.id)
            
            # Collect metadata from identified stored reagents
            for reagent_id in stored_reagents_with_metadata:
                try:
                    stored_reagent = StoredReagent.objects.get(id=reagent_id)
                    reagent_metadata = stored_reagent.metadata_columns.all()
                    
                    if reagent_metadata.exists():
                        reagent_data = {
                            'stored_reagent_id': stored_reagent.id,
                            'reagent_name': stored_reagent.reagent.name if stored_reagent.reagent else 'Unknown',
                            'storage_location': str(stored_reagent.storage_object) if stored_reagent.storage_object else 'Unknown',
                            'metadata_columns': []
                        }
                        
                        for metadata in reagent_metadata:
                            if unique_values_only and filter_names:
                                # In unique values mode, use the helper function
                                process_metadata(metadata)
                            else:
                                # Standard mode - collect full details
                                metadata_info = {
                                    'id': metadata.id,
                                    'name': metadata.name,
                                    'type': metadata.type,
                                    'value': metadata.value,
                                    'column_position': metadata.column_position,
                                    'mandatory': metadata.mandatory,
                                    'hidden': metadata.hidden,
                                    'auto_generated': metadata.auto_generated,
                                    'readonly': metadata.readonly,
                                    'modifiers': metadata.modifiers,
                                    'created_at': metadata.created_at,
                                    'updated_at': metadata.updated_at
                                }
                                reagent_data['metadata_columns'].append(metadata_info)
                                
                                # Use helper function for consistent processing
                                source_info = {
                                    'type': 'stored_reagent',
                                    'stored_reagent_id': stored_reagent.id
                                }
                                process_metadata(metadata, source_info)
                        
                        if reagent_data['metadata_columns']:
                            metadata_collection['metadata_sources']['stored_reagent_annotations'].append(reagent_data)
                            metadata_collection['statistics']['sources_count']['stored_reagents'] += 1
                            
                except StoredReagent.DoesNotExist:
                    continue
            
            # Calculate final statistics and prepare response
            if unique_values_only and filter_names:
                # Convert sets to lists for JSON serialization and calculate statistics
                total_unique_values = 0
                for base_name, column_data in metadata_collection['metadata_columns'].items():
                    column_data['unique_values'] = sorted(list(column_data['unique_values']))
                    total_unique_values += len(column_data['unique_values'])
                
                metadata_collection['statistics']['filtered_columns_count'] = len(metadata_collection['metadata_columns'])
                metadata_collection['statistics']['total_unique_values'] = total_unique_values
            else:
                # Standard mode statistics
                total_metadata_count = 0
                if 'metadata_sources' in metadata_collection:
                    for source_type in metadata_collection['metadata_sources'].values():
                        for source in source_type:
                            total_metadata_count += len(source['metadata_columns'])
                
                metadata_collection['statistics']['total_metadata_columns'] = total_metadata_count
                metadata_collection['statistics']['unique_column_names'] = len(metadata_collection['unique_metadata_columns'])
            
            return Response(metadata_collection, status=status.HTTP_200_OK)
            
        except Exception as e:
            import traceback
            error_details = {
                'error': f'Failed to collect SDRF metadata: {str(e)}',
                'error_type': type(e).__name__,
                'traceback': traceback.format_exc(),
                'project_id': project.id,
                'filter_applied': filter_names,
                'unique_values_only': unique_values_only
            }
            print(f"SDRF Collection Error: {error_details}")  # For debugging
            return Response(error_details, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
        serial_number = self.request.query_params.get('serial_number', None)
        accepts_bookings = self.request.query_params.get('accepts_bookings', None)

        # Vaulting logic: exclude vaulted items by default unless include_vaulted=true
        include_vaulted = self.request.query_params.get('include_vaulted', 'false').lower() == 'true'
        vault_filter = Q() if include_vaulted else Q(is_vaulted=False)

        query = Q()
        if serial_number:
            query = query & Q(support_information__serial_number=serial_number)
        if accepts_bookings:
            accepts_bookings = True if accepts_bookings.lower() == 'true' else False
            query = query & Q(accepts_bookings=accepts_bookings)
        
        # Apply vaulting filter to all query paths
        query = query & vault_filter
        
        if user.is_staff:
            return self.queryset.filter(query)
        if user.is_authenticated:
            query_permission = query & Q(user=user)
            query_permission = query_permission & Q(Q(can_book=True) | Q(can_view=True) | Q(can_manage=True))
            i_permission = InstrumentPermission.objects.filter(query_permission)
            if i_permission.exists():
                instruments = []
                for i in i_permission:
                    instruments.append(i.instrument.id)
                return Instrument.objects.filter(Q(id__in=instruments) & vault_filter)

        return Instrument.objects.filter(Q(enabled=True) & vault_filter)

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
        if 'accepts_bookings' in request.data:
            instance.accepts_bookings = request.data['accepts_bookings']
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

    @action(detail=False, methods=['get'])
    def can_manage_instruments(self, request):
        """
        Check if the current user can manage at least one instrument
        """
        user = request.user
        if not user.is_authenticated:
            return Response({'can_manage': False}, status=status.HTTP_200_OK)

        if user.is_staff:
            return Response({'can_manage': True}, status=status.HTTP_200_OK)

        # Check if user has manage permission for any instrument
        has_manage_permission = InstrumentPermission.objects.filter(
            user=user,
            can_manage=True
        ).exists()

        return Response({'can_manage': has_manage_permission}, status=status.HTTP_200_OK)

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
        
        # Vaulting logic: exclude vaulted items by default unless include_vaulted=true
        include_vaulted = self.request.query_params.get('include_vaulted', 'false').lower() == 'true'
        if not include_vaulted:
            query &= Q(is_vaulted=False)
        
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
        """
        Update storage object with vaulting checks.
        
        Vaulted storage objects cannot be updated.
        """
        instance = self.get_object()
        
        # Check if storage object is vaulted - vaulted objects cannot be updated (unless allowed by settings)
        if hasattr(instance, 'is_vaulted') and instance.is_vaulted:
            from .models import SiteSettings
            site_settings = SiteSettings.get_or_create_default()
            if not site_settings.can_modify_vaulted_object(request.user, 'update'):
                return Response(
                    {'error': 'Vaulted storage objects cannot be updated. Please unvault first or contact an administrator.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
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
        """
        Delete storage object with vaulting checks.
        
        Vaulted storage objects cannot be deleted.
        """
        instance = self.get_object()
        
        # Check if storage object is vaulted - vaulted objects cannot be deleted (unless allowed by settings)
        if hasattr(instance, 'is_vaulted') and instance.is_vaulted:
            from .models import SiteSettings
            site_settings = SiteSettings.get_or_create_default()
            if not site_settings.can_modify_vaulted_object(request.user, 'delete'):
                return Response(
                    {'error': 'Vaulted storage objects cannot be deleted. Please unvault first or contact an administrator.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
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
    def unvault(self, request, pk=None):
        """
        Unvault a storage object, making it accessible in normal queries.
        
        Only the storage object owner or staff can unvault storage objects.
        
        Returns:
            Response: Success message with updated storage object data
        """
        instance = self.get_object()
        
        # Check if storage object is actually vaulted
        if not hasattr(instance, 'is_vaulted') or not instance.is_vaulted:
            return Response(
                {'error': 'This storage object is not vaulted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check permissions - only owner or staff can unvault
        user = request.user
        if not user.is_staff and instance.user != user:
            return Response(
                {'error': 'Only the storage object owner or staff can unvault storage objects.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Unvault the storage object
        instance.is_vaulted = False
        instance.save()
        
        data = self.get_serializer(instance).data
        return Response({
            'message': 'Storage object unvaulted successfully.',
            'storage_object': data
        }, status=status.HTTP_200_OK)

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
        
        # Vaulting logic: exclude vaulted items by default unless include_vaulted=true
        include_vaulted = self.request.query_params.get('include_vaulted', 'false').lower() == 'true'
        if not include_vaulted:
            query &= Q(is_vaulted=False)
        
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
        """
        Update stored reagent with vaulting checks.
        
        Vaulted stored reagents cannot be updated.
        """
        instance = self.get_object()

        # Check if stored reagent is vaulted - vaulted reagents cannot be updated (unless allowed by settings)
        if hasattr(instance, 'is_vaulted') and instance.is_vaulted:
            from .models import SiteSettings
            site_settings = SiteSettings.get_or_create_default()
            if not site_settings.can_modify_vaulted_object(request.user, 'update'):
                return Response(
                    {'error': 'Vaulted stored reagents cannot be updated. Please unvault first or contact an administrator.'},
                    status=status.HTTP_403_FORBIDDEN
                )

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
        """
        Delete stored reagent with vaulting checks.
        
        Vaulted stored reagents cannot be deleted.
        """
        instance = self.get_object()
        
        # Check if stored reagent is vaulted - vaulted reagents cannot be deleted (unless allowed by settings)
        if hasattr(instance, 'is_vaulted') and instance.is_vaulted:
            from .models import SiteSettings
            site_settings = SiteSettings.get_or_create_default()
            if not site_settings.can_modify_vaulted_object(request.user, 'delete'):
                return Response(
                    {'error': 'Vaulted stored reagents cannot be deleted. Please unvault first or contact an administrator.'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        permission = self._get_user_permission(instance, self.request.user)
        if not permission["delete"]:
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def unvault(self, request, pk=None):
        """
        Unvault a stored reagent, making it accessible in normal queries.
        
        Only the stored reagent owner or staff can unvault stored reagents.
        
        Returns:
            Response: Success message with updated stored reagent data
        """
        instance = self.get_object()
        
        # Check if stored reagent is actually vaulted
        if not hasattr(instance, 'is_vaulted') or not instance.is_vaulted:
            return Response(
                {'error': 'This stored reagent is not vaulted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check permissions - only owner or staff can unvault
        user = request.user
        if not user.is_staff and instance.user != user:
            return Response(
                {'error': 'Only the stored reagent owner or staff can unvault stored reagents.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Unvault the stored reagent
        instance.is_vaulted = False
        instance.save()
        
        data = self.get_serializer(instance).data
        return Response({
            'message': 'Stored reagent unvaulted successfully.',
            'stored_reagent': data
        }, status=status.HTTP_200_OK)

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
        can_perform_ms_analysis = self.request.query_params.get('can_perform_ms_analysis', None)
        is_core_facility = self.request.query_params.get('is_core_facility', None)
        if is_core_facility:
            is_core_facility = is_core_facility == 'true'
            query &= Q(is_core_facility=is_core_facility)
        if stored_reagent_id:
            stored_reagent = StoredReagent.objects.get(id=stored_reagent_id)
            return stored_reagent.access_lab_groups.all()
        storage_object_id = self.request.query_params.get('storage_object', None)
        if storage_object_id:
            storage_object = StorageObject.objects.get(id=storage_object_id)
            return storage_object.access_lab_groups.all()
        if can_perform_ms_analysis:
            can_perform_ms_analysis = can_perform_ms_analysis == 'true'
            query &= Q(can_perform_ms_analysis=can_perform_ms_analysis)
        return self.queryset.filter(query)

    def get_object(self):
        obj = super().get_object()
        return obj

    def create(self, request, *args, **kwargs):
        group = LabGroup()
        user = self.request.user
        group.name = request.data['name']
        group.description = request.data['description']
        group.can_perform_ms_analysis = request.data['can_perform_ms_analysis']
        group.save()
        
        # Add creator as both user and manager
        group.users.add(user)
        group.managers.add(user)
        
        data = self.get_serializer(group).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        # Check if user has permission to update this lab group
        if not self.request.user.is_staff:
            if not instance.managers.filter(id=self.request.user.id).exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)

        if "name" in request.data:
            instance.name = request.data['name']
        if "description" in request.data:
            instance.description = request.data['description']
        if "default_storage" in request.data:
            instance.default_storage = StorageObject.objects.get(id=request.data['default_storage'])
        if "service_storage" in request.data:
            instance.service_storage = StorageObject.objects.get(id=request.data['service_storage'])
        if "can_perform_ms_analysis" in request.data:
            instance.can_perform_ms_analysis = request.data['can_perform_ms_analysis']
        if self.request.user.is_staff:
            if "is_core_facility" in request.data:
                instance.is_core_facility = request.data['is_core_facility']
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
            if not group.managers.filter(id=self.request.user.id).exists():
                return Response(status=status.HTTP_401_UNAUTHORIZED)
        user = User.objects.get(id=request.data['user'])
        group.users.remove(user)
        data = self.get_serializer(group).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def add_user(self, request, pk=None):
        group: LabGroup = self.get_object()
        if not self.request.user.is_staff:
            if not group.managers.filter(id=self.request.user.id).exists():
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

    @action(detail=True, methods=['post'])
    def add_manager(self, request, pk=None):
        """Add a user as a manager to the lab group"""
        group = self.get_object()
        
        # Only staff or existing managers can add new managers
        if not self.request.user.is_staff:
            if not group.managers.filter(id=self.request.user.id).exists():
                return Response(
                    {'error': 'Only staff or existing managers can add new managers'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
        
        try:
            user_id = request.data['user']
            user = User.objects.get(id=user_id)
            
            # Add user as manager (also add as regular user if not already)
            group.managers.add(user)
            group.users.add(user)  # Ensure manager is also a user of the group
            
            data = self.get_serializer(group).data
            return Response(data, status=status.HTTP_200_OK)
            
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except KeyError:
            return Response(
                {'error': 'User ID is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def remove_manager(self, request, pk=None):
        """Remove a user from managers of the lab group"""
        group = self.get_object()
        
        # Only staff or existing managers can remove managers
        if not self.request.user.is_staff:
            if not group.managers.filter(id=self.request.user.id).exists():
                return Response(
                    {'error': 'Only staff or existing managers can remove managers'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
        
        try:
            user_id = request.data['user']
            user = User.objects.get(id=user_id)
            
            # Prevent removing the last manager (unless staff is doing it)
            if not self.request.user.is_staff and group.managers.count() <= 1:
                return Response(
                    {'error': 'Cannot remove the last manager. At least one manager must remain.'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Remove user from managers (but keep as regular user)
            group.managers.remove(user)
            
            data = self.get_serializer(group).data
            return Response(data, status=status.HTTP_200_OK)
            
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except KeyError:
            return Response(
                {'error': 'User ID is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

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
        
        # If this is an instrument metadata column, also add it to all existing pools
        if metadata_column.instrument:
            instrument_jobs = InstrumentJob.objects.filter(instrument=metadata_column.instrument)
            for job in instrument_jobs:
                # Add the new column to the job's metadata first
                job.user_metadata.add(metadata_column)
                
                pools = SamplePool.objects.filter(instrument_job=job)
                for pool in pools:
                    # Create a new metadata column for this pool with the same properties
                    pool_metadata_column = MetadataColumn.objects.create(
                        name=metadata_column.name,
                        type=metadata_column.type,
                        value=metadata_column.value,
                        mandatory=metadata_column.mandatory,
                        hidden=metadata_column.hidden,
                        readonly=metadata_column.readonly,
                        modifiers=metadata_column.modifiers
                    )
                    
                    # Add to pool's user metadata (most new columns are user metadata)
                    pool.user_metadata.add(pool_metadata_column)
        
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
                    
            # When deleting a metadata column from an instrument, also remove corresponding columns from all pools
            # that are using this instrument
            instrument_jobs = InstrumentJob.objects.filter(instrument=metadata_column.instrument)
            for job in instrument_jobs:
                # Find the index of the column being deleted in the job's metadata arrays
                user_metadata_list = list(job.user_metadata.all())
                staff_metadata_list = list(job.staff_metadata.all())
                
                column_index = None
                is_user_metadata = False
                is_staff_metadata = False
                
                # Check if it's in user_metadata and get its index
                if metadata_column in user_metadata_list:
                    column_index = user_metadata_list.index(metadata_column)
                    is_user_metadata = True
                
                # Check if it's in staff_metadata and get its index
                if metadata_column in staff_metadata_list:
                    column_index = staff_metadata_list.index(metadata_column)
                    is_staff_metadata = True
                
                # If we found the column and its index, remove it from all pools at the same index
                if column_index is not None:
                    pools = SamplePool.objects.filter(instrument_job=job)
                    for pool in pools:
                        if is_user_metadata:
                            pool_user_metadata_list = list(pool.user_metadata.all())
                            if column_index < len(pool_user_metadata_list):
                                col_to_remove = pool_user_metadata_list[column_index]
                                pool.user_metadata.remove(col_to_remove)
                                col_to_remove.delete()
                        
                        if is_staff_metadata:
                            pool_staff_metadata_list = list(pool.staff_metadata.all())
                            if column_index < len(pool_staff_metadata_list):
                                col_to_remove = pool_staff_metadata_list[column_index]
                                pool.staff_metadata.remove(col_to_remove)
                                col_to_remove.delete()
                    
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
            if not instrument.accepts_bookings:
                return Response(
                    {'error': 'This instrument does not accept bookings'},
                    status=status.HTTP_400_BAD_REQUEST
                )
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
            if not instrument.accepts_bookings:
                return Response(
                    {'error': 'This instrument does not accept bookings'},
                    status=status.HTTP_400_BAD_REQUEST
                )
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
        request_status = request.data['status']
        instrument_job.status = request_status
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

    def _check_instrument_job_permissions(self, instrument_job, user, action='read'):
        """
        Check if user has permission to perform action on instrument job
        Returns (has_permission, is_staff_user)
        """
        # System admin always has access
        if user.is_staff:
            return True, True
        
        # Job owner has read access only
        if instrument_job.user == user:
            return action == 'read', False
        
        # Check staff assignment
        staff_users = instrument_job.staff.all()
        if staff_users.count() > 0:
            if user in staff_users:
                return True, True
        else:
            # No specific staff assigned, check service lab group
            if instrument_job.service_lab_group:
                service_staff = instrument_job.service_lab_group.users.all()
                if user in service_staff:
                    return True, True
        
        return False, False

    @action(detail=True, methods=['get'])
    def sample_pools(self, request, pk=None):
        """List all sample pools for this instrument job"""
        instrument_job = self.get_object()
        
        # Check permissions
        has_permission, _ = self._check_instrument_job_permissions(instrument_job, request.user, 'read')
        if not has_permission:
            return Response(status=status.HTTP_403_FORBIDDEN)
        
        pools = SamplePool.objects.filter(instrument_job=instrument_job)
        serializer = SamplePoolSerializer(pools, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def create_sample_pool(self, request, pk=None):
        """Create a new sample pool for this instrument job"""
        instrument_job = self.get_object()
        
        # Check write permissions (only staff can create pools)
        has_permission, is_staff_user = self._check_instrument_job_permissions(instrument_job, request.user, 'write')
        if not has_permission or not is_staff_user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        
        # Add instrument_job to the data
        pool_data = request.data.copy()
        pool_data['instrument_job'] = instrument_job.id
        
        serializer = SamplePoolSerializer(data=pool_data)
        if serializer.is_valid():
            pool = serializer.save(
                instrument_job=instrument_job,
                created_by=request.user
            )
            
            # Copy metadata from template sample if provided
            if pool.template_sample:
                self._copy_metadata_from_template_sample(pool, instrument_job)
            else:
                # Create a basic pooled sample column for pools without template
                self._create_basic_pool_metadata(pool, instrument_job)
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def sample_pool_overview(self, request, pk=None):
        """Get sample pool status overview for this instrument job"""
        instrument_job = self.get_object()
        
        # Check permissions
        has_permission, _ = self._check_instrument_job_permissions(instrument_job, request.user, 'read')
        if not has_permission:
            return Response(status=status.HTTP_403_FORBIDDEN)
        
        # Get all pools for this instrument job
        pools = SamplePool.objects.filter(instrument_job=instrument_job)
        
        # Get source names for all samples
        source_names = self._get_source_names_for_samples(instrument_job)
        
        # Generate sample status overview
        sample_overview = []
        for sample_index in range(1, instrument_job.sample_number + 1):
            sample_pools = []
            sample_status = "Independent"
            sdrf_value = "not pooled"
            
            for pool in pools:
                if sample_index in pool.pooled_only_samples:
                    sample_pools.append(pool.pool_name)
                    sample_status = "Pooled Only"
                    sdrf_value = pool.sdrf_value
                elif sample_index in pool.pooled_and_independent_samples:
                    sample_pools.append(pool.pool_name)
                    if sample_status == "Pooled Only":
                        sample_status = "Mixed"
                    elif sample_status == "Independent":
                        sample_status = "Mixed"
                    # For independent samples, SDRF value remains "not pooled"
            
            # Get source name or fallback to sample index
            source_name = source_names.get(sample_index, f'Sample {sample_index}')
            
            sample_overview.append({
                "sample_index": sample_index,
                "sample_name": source_name,
                "status": sample_status,
                "pool_names": sample_pools,
                "sdrf_value": sdrf_value
            })
        
        overview = {
            "total_samples": instrument_job.sample_number,
            "pooled_samples": len([s for s in sample_overview if s["status"] != "Independent"]),
            "independent_samples": len([s for s in sample_overview if s["status"] == "Independent"]),
            "pools": SamplePoolSerializer(pools, many=True).data,
            "sample_overview": sample_overview
        }
        
        return Response(overview, status=status.HTTP_200_OK)

    def _update_pooled_sample_metadata(self, instrument_job):
        """Update pooled sample metadata for an instrument job"""
        import json
        
        pools = SamplePool.objects.filter(instrument_job=instrument_job)
        
        # Check if there's already a pooled sample column in staff_metadata
        existing_pooled_column = instrument_job.staff_metadata.filter(
            name="Pooled sample",
            type="Characteristics"
        ).first()
        
        if existing_pooled_column:
            pooled_column = existing_pooled_column
            created = False
        else:
            # Create a new pooled sample metadata column
            pooled_column = MetadataColumn.objects.create(
                instrument=instrument_job.instrument,
                name="Pooled sample",
                type="Characteristics",
                value="not pooled",
                mandatory=False
            )
            created = True
        
        # Add to staff_metadata if it's a new column
        if created:
            instrument_job.staff_metadata.add(pooled_column)
        else:
            # Check if it's already in staff_metadata, if not add it
            if not instrument_job.staff_metadata.filter(id=pooled_column.id).exists():
                instrument_job.staff_metadata.add(pooled_column)
        
        # Generate modifiers for pooled samples
        modifiers = []
        for pool in pools:
            if pool.pooled_only_samples:
                modifier = {
                    "samples": ",".join([str(i) for i in pool.pooled_only_samples]),
                    "value": "pooled"
                }
                modifiers.append(modifier)
        
        # Update the metadata column with modifiers
        pooled_column.modifiers = json.dumps(modifiers) if modifiers else None
        pooled_column.save()

    def _update_pooled_sample_metadata_after_pool_deletion(self, instrument_job, affected_samples):
        """Update pooled sample metadata after pool deletion to recalculate sample statuses"""
        import json
        
        # Get remaining pools for this instrument job
        pools = SamplePool.objects.filter(instrument_job=instrument_job)
        
        # Find the pooled sample metadata column
        pooled_column = instrument_job.staff_metadata.filter(
            name="Pooled sample",
            type="Characteristics"
        ).first()
        
        if not pooled_column:
            # No pooled sample column exists, nothing to update
            return
        
        # Recalculate modifiers based on remaining pools
        modifiers = []
        for pool in pools:
            if pool.pooled_only_samples:
                modifier = {
                    "samples": ",".join([str(i) for i in pool.pooled_only_samples]),
                    "value": "pooled"
                }
                modifiers.append(modifier)
        
        # Update the metadata column with new modifiers
        pooled_column.modifiers = json.dumps(modifiers) if modifiers else None
        pooled_column.save()
        
        # Also update pooled sample metadata for all pools to reflect the changes
        for pool in pools:
            pool_pooled_column = pool.staff_metadata.filter(
                name="Pooled sample",
                type="Characteristics"  
            ).first()
            
            if pool_pooled_column:
                # Calculate SDRF value for this pool
                if pool.pooled_only_samples:
                    # Get source names for pooled only samples
                    source_names = self._get_source_names_for_samples(instrument_job)
                    pooled_source_names = [source_names.get(i, f"Sample {i}") for i in pool.pooled_only_samples]
                    sdrf_value = f"SN={','.join(pooled_source_names)}"
                else:
                    sdrf_value = "not pooled"
                
                pool_pooled_column.value = sdrf_value
                pool_pooled_column.save()

    def _create_basic_pool_metadata(self, pool, instrument_job):
        """Create ALL metadata columns for pools inheriting default values from main table"""
        # Get all metadata columns for this instrument job
        user_metadata_columns = list(instrument_job.user_metadata.all())
        staff_metadata_columns = list(instrument_job.staff_metadata.all())
        
        # Create ALL user metadata columns for the pool
        for metadata_column in user_metadata_columns:
            # Skip pooled sample column as it's added separately to staff metadata
            if metadata_column.name.lower() in ['pooled sample', 'pooled_sample']:
                continue
                
            # Determine the value based on column type - use main table defaults except for special cases
            if metadata_column.name.lower() in ['source name', 'source_name']:
                column_value = pool.pool_name  # Pool name as source name
            elif metadata_column.name.lower() in ['assay name', 'assay_name']:
                # Calculate run number: sample_count + pool_number (pools are numbered sequentially)
                pool_count = instrument_job.sample_pools.filter(id__lte=pool.id).count()
                run_number = instrument_job.sample_number + pool_count
                column_value = f"run {run_number}"
            else:
                # Use the default value from the main table
                column_value = metadata_column.value
            
            # Create a copy of the metadata column for the pool
            pool_metadata_column = MetadataColumn.objects.create(
                name=metadata_column.name,
                type=metadata_column.type,
                value=column_value,
                mandatory=metadata_column.mandatory,
                hidden=metadata_column.hidden,
                readonly=metadata_column.readonly,
                column_position=metadata_column.column_position,
                not_applicable=metadata_column.not_applicable,
                auto_generated=metadata_column.auto_generated,
                modifiers=metadata_column.modifiers
            )
            
            # Add to pool's user metadata
            pool.user_metadata.add(pool_metadata_column)
        
        # Create ALL staff metadata columns for the pool
        for metadata_column in staff_metadata_columns:
            # Determine the value based on column type - use main table defaults except for special cases
            if metadata_column.name.lower() in ['pooled sample', 'pooled_sample']:
                column_value = pool.sdrf_value  # Always use pool-specific SDRF value, never inherit from main table
            elif metadata_column.name.lower() in ['source name', 'source_name']:
                column_value = pool.pool_name  # Pool name as source name
            elif metadata_column.name.lower() in ['assay name', 'assay_name']:
                # Calculate run number: sample_count + pool_number (pools are numbered sequentially)
                pool_count = instrument_job.sample_pools.filter(id__lte=pool.id).count()
                run_number = instrument_job.sample_number + pool_count
                column_value = f"run {run_number}"
            else:
                # Use the default value from the main table
                column_value = metadata_column.value
            
            # Create a copy of the metadata column for the pool
            pool_metadata_column = MetadataColumn.objects.create(
                name=metadata_column.name,
                type=metadata_column.type,
                value=column_value,
                mandatory=metadata_column.mandatory,
                hidden=metadata_column.hidden,
                readonly=metadata_column.readonly,
                column_position=metadata_column.column_position,
                not_applicable=metadata_column.not_applicable,
                auto_generated=metadata_column.auto_generated,
                modifiers=metadata_column.modifiers
            )
            
            # Add to pool's staff metadata
            pool.staff_metadata.add(pool_metadata_column)
        
        # If no pooled sample column exists in staff metadata, create one
        pooled_sample_exists = any(
            col.name.lower() in ['pooled sample', 'pooled_sample'] 
            for col in staff_metadata_columns
        )
        
        if not pooled_sample_exists:
            # Create a Pooled sample column for the pool with the SDRF value
            pool_pooled_column = MetadataColumn.objects.create(
                name="Pooled sample",
                type="Characteristics",
                value=pool.sdrf_value,
                mandatory=False,
                hidden=False,
                readonly=False,
                column_position=999,  # Put at end
                not_applicable=False,
                auto_generated=True
            )
            
            # Add to pool's staff metadata
            pool.staff_metadata.add(pool_pooled_column)

    def _copy_metadata_from_template_sample(self, pool, instrument_job):
        """Copy ALL metadata from template sample to pool, creating complete metadata structure"""
        import json
        
        template_sample_index = pool.template_sample
        if not template_sample_index:
            # Fallback to basic metadata creation if no template
            self._create_basic_pool_metadata(pool, instrument_job)
            return
        
        # Get all metadata columns for this instrument job
        user_metadata_columns = list(instrument_job.user_metadata.all())
        staff_metadata_columns = list(instrument_job.staff_metadata.all())
        
        # Create ALL user metadata columns for the pool
        for metadata_column in user_metadata_columns:
            # Skip pooled sample column as it's added separately to staff metadata
            if metadata_column.name.lower() in ['pooled sample', 'pooled_sample']:
                continue
                
            # Determine the value based on column type and template
            if metadata_column.name.lower() in ['source name', 'source_name']:
                column_value = pool.pool_name  # Pool name as source name
            elif metadata_column.name.lower() in ['assay name', 'assay_name']:
                # Calculate run number: sample_count + pool_number (pools are numbered sequentially)
                pool_count = instrument_job.sample_pools.filter(id__lte=pool.id).count()
                run_number = instrument_job.sample_number + pool_count
                column_value = f"run {run_number}"
            else:
                # Get the value for the template sample from this metadata column
                column_value = self._get_sample_metadata_value(metadata_column, template_sample_index) or ""
            
            # Create a copy of ALL metadata columns for the pool (not just ones with values)
            pool_metadata_column = MetadataColumn.objects.create(
                name=metadata_column.name,
                type=metadata_column.type,
                value=column_value,
                mandatory=metadata_column.mandatory,
                hidden=metadata_column.hidden,
                readonly=metadata_column.readonly,
                column_position=metadata_column.column_position,
                not_applicable=metadata_column.not_applicable,
                auto_generated=metadata_column.auto_generated,
                modifiers=metadata_column.modifiers
            )
            
            # Add to pool's user metadata
            pool.user_metadata.add(pool_metadata_column)
        
        # Create ALL staff metadata columns for the pool
        for metadata_column in staff_metadata_columns:
            # Determine the value based on column type and template
            if metadata_column.name.lower() in ['pooled sample', 'pooled_sample']:
                column_value = pool.sdrf_value  # Always use pool-specific SDRF value, never inherit from template
            elif metadata_column.name.lower() in ['source name', 'source_name']:
                column_value = pool.pool_name  # Pool name as source name
            elif metadata_column.name.lower() in ['assay name', 'assay_name']:
                # Calculate run number: sample_count + pool_number (pools are numbered sequentially)
                pool_count = instrument_job.sample_pools.filter(id__lte=pool.id).count()
                run_number = instrument_job.sample_number + pool_count
                column_value = f"run {run_number}"
            else:
                # Get the value for the template sample from this metadata column
                column_value = self._get_sample_metadata_value(metadata_column, template_sample_index) or ""
            
            # Create a copy of ALL metadata columns for the pool (not just ones with values)
            pool_metadata_column = MetadataColumn.objects.create(
                name=metadata_column.name,
                type=metadata_column.type,
                value=column_value,
                mandatory=metadata_column.mandatory,
                hidden=metadata_column.hidden,
                readonly=metadata_column.readonly,
                column_position=metadata_column.column_position,
                not_applicable=metadata_column.not_applicable,
                auto_generated=metadata_column.auto_generated,
                modifiers=metadata_column.modifiers
            )
            
            # Add to pool's staff metadata
            pool.staff_metadata.add(pool_metadata_column)
        
        # If no pooled sample column exists in staff metadata, create one
        pooled_sample_exists = any(
            col.name.lower() in ['pooled sample', 'pooled_sample'] 
            for col in staff_metadata_columns
        )
        
        if not pooled_sample_exists:
            # Create a Pooled sample column for the pool with the SDRF value
            pool_pooled_column = MetadataColumn.objects.create(
                name="Pooled sample",
                type="Characteristics",
                value=pool.sdrf_value,
                mandatory=False,
                hidden=False,
                readonly=False,
                column_position=999,  # Put at end
                not_applicable=False,
                auto_generated=True
            )
            
            # Add to pool's staff metadata
            pool.staff_metadata.add(pool_pooled_column)
    
    def _get_sample_metadata_value(self, metadata_column, sample_index):
        """Get the metadata value for a specific sample from a metadata column"""
        import json
        
        # Check if there are modifiers for this specific sample
        if metadata_column.modifiers:
            try:
                modifiers = json.loads(metadata_column.modifiers)
                for modifier in modifiers:
                    if 'samples' in modifier and 'value' in modifier:
                        sample_list = [int(s.strip()) for s in modifier['samples'].split(',')]
                        if sample_index in sample_list:
                            return modifier['value']
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Return the default value if no specific modifier found
        return metadata_column.value or ''

    def _get_source_names_for_samples(self, instrument_job):
        """Get source names for all samples from metadata"""
        import json
        
        # Get the Source name metadata column
        source_name_column = None
        for metadata_column in list(instrument_job.user_metadata.all()) + list(instrument_job.staff_metadata.all()):
            if metadata_column.name == "Source name":
                source_name_column = metadata_column
                break
        
        if not source_name_column:
            # No source name metadata found, return empty dict to use fallback
            return {}
        
        source_names = {}
        
        # Set default value for all samples
        if source_name_column.value:
            for i in range(1, instrument_job.sample_number + 1):
                source_names[i] = source_name_column.value
        
        # Override with modifier values if they exist
        if source_name_column.modifiers:
            try:
                modifiers = json.loads(source_name_column.modifiers) if isinstance(source_name_column.modifiers, str) else source_name_column.modifiers
                for modifier in modifiers:
                    samples_str = modifier.get("samples", "")
                    value = modifier.get("value", "")
                    
                    # Parse sample indices from the modifier string
                    sample_indices = self._parse_sample_indices_from_modifier_string(samples_str)
                    for sample_index in sample_indices:
                        if 1 <= sample_index <= instrument_job.sample_number:
                            source_names[sample_index] = value
            except (json.JSONDecodeError, ValueError):
                pass
        
        return source_names
    
    def _parse_sample_indices_from_modifier_string(self, samples_str):
        """Parse sample indices from modifier string like '1,2,3' or '1-3,5'"""
        indices = []
        if not samples_str:
            return indices
            
        parts = samples_str.split(",")
        for part in parts:
            part = part.strip()
            if "-" in part:
                # Handle range like "1-3"
                try:
                    start, end = part.split("-")
                    start_idx = int(start.strip())
                    end_idx = int(end.strip())
                    for i in range(start_idx, end_idx + 1):
                        indices.append(i)
                except ValueError:
                    continue
            else:
                # Handle single number
                try:
                    indices.append(int(part))
                except ValueError:
                    continue
        
        return indices


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
                lab_group = LabGroup.objects.get(id=lab_group, can_perform_ms_analysis=True)
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

            lab_group = LabGroup.objects.get(id=lab_group, can_perform_ms_analysis=True)
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
                try:
                    lab_group = LabGroup.objects.get(id=lab_group_id, can_perform_ms_analysis=True)
                    query &= Q(service_lab_group=lab_group)
                except LabGroup.DoesNotExist:
                    # Return empty queryset instead of Response
                    return self.queryset.none()
            else:
                # Return empty queryset instead of Response
                return self.queryset.none()
        else:
            if not user.is_staff:
                # Return empty queryset instead of Response
                return self.queryset.none()
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
        template = MetadataTableTemplate.objects.create(name=name, user=user, field_mask_mapping=json.dumps(default_mask_mapping))
        template.user_columns.add(*user_columns)
        template.staff_columns.add(*staff_columns)
        if mode == 'service_lab_group':
            lab_group_id = request.data.get('lab_group', None)
            if lab_group_id:
                lab_group = LabGroup.objects.get(id=lab_group_id, can_perform_ms_analysis=True)
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
                lab_group = LabGroup.objects.get(id=lab_group_id, can_perform_ms_analysis=True)
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

        a = Annotation(
            user=request.user,
            folder=maintenance_log.annotation_folder
        )

        if "annotation" in request.data:
            a.annotation = request.data["annotation"]
        else:
            a.annotation = f'annotation file from maintenance log {maintenance_log.id}'

        if 'file' in request.FILES:
            uploaded_file = request.FILES['file']
            a.annotation_name = uploaded_file.name
            a.annotation_type = "file"
            a.file.save(uploaded_file.name, uploaded_file, save=False)

        if "annotation_type" in request.data:
            a.annotation_type = request.data["annotation_type"]
        if "annotation_name" in request.data:
            a.annotation_name = request.data["annotation_name"]
        if "language" in request.data:
            a.language = request.data["language"]
        if "transcribed" in request.data:
            a.transcribed = request.data["transcribed"]
        if "summary" in request.data:
            a.summary = request.data["summary"]

        a.save()
        serialized = AnnotationSerializer(a, many=False)
        return Response(serialized.data, status=status.HTTP_201_CREATED)

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


class JobStatusViewSet(ModelViewSet, FilterMixin):
    """
    Universal ViewSet for checking RQ job status.
    
    Provides status checking for any RQ job, not limited to MCP tasks.
    Supports both task_id and job_id based lookups.
    
    This replaces the MCPTaskStatusView and provides a universal
    interface for all async job status checking.
    """
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def status(self, request):
        """
        Get status of an RQ job.
        
        Query parameters:
        - task_id (str): Optional task identifier
        - job_id (str): RQ job identifier
        - queue (str): Queue name (default: 'default')
        
        Returns job status, metadata, and results if completed.
        """
        task_id = request.query_params.get('task_id')
        job_id = request.query_params.get('job_id')
        queue_name = request.query_params.get('queue', 'default')
        
        if not task_id and not job_id:
            return Response({
                'success': False,
                'error': 'Either task_id or job_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            queue = get_queue(queue_name)
            
            if job_id:
                try:
                    job = Job.fetch(job_id, connection=queue.connection)
                    
                    job_status = job.get_status()
                    
                    result = {
                        'success': True,
                        'job_id': job.id,
                        'task_id': task_id or job.meta.get('task_id'),
                        'queue': queue_name,
                        'status': job_status,
                        'created_at': job.created_at.isoformat() if job.created_at else None,
                        'started_at': job.started_at.isoformat() if job.started_at else None,
                        'ended_at': job.ended_at.isoformat() if job.ended_at else None,
                        'meta': job.meta or {}
                    }
                    
                    # Add result if job is finished
                    if job_status == 'finished':
                        result['result'] = job.result
                    elif job_status == 'failed':
                        result['error'] = str(job.exc_info) if job.exc_info else 'Job failed with unknown error'
                        result['failure_reason'] = str(job.exc_info) if job.exc_info else None
                    
                    return Response(result, status=status.HTTP_200_OK)
                    
                except Exception as e:
                    return Response({
                        'success': False,
                        'error': f'Job not found or invalid: {str(e)}'
                    }, status=status.HTTP_404_NOT_FOUND)
            
            # If only task_id is provided, search for job by task_id in meta
            if task_id:
                try:
                    # Search through jobs to find one with matching task_id
                    jobs = queue.get_jobs()
                    target_job = None
                    
                    for job in jobs:
                        if job.meta.get('task_id') == task_id:
                            target_job = job
                            break
                    
                    if target_job:
                        job_status = target_job.get_status()
                        
                        result = {
                            'success': True,
                            'job_id': target_job.id,
                            'task_id': task_id,
                            'queue': queue_name,
                            'status': job_status,
                            'created_at': target_job.created_at.isoformat() if target_job.created_at else None,
                            'started_at': target_job.started_at.isoformat() if target_job.started_at else None,
                            'ended_at': target_job.ended_at.isoformat() if target_job.ended_at else None,
                            'meta': target_job.meta or {}
                        }
                        
                        # Add result if job is finished
                        if job_status == 'finished':
                            result['result'] = target_job.result
                        elif job_status == 'failed':
                            result['error'] = str(target_job.exc_info) if target_job.exc_info else 'Job failed with unknown error'
                            result['failure_reason'] = str(target_job.exc_info) if target_job.exc_info else None
                        
                        return Response(result, status=status.HTTP_200_OK)
                    else:
                        return Response({
                            'success': False,
                            'error': f'No job found with task_id: {task_id}'
                        }, status=status.HTTP_404_NOT_FOUND)
                        
                except Exception as e:
                    return Response({
                        'success': False,
                        'error': f'Error searching for task: {str(e)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Job status check failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def list_jobs(self, request):
        """
        List jobs in a queue with optional filtering.
        
        Query parameters:
        - queue (str): Queue name (default: 'default')
        - status (str): Filter by job status
        - limit (int): Maximum number of jobs to return (default: 50)
        
        Returns list of jobs with basic information.
        """
        queue_name = request.query_params.get('queue', 'default')
        status_filter = request.query_params.get('status')
        limit = int(request.query_params.get('limit', 50))
        
        try:
            queue = get_queue(queue_name)
            jobs = queue.get_jobs()
            
            # Filter by status if provided
            if status_filter:
                jobs = [job for job in jobs if job.get_status() == status_filter]
            
            # Limit results
            jobs = jobs[:limit]
            
            job_list = []
            for job in jobs:
                job_info = {
                    'job_id': job.id,
                    'task_id': job.meta.get('task_id'),
                    'status': job.get_status(),
                    'created_at': job.created_at.isoformat() if job.created_at else None,
                    'started_at': job.started_at.isoformat() if job.started_at else None,
                    'ended_at': job.ended_at.isoformat() if job.ended_at else None,
                    'func_name': job.func_name if hasattr(job, 'func_name') else None
                }
                job_list.append(job_info)
            
            return Response({
                'success': True,
                'queue': queue_name,
                'total_jobs': len(job_list),
                'jobs': job_list
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to list jobs: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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


class SiteSettingsViewSet(ModelViewSet):
    """ViewSet for managing site settings"""
    queryset = SiteSettings.objects.all()
    serializer_class = SiteSettingsSerializer
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return only active site settings"""
        return SiteSettings.objects.filter(is_active=True)

    def list(self, request, *args, **kwargs):
        """Get current site settings (singleton pattern)"""
        current_settings = SiteSettings.get_or_create_default()
        serializer = self.get_serializer(current_settings)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """Create new site settings (replaces existing)"""
        # Only staff/superusers can modify site settings
        if not request.user.is_staff:
            raise PermissionDenied("Only staff members can modify site settings")

        # Deactivate existing settings
        SiteSettings.objects.filter(is_active=True).update(is_active=False)

        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """Update existing site settings"""
        # Only staff/superusers can modify site settings
        if not request.user.is_staff:
            raise PermissionDenied("Only staff members can modify site settings")

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """Partially update site settings"""
        # Only staff/superusers can modify site settings
        if not request.user.is_staff:
            raise PermissionDenied("Only staff members can modify site settings")

        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Prevent deletion of site settings"""
        return Response(
            {"error": "Site settings cannot be deleted"},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def public(self, request):
        """Get public site settings (no authentication required)"""
        current_settings = SiteSettings.get_or_create_default()
        # Return only public fields
        public_data = {
            'site_name': current_settings.site_name,
            'site_tagline': current_settings.site_tagline,
            'logo': current_settings.logo.url if current_settings.logo else None,
            'favicon': current_settings.favicon.url if current_settings.favicon else None,
            'banner_enabled': current_settings.banner_enabled,
            'banner_text': current_settings.banner_text,
            'banner_color': current_settings.banner_color,
            'banner_text_color': current_settings.banner_text_color,
            'banner_dismissible': current_settings.banner_dismissible,
            'primary_color': current_settings.primary_color,
            'secondary_color': current_settings.secondary_color,
            'footer_text': current_settings.footer_text,
            # Module availability settings
            'enable_documents_module': current_settings.enable_documents_module,
            'enable_lab_notebook_module': current_settings.enable_lab_notebook_module,
            'enable_instruments_module': current_settings.enable_instruments_module,
            'enable_storage_module': current_settings.enable_storage_module,
            'enable_billing_module': current_settings.enable_billing_module,
            'enable_ai_sdrf_suggestions': current_settings.enable_ai_sdrf_suggestions,
            'enable_backup_module': current_settings.enable_backup_module,
            # Backup configuration
            'backup_frequency_days': current_settings.backup_frequency_days,

        }
        return Response(public_data)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def download_logo(self, request):
        """Download site logo using X-Accel-Redirect"""
        current_settings = SiteSettings.get_or_create_default()
        if not current_settings.logo:
            return Response({"error": "No logo file available"}, status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(status=200)
        filename = current_settings.logo.name.split('/')[-1]
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        response["X-Accel-Redirect"] = f"/media/{current_settings.logo.name}"
        return response

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def download_favicon(self, request):
        """Download site favicon using X-Accel-Redirect"""
        current_settings = SiteSettings.get_or_create_default()
        if not current_settings.favicon:
            return Response({"error": "No favicon file available"}, status=status.HTTP_404_NOT_FOUND)

        response = HttpResponse(status=200)
        filename = current_settings.favicon.name.split('/')[-1]
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        response["X-Accel-Redirect"] = f"/media/{current_settings.favicon.name}"
        return response

    @action(detail=False, methods=['post'])
    def get_logo_signed_url(self, request):
        """Get signed URL for logo download"""
        current_settings = SiteSettings.get_or_create_default()
        if not current_settings.logo:
            return Response({"error": "No logo file available"}, status=status.HTTP_404_NOT_FOUND)

        signer = TimestampSigner()
        filename = current_settings.logo.name.split('/')[-1]
        token = signer.sign(filename)
        return Response({"token": token, "filename": filename})

    @action(detail=False, methods=['post'])
    def get_favicon_signed_url(self, request):
        """Get signed URL for favicon download"""
        current_settings = SiteSettings.get_or_create_default()
        if not current_settings.favicon:
            return Response({"error": "No favicon file available"}, status=status.HTTP_404_NOT_FOUND)

        signer = TimestampSigner()
        filename = current_settings.favicon.name.split('/')[-1]
        token = signer.sign(filename)
        return Response({"token": token, "filename": filename})

    @action(detail=False, methods=['get'])
    def download_logo_signed(self, request):
        """Download logo using a signed token"""
        token = request.query_params.get('token', None)
        if not token:
            return Response({"error": "No token provided"}, status=status.HTTP_400_BAD_REQUEST)

        signer = TimestampSigner()
        try:
            filename = signer.unsign(token, max_age=60 * 30)  # 30 minute expiration
            current_settings = SiteSettings.get_or_create_default()
            if not current_settings.logo:
                return Response({"error": "No logo file available"}, status=status.HTTP_404_NOT_FOUND)

            response = HttpResponse(status=200)
            response["Content-Disposition"] = f'inline; filename="{filename}"'
            response["X-Accel-Redirect"] = f"/media/{current_settings.logo.name}"
            return response
        except (BadSignature, SignatureExpired) as e:
            return Response({"error": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def download_favicon_signed(self, request):
        """Download favicon using a signed token"""
        token = request.query_params.get('token', None)
        if not token:
            return Response({"error": "No token provided"}, status=status.HTTP_400_BAD_REQUEST)

        signer = TimestampSigner()
        try:
            filename = signer.unsign(token, max_age=60 * 30)  # 30 minute expiration
            current_settings = SiteSettings.get_or_create_default()
            if not current_settings.favicon:
                return Response({"error": "No favicon file available"}, status=status.HTTP_404_NOT_FOUND)

            response = HttpResponse(status=200)
            response["Content-Disposition"] = f'inline; filename="{filename}"'
            response["X-Accel-Redirect"] = f"/media/{current_settings.favicon.name}"
            return response
        except (BadSignature, SignatureExpired) as e:
            return Response({"error": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def available_import_options(self, request):
        """Get available import options based on site settings and user permissions"""
        current_settings = SiteSettings.get_or_create_default()

        # Default import options
        default_options = {
            'protocols': True,
            'sessions': True,
            'annotations': True,
            'projects': True,
            'reagents': True,
            'instruments': True,
            'lab_groups': True,
            'messaging': False,  # Default to false for privacy
            'support_models': True
        }

        # Filter based on site settings and user permissions
        available_options = current_settings.filter_import_options(default_options, request.user)

        return Response({
            'available_options': available_options,
            'is_staff_override': request.user.is_staff,
            'max_archive_size_mb': current_settings.max_import_archive_size_mb if hasattr(current_settings, 'max_import_archive_size_mb') else None
        })




class SharedDocumentViewSet(ModelViewSet, FilterMixin):
    """ViewSet for managing shared documents (annotations with files)"""
    queryset = Annotation.objects.all()
    serializer_class = SharedDocumentSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["annotation", "annotation_name"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]
    pagination_class = LimitOffsetPagination
    filterset_fields = ["annotation_type", "created_at", "updated_at", "user", "folder", "session"]

    def get_queryset(self):
        """Get annotations that are specifically shared documents (files in shared document folders or with document permissions)"""
        user = self.request.user

        # Start with annotations that have files AND are in shared document folders OR have document permissions
        queryset = Annotation.objects.filter(
            file__isnull=False
        ).filter(
            Q(folder__is_shared_document_folder=True) |  # In shared document folder
            Q(folder__isnull=True, document_permissions__isnull=False) |  # Root level with permissions
            Q(document_permissions__isnull=False)  # Has document permissions
        ).select_related("user", "folder", "session").distinct()

        # Filter by access permissions
        accessible_annotations = []
        for annotation in queryset:
            # Owner can always access
            if annotation.user == user:
                accessible_annotations.append(annotation.id)
                continue

            # Check document permissions
            if DocumentPermission.user_can_access_annotation_with_folder_inheritance(annotation, user, "view"):
                accessible_annotations.append(annotation.id)

        return Annotation.objects.filter(id__in=accessible_annotations).select_related("user", "folder", "session")

    def perform_create(self, serializer):
        """Override create to ensure user and handle file uploads for shared documents"""
        # Ensure this is a file annotation
        if not serializer.validated_data.get('file'):
            raise ValidationError("SharedDocumentViewSet only handles file annotations")

        # If folder is specified, ensure it's a shared document folder
        folder = serializer.validated_data.get('folder')
        if folder and not folder.is_shared_document_folder:
            raise ValidationError("Files can only be added to shared document folders")

        serializer.save(user=self.request.user, annotation_type="file")

    @action(detail=True, methods=["post"])
    def share(self, request, pk=None):
        """Share document with specific users or groups"""
        annotation = self.get_object()

        # Check if user can share this document
        if annotation.user != request.user and not DocumentPermission.user_can_access_annotation_with_folder_inheritance(annotation, request.user, "share"):
            return Response(
                {"error": "You do not have permission to share this document"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Validate required fields
        permissions_data = request.data.get("permissions", {})
        if not permissions_data:
            return Response(
                {"error": "permissions field is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        created_permissions = []
        errors = []

        for user in request.data["users"]:
            permissions_data['annotation'] = annotation.id
            permissions_data['user_id'] = user
            serializer = DocumentPermissionSerializer(data=permissions_data, context={"request": request})

            if serializer.is_valid():
                # check if the user already has permission
                existing_perm = DocumentPermission.objects.filter(
                    annotation=annotation,
                    user_id=user
                ).first()
                if existing_perm:
                    for key, value in permissions_data.items():
                        if key.startswith("can_"):
                            # Only update can_* fields
                            setattr(existing_perm, key, value)
                    existing_perm.save()
                    permission = existing_perm
                else:
                    permission = serializer.save()
                created_permissions.append(permission)
            else:
                errors.append(serializer.errors)

        if errors:
            # Clean up any successfully created permissions if there were errors
            for perm in created_permissions:
                perm.delete()
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "message": f"Document shared with {len(created_permissions)} recipients",
            "permissions": DocumentPermissionSerializer(created_permissions, many=True).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"])
    def unshare(self, request, pk=None):
        """Remove sharing permissions for specific users or groups"""
        annotation = self.get_object()

        # Check if user can share this document
        if annotation.user != request.user and not DocumentPermission.user_can_access_annotation_with_folder_inheritance(annotation, request.user, "share"):
            return Response(
                {"error": "You do not have permission to manage sharing for this document"},
                status=status.HTTP_403_FORBIDDEN
            )

        user_id = request.data.get("user_id")
        lab_group_id = request.data.get("lab_group_id")

        if not user_id and not lab_group_id:
            return Response(
                {"error": "Either user_id or lab_group_id must be provided"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Remove the permission
        filter_kwargs = {"annotation": annotation}
        if user_id:
            filter_kwargs["user_id"] = user_id
        if lab_group_id:
            filter_kwargs["lab_group_id"] = lab_group_id

        deleted_count, _ = DocumentPermission.objects.filter(**filter_kwargs).delete()

        return Response({
            "message": f"Removed {deleted_count} permission(s)",
            "deleted_count": deleted_count
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Download document with permission check and access tracking using X-Accel-Redirect"""
        annotation = self.get_object()

        # Check download permissions
        if annotation.user != request.user and not DocumentPermission.user_can_access_annotation_with_folder_inheritance(annotation, request.user, "download"):
            return Response(
                {"error": "You do not have permission to download this document"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Record access if not the owner
        if annotation.user != request.user:
            perm = DocumentPermission.objects.filter(
                annotation=annotation,
                user=request.user
            ).first()
            if not perm:
                # Check lab group permissions
                user_groups = request.user.lab_groups.all()
                for group in user_groups:
                    perm = DocumentPermission.objects.filter(
                        annotation=annotation,
                        lab_group=group
                    ).first()
                    if perm:
                        break

            if perm:
                perm.record_access()

        if not annotation.file:
            return Response(
                {"error": "No file attached to this annotation"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Use X-Accel-Redirect for efficient nginx file delivery
        file_name = annotation.file.name
        filename = file_name.split('/')[-1]
        view = request.query_params.get('view', None)

        response = HttpResponse(status=200)

        # Set appropriate content type and disposition based on file extension
        if view:
            if file_name.endswith(".pdf"):
                response["Content-Type"] = "application/pdf"
                response["Content-Disposition"] = f'inline; filename="{filename}"'
            elif file_name.endswith((".jpg", ".jpeg", ".png", ".gif")):
                response["Content-Type"] = "image/*"
                response["Content-Disposition"] = f'inline; filename="{filename}"'
            elif file_name.endswith((".mp4", ".webm", ".avi")):
                response["Content-Type"] = "video/mp4"
                response["Content-Disposition"] = f'inline; filename="{filename}"'
            elif file_name.endswith((".mp3", ".m4a", ".wav")):
                response["Content-Type"] = "audio/mpeg"
                response["Content-Disposition"] = f'inline; filename="{filename}"'
            else:
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
        else:
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

        # Let nginx handle the actual file serving
        response["X-Accel-Redirect"] = f"/media/{file_name}"
        return response

    @action(detail=True, methods=["get"])
    def get_signed_url(self, request, pk=None):
        """Generate a signed, time-limited download URL for secure access"""
        annotation = self.get_object()

        # Check download permissions
        if annotation.user != request.user and not DocumentPermission.user_can_access_annotation_with_folder_inheritance(annotation, request.user, "download"):
            return Response(
                {"error": "You do not have permission to download this document"},
                status=status.HTTP_403_FORBIDDEN
            )

        if not annotation.file:
            return Response(
                {"error": "No file attached to this document"},
                status=status.HTTP_404_NOT_FOUND
            )

        signer = TimestampSigner()

        # Sign the annotation data for secure access
        file_data = {
            'file': annotation.file.name,
            'id': annotation.id,
            'user_id': request.user.id
        }
        signed_token = signer.sign_object(file_data)

        return Response({
            "signed_token": signed_token,
            "expires_in": 1800  # 30 minutes
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def download_signed(self, request):
        """Download document using a signed token (no authentication required)"""
        token = request.query_params.get('token', None)
        if not token:
            return Response(
                {"error": "No token provided"},
                status=status.HTTP_400_BAD_REQUEST
            )
        signer = TimestampSigner()
        view = request.query_params.get('view', None)

        try:
            file_data = signer.unsign_object(token, max_age=60*30)
            annotation = Annotation.objects.get(id=file_data['id'])

            if not annotation.file:
                return Response(
                    {"error": "No file attached to this document"},
                    status=status.HTTP_404_NOT_FOUND
                )
            print(file_data)
            try:
                token_user = User.objects.get(id=file_data['user_id'])
                if annotation.user != token_user:
                    perm = DocumentPermission.objects.filter(
                        annotation=annotation,
                        user=token_user
                    ).first()
                    if not perm:
                        user_groups = token_user.lab_groups.all()
                        for group in user_groups:
                            perm = DocumentPermission.objects.filter(
                                annotation=annotation,
                                lab_group=group
                            ).first()
                            if perm:
                                break

                    if perm:
                        perm.record_access()
            except User.DoesNotExist:
                pass

            file_name = annotation.file.name
            filename = file_name.split('/')[-1]

            response = HttpResponse(status=200)

            if view:
                if file_name.endswith(".pdf"):
                    response["Content-Type"] = "application/pdf"
                    response["Content-Disposition"] = f'inline; filename="{filename}"'
                elif file_name.endswith((".jpg", ".jpeg", ".png", ".gif")):
                    response["Content-Type"] = "image/*"
                    response["Content-Disposition"] = f'inline; filename="{filename}"'
                elif file_name.endswith((".mp4", ".webm", ".avi")):
                    response["Content-Type"] = "video/mp4"
                    response["Content-Disposition"] = f'inline; filename="{filename}"'
                elif file_name.endswith((".mp3", ".m4a", ".wav")):
                    response["Content-Type"] = "audio/mpeg"
                    response["Content-Disposition"] = f'inline; filename="{filename}"'
                else:
                    response["Content-Disposition"] = f'attachment; filename="{filename}"'
            else:
                response["Content-Disposition"] = f'attachment; filename="{filename}"'

            # Let nginx handle the actual file serving
            response["X-Accel-Redirect"] = f"/media/{file_name}"
            return response

        except (BadSignature, SignatureExpired):
            return Response(
                {"error": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Annotation.DoesNotExist:
            return Response(
                {"error": "Document not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": "Failed to process download request"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"])
    def browse(self, request):
        """Browse documents and folders in a hierarchical structure"""
        folder_id = request.query_params.get('folder_id', None)
        filter_type = request.query_params.get('filter_type', 'all')  # 'all', 'personal', 'shared'
        user = request.user

        # Get the current folder or root level
        current_folder = None
        if folder_id:
            try:
                current_folder = AnnotationFolder.objects.get(id=folder_id)
            except AnnotationFolder.DoesNotExist:
                return Response(
                    {"error": "Folder not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Get subfolders in current directory that contain shared documents
        subfolders = self._get_folders_with_shared_documents(current_folder, filter_type)

        # Filter documents in this specific folder
        if current_folder:
            folder_documents = self.get_queryset().filter(folder=current_folder)
        else:
            folder_documents = self.get_queryset().filter(folder__isnull=True)

        # Build folder structure with metadata
        folders_data = []
        for folder in subfolders:
            # Count documents in this folder (including subfolders)
            folder_doc_count = self._count_documents_in_folder(folder, user, filter_type)
            # Only include if folder has documents or accessible subfolders with documents
            # OR if it's a personal folder owned by the user (when filter_type is 'personal' or 'all')
            should_include = (
                folder_doc_count > 0 or
                self._folder_has_accessible_content(folder, user) or
                (filter_type in ['personal', 'all'] and folder.owner == user)
            )
            if should_include:
                # Get folder permissions
                folder_permissions = DocumentPermission.objects.filter(folder=folder).select_related('user', 'lab_group', 'shared_by')

                # Calculate user's permissions for this folder
                is_folder_owner = folder.owner == user
                user_folder_permissions = {
                    'can_view': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'view'),
                    'can_download': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'download'),
                    'can_comment': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'comment'),
                    'can_edit': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'edit'),
                    'can_share': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'share'),
                    'can_delete': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'delete'),
                    'is_owner': is_folder_owner
                }

                folders_data.append({
                    'id': folder.id,
                    'name': folder.folder_name,
                    'type': 'folder',
                    'created_at': folder.created_at,
                    'updated_at': folder.updated_at,
                    'document_count': folder_doc_count,
                    'has_subfolders': self._get_folders_with_shared_documents(folder, filter_type).exists(),
                    'is_shared_document_folder': folder.is_shared_document_folder,
                    'owner': {
                        'id': folder.owner.id,
                        'username': folder.owner.username,
                        'first_name': folder.owner.first_name,
                        'last_name': folder.owner.last_name
                    } if folder.owner else None,
                    'is_personal': folder.owner == user if folder.owner else False,
                    'permissions': DocumentPermissionSerializer(folder_permissions, many=True).data,
                    'user_permissions': user_folder_permissions,
                    'sharing_stats': {
                        'total_shared': folder_permissions.count(),
                        'shared_users': folder_permissions.filter(user__isnull=False).count(),
                        'shared_groups': folder_permissions.filter(lab_group__isnull=False).count(),
                        'total_access_count': sum(perm.access_count for perm in folder_permissions)
                    }
                })

        # Get documents in current folder with filtering
        documents_data = []
        for doc in folder_documents:
            is_owner = doc.user == user
            has_shared_access = DocumentPermission.user_can_access_annotation_with_folder_inheritance(doc, user, 'view')
            can_view = is_owner or has_shared_access

            # Apply filter_type logic
            include_document = False
            if filter_type == 'all' and can_view:
                include_document = True
            elif filter_type == 'personal' and is_owner:
                include_document = True
            elif filter_type == 'shared' and has_shared_access and not is_owner:
                include_document = True

            if include_document:
                doc_serializer = self.get_serializer(doc)
                doc_data = doc_serializer.data
                doc_data['type'] = 'file'
                doc_data['is_personal'] = is_owner
                doc_data['is_shared'] = has_shared_access and not is_owner
                documents_data.append(doc_data)

        # Build breadcrumb path
        breadcrumbs = self._build_breadcrumbs(current_folder)

        return Response({
            'current_folder': {
                'id': current_folder.id if current_folder else None,
                'name': current_folder.folder_name if current_folder else 'Root',
                'parent_id': current_folder.parent_folder.id if current_folder and current_folder.parent_folder else None,
                'is_shared_document_folder': current_folder.is_shared_document_folder if current_folder else True
            },
            'breadcrumbs': breadcrumbs,
            'folders': folders_data,
            'documents': documents_data,
            'total_folders': len(folders_data),
            'total_documents': len(documents_data),
            'filter_type': filter_type
        })

    def _count_documents_in_folder(self, folder, user, filter_type='all'):
        """Recursively count documents user can access in folder and subfolders"""
        count = 0

        # Count documents directly in this folder
        folder_docs = self.get_queryset().filter(folder=folder)
        for doc in folder_docs:
            is_owner = doc.user == user
            has_shared_access = DocumentPermission.user_can_access_annotation_with_folder_inheritance(doc, user, 'view')
            can_view = is_owner or has_shared_access

            # Apply filter_type logic
            include_document = False
            if filter_type == 'all' and can_view:
                include_document = True
            elif filter_type == 'personal' and is_owner:
                include_document = True
            elif filter_type == 'shared' and has_shared_access and not is_owner:
                include_document = True

            if include_document:
                count += 1

        # Count documents in subfolders that have shared documents
        subfolders = self._get_folders_with_shared_documents(folder, filter_type)
        for subfolder in subfolders:
            count += self._count_documents_in_folder(subfolder, user, filter_type)

        return count

    def _build_breadcrumbs(self, current_folder):
        """Build breadcrumb navigation path"""
        breadcrumbs = []
        folder = current_folder

        while folder:
            breadcrumbs.insert(0, {
                'id': folder.id,
                'name': folder.folder_name
            })
            folder = folder.parent_folder

        # Add root
        breadcrumbs.insert(0, {
            'id': None,
            'name': 'Root'
        })

        return breadcrumbs

    @action(detail=False, methods=["get"])
    def my_documents(self, request):
        """Get documents owned by the current user organized by folder"""
        user = request.user
        folder_id = request.query_params.get('folder_id', None)

        # Get user's shared documents only (in shared document folders or root level with permissions)
        user_documents = Annotation.objects.filter(
            user=user,
            file__isnull=False
        ).filter(
            Q(folder__is_shared_document_folder=True) |  # In shared document folder
            Q(folder__isnull=True, document_permissions__isnull=False) |  # Root level with permissions
            Q(document_permissions__isnull=False)  # Has document permissions
        ).select_related('folder', 'session').distinct()

        if folder_id:
            try:
                folder = AnnotationFolder.objects.get(id=folder_id, is_shared_document_folder=True)
                user_documents = user_documents.filter(folder=folder)
            except AnnotationFolder.DoesNotExist:
                return Response(
                    {"error": "Folder not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            user_documents = user_documents.filter(folder__isnull=True)

        # Get user's folders at this level that contain shared documents
        if folder_id:
            current_folder = AnnotationFolder.objects.get(id=folder_id)
        else:
            current_folder = None

        # Get folders that contain file annotations accessible to this user (personal only)
        user_folders = self._get_folders_with_shared_documents(current_folder, 'personal')

        # Build response
        folders_data = []
        for folder in user_folders:
            doc_count = Annotation.objects.filter(
                user=user,
                file__isnull=False,
                folder=folder,
                folder__is_shared_document_folder=True
            ).count()

            # Get folder permissions (since this is my_documents, user is owner so they have full permissions)
            folder_permissions = DocumentPermission.objects.filter(folder=folder).select_related('user', 'lab_group', 'shared_by')
            is_folder_owner = folder.owner == user
            user_folder_permissions = {
                'can_view': True,  # Owner always has full permissions
                'can_download': True,
                'can_comment': True,
                'can_edit': True,
                'can_share': True,
                'can_delete': True,
                'is_owner': is_folder_owner
            }

            folders_data.append({
                'id': folder.id,
                'name': folder.folder_name,
                'type': 'folder',
                'created_at': folder.created_at,
                'updated_at': folder.updated_at,
                'document_count': doc_count,
                'has_subfolders': self._get_folders_with_shared_documents(folder, 'personal').exists(),
                'is_shared_document_folder': folder.is_shared_document_folder,
                'owner': {
                    'id': folder.owner.id,
                    'username': folder.owner.username,
                    'first_name': folder.owner.first_name,
                    'last_name': folder.owner.last_name
                } if folder.owner else None,
                'is_personal': folder.owner == user if folder.owner else False,
                'permissions': DocumentPermissionSerializer(folder_permissions, many=True).data,
                'user_permissions': user_folder_permissions,
                'sharing_stats': {
                    'total_shared': folder_permissions.count(),
                    'shared_users': folder_permissions.filter(user__isnull=False).count(),
                    'shared_groups': folder_permissions.filter(lab_group__isnull=False).count(),
                    'total_access_count': sum(perm.access_count for perm in folder_permissions)
                }
            })

        # Serialize documents
        documents_data = []
        for doc in user_documents:
            doc_serializer = self.get_serializer(doc)
            doc_data = doc_serializer.data
            doc_data['type'] = 'file'
            doc_data['folder_path'] = self._get_folder_path_string(doc_data.get('folder'))
            documents_data.append(doc_data)

        # Build breadcrumbs
        breadcrumbs = self._build_breadcrumbs(current_folder)

        return Response({
            'current_folder': {
                'id': current_folder.id if current_folder else None,
                'name': current_folder.folder_name if current_folder else 'My Documents',
                'parent_id': current_folder.parent_folder.id if current_folder and current_folder.parent_folder else None,
                'is_shared_document_folder': current_folder.is_shared_document_folder if current_folder else True
            },
            'breadcrumbs': breadcrumbs,
            'folders': folders_data,
            'documents': documents_data,
            'total_folders': len(folders_data),
            'total_documents': len(documents_data)
        })

    @action(detail=False, methods=["post"])
    def create_folder(self, request):
        """Create a new folder for organizing documents"""
        folder_name = request.data.get('folder_name', '').strip()
        parent_folder_id = request.data.get('parent_folder_id')

        if not folder_name:
            return Response(
                {"error": "folder_name is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate parent folder if provided
        parent_folder = None
        if parent_folder_id:
            try:
                parent_folder = AnnotationFolder.objects.get(id=parent_folder_id)
                permission = DocumentPermission.objects.filter(
                    folder=parent_folder,
                    user=request.user
                ).first()
                if not permission or not permission.can_edit:
                    return Response(
                        {"error": "You do not have permission to create folders in this location"},
                        status=status.HTTP_403_FORBIDDEN
                    )
            except AnnotationFolder.DoesNotExist:
                return Response(
                    {"error": "Parent folder not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Check for duplicate folder names at the same level
        existing_folder = AnnotationFolder.objects.filter(
            folder_name=folder_name,
            parent_folder=parent_folder,
            is_shared_document_folder=True
        ).first()

        if existing_folder:
            return Response(
                {"error": "A folder with this name already exists at this location"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the folder marked as shared document folder
        folder = AnnotationFolder.objects.create(
            folder_name=folder_name,
            parent_folder=parent_folder,
            is_shared_document_folder=True,
            owner=request.user
        )

        # Get folder permissions (newly created folder has no shared permissions yet)
        folder_permissions = DocumentPermission.objects.filter(folder=folder).select_related('user', 'lab_group', 'shared_by')
        user_folder_permissions = {
            'can_view': True,  # Owner always has full permissions
            'can_download': True,
            'can_comment': True,
            'can_edit': True,
            'can_share': True,
            'can_delete': True,
            'is_owner': True
        }

        return Response({
            'id': folder.id,
            'name': folder.folder_name,
            'type': 'folder',
            'parent_id': folder.parent_folder.id if folder.parent_folder else None,
            'created_at': folder.created_at,
            'updated_at': folder.updated_at,
            'document_count': 0,
            'has_subfolders': False,
            'is_shared_document_folder': folder.is_shared_document_folder,
            'owner': {
                'id': folder.owner.id,
                'username': folder.owner.username,
                'first_name': folder.owner.first_name,
                'last_name': folder.owner.last_name
            } if folder.owner else None,
            'is_personal': folder.owner == request.user if folder.owner else False,
            'permissions': DocumentPermissionSerializer(folder_permissions, many=True).data,
            'user_permissions': user_folder_permissions,
            'sharing_stats': {
                'total_shared': 0,  # Newly created folder has no shares
                'shared_users': 0,
                'shared_groups': 0,
                'total_access_count': 0
            }
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def search(self, request):
        """Search documents and folders with full-text search"""
        query = request.query_params.get('q', '').strip()
        folder_id = request.query_params.get('folder_id')  # Optional: search within specific folder

        if not query:
            return Response(
                {"error": "Search query 'q' parameter is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user

        # Search in documents (annotation content and names)
        document_query = Q(annotation__icontains=query) | Q(annotation_name__icontains=query)
        if folder_id:
            document_query &= Q(folder_id=folder_id)

        documents = self.get_queryset().filter(document_query)

        # Filter by permissions
        accessible_documents = []
        for doc in documents:
            if doc.user == user or DocumentPermission.user_can_access_annotation_with_folder_inheritance(doc, user, 'view'):
                accessible_documents.append(doc)

        # Search in folders
        folder_query = Q(folder_name__icontains=query)
        if folder_id:
            # Search within subfolder hierarchy
            try:
                parent_folder = AnnotationFolder.objects.get(id=folder_id)
                folder_query &= Q(parent_folder=parent_folder)
            except AnnotationFolder.DoesNotExist:
                pass

        # Filter folders to only those with shared documents
        all_folders = AnnotationFolder.objects.filter(folder_query)
        folders = []
        for folder in all_folders:
            if self._folder_has_accessible_content(folder, user):
                folders.append(folder)

        # Serialize results
        documents_data = []
        for doc in accessible_documents:
            doc_serializer = self.get_serializer(doc)
            doc_data = doc_serializer.data
            doc_data['type'] = 'file'
            # Add folder path for context
            if doc.folder:
                doc_data['folder_path'] = self._get_folder_path(doc.folder)
            else:
                doc_data['folder_path'] = "Root"
            documents_data.append(doc_data)

        folders_data = []
        for folder in folders:
            doc_count = self._count_documents_in_folder(folder, user, 'all')

            # Get folder permissions
            folder_permissions = DocumentPermission.objects.filter(folder=folder).select_related('user', 'lab_group', 'shared_by')

            # Calculate user's permissions for this folder
            is_folder_owner = folder.owner == user
            user_folder_permissions = {
                'can_view': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'view'),
                'can_download': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'download'),
                'can_comment': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'comment'),
                'can_edit': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'edit'),
                'can_share': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'share'),
                'can_delete': is_folder_owner or DocumentPermission.user_can_access_folder(folder, user, 'delete'),
                'is_owner': is_folder_owner
            }

            folders_data.append({
                'id': folder.id,
                'name': folder.folder_name,
                'type': 'folder',
                'created_at': folder.created_at,
                'updated_at': folder.updated_at,
                'document_count': doc_count,
                'folder_path': self._get_folder_path(folder) if folder.parent_folder else "Root",
                'has_subfolders': self._get_folders_with_shared_documents(folder, 'all').exists(),
                'is_shared_document_folder': folder.is_shared_document_folder,
                'owner': {
                    'id': folder.owner.id,
                    'username': folder.owner.username,
                    'first_name': folder.owner.first_name,
                    'last_name': folder.owner.last_name
                } if folder.owner else None,
                'is_personal': folder.owner == user if folder.owner else False,
                'permissions': DocumentPermissionSerializer(folder_permissions, many=True).data,
                'user_permissions': user_folder_permissions,
                'sharing_stats': {
                    'total_shared': folder_permissions.count(),
                    'shared_users': folder_permissions.filter(user__isnull=False).count(),
                    'shared_groups': folder_permissions.filter(lab_group__isnull=False).count(),
                    'total_access_count': sum(perm.access_count for perm in folder_permissions)
                }
            })

        return Response({
            'query': query,
            'total_results': len(documents_data) + len(folders_data),
            'folders': folders_data,
            'documents': documents_data
        })

    def _get_folder_path(self, folder):
        """Get the full path to a folder"""
        path_parts = []
        current = folder
        while current:
            path_parts.insert(0, current.folder_name)
            current = current.parent_folder
        return ' / '.join(path_parts)

    def _get_folder_path_string(self, folder_data):
        """Convert serialized folder data to readable path string"""
        if not folder_data:
            return "Root"

        # folder_data is an array from the serializer - reverse it to get root-to-file order
        path_parts = [folder['folder_name'] for folder in reversed(folder_data)]
        return ' / '.join(['Root'] + path_parts)

    def _get_folders_with_shared_documents(self, parent_folder=None, filter_type='all'):
        """Get folders that are designated for shared documents with ownership filtering"""
        user = self.request.user

        # Base folder filter
        if parent_folder:
            folder_filter = Q(parent_folder=parent_folder)
        else:
            folder_filter = Q(parent_folder__isnull=True)

        # Get folders marked as shared document folders
        queryset = AnnotationFolder.objects.filter(
            folder_filter,
            is_shared_document_folder=True
        )

        # Apply ownership filtering based on filter_type
        if filter_type == 'personal':
            queryset = queryset.filter(owner=user)
        elif filter_type == 'shared':
            # Folders shared with user but not owned by them
            queryset = queryset.exclude(owner=user).filter(
                Q(annotations__document_permissions__user=user) |
                Q(annotations__document_permissions__lab_group__in=user.lab_groups.all())
            ).distinct()
        elif filter_type == 'all':
            # All folders user can access (owned or shared with them)
            queryset = queryset.filter(
                Q(owner=user) |
                Q(annotations__document_permissions__user=user) |
                Q(annotations__document_permissions__lab_group__in=user.lab_groups.all())
            ).distinct()

        return queryset

    def _folder_has_accessible_content(self, folder, user):
        """Check if folder is marked for shared documents and has accessible content"""
        # If folder is marked as shared document folder, check if it has accessible files
        if folder.is_shared_document_folder:
            has_direct_files = Annotation.objects.filter(
                folder=folder,
                file__isnull=False
            ).filter(
                Q(user=user) |
                Q(document_permissions__user=user) |
                Q(document_permissions__lab_group__in=user.lab_groups.all())
            ).exists()

            if has_direct_files:
                return True

        # Check subfolders recursively that are marked for shared documents
        subfolders = self._get_folders_with_shared_documents(folder, 'all')
        for subfolder in subfolders:
            if self._folder_has_accessible_content(subfolder, user):
                return True

        return False

    @action(detail=False, methods=["get"])
    def shared_with_me(self, request):
        """Get documents shared with the current user, including folder path information"""
        user = request.user

        # Get documents shared directly with user
        user_permissions = DocumentPermission.objects.filter(user=user).select_related("annotation")

        # Get documents shared with user's lab groups
        user_groups = user.lab_groups.all()
        group_permissions = DocumentPermission.objects.filter(lab_group__in=user_groups).select_related("annotation")

        # Combine and get unique annotations
        all_permissions = list(user_permissions) + list(group_permissions)
        annotation_ids = list(set(perm.annotation.id for perm in all_permissions if perm.annotation.file))

        annotations = Annotation.objects.filter(id__in=annotation_ids).select_related("user", "folder", "session")

        # Apply filtering and ordering
        queryset = self.filter_queryset(annotations)
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            # Enhance response data with folder path information
            response_data = serializer.data
            for doc_data in response_data:
                doc_data['folder_path'] = self._get_folder_path_string(doc_data.get('folder'))
            return self.get_paginated_response(response_data)

        serializer = self.get_serializer(queryset, many=True)
        # Enhance response data with folder path information
        response_data = serializer.data
        for doc_data in response_data:
            doc_data['folder_path'] = self._get_folder_path_string(doc_data.get('folder'))
        return Response(response_data)

    @action(detail=False, methods=["post"])
    def bind_chunked_file(self, request):
        """
        Bind a file that was uploaded in chunks to create a shared document
        """

        upload_id = request.data.get('chunked_upload_id')
        annotation_name = request.data.get('annotation_name', '')
        annotation_text = request.data.get('annotation', '')
        folder_id = request.data.get('folder_id') or request.data.get('folder')

        # Validation
        if not upload_id:
            return Response(
                {'error': 'upload_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Get and validate chunked upload
            chunked_upload = ChunkedUpload.objects.get(id=upload_id)

            # Permission check - user must own the upload
            if chunked_upload.user != request.user and not request.user.is_staff:
                return Response(
                    {'error': 'You do not have permission to use this upload'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Verify upload is completed
            if not chunked_upload.completed_at:
                return Response(
                    {'error': 'Upload is not completed yet'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate folder if provided
            folder = None
            if folder_id:
                try:
                    folder = AnnotationFolder.objects.get(id=folder_id, is_shared_document_folder=True)
                    # Could add folder permission checks here if needed
                except AnnotationFolder.DoesNotExist:
                    return Response(
                        {'error': 'Shared document folder not found'},
                        status=status.HTTP_404_NOT_FOUND
                    )

            # Use chunked upload filename if no name provided
            if not annotation_name:
                annotation_name = chunked_upload.filename or 'Uploaded Document'

            # Create the annotation with file
            with open(chunked_upload.file.path, 'rb') as file:
                django_file = djangoFile(file)
                annotation = Annotation(
                    annotation=annotation_text or annotation_name,
                    annotation_name=annotation_name,
                    user=request.user,
                    annotation_type="file"
                )
                
                if folder:
                    annotation.folder = folder

                annotation.file.save(annotation_name, django_file, save=True)
                annotation.save()
                
                DocumentPermission.objects.create(
                    annotation=annotation,
                    user=request.user,
                    can_view=True,
                    can_download=True,
                    can_comment=True,
                    can_edit=True,
                    can_share=True,
                    can_delete=True,
                    shared_by=request.user
                )
            
            # Clean up chunked upload
            chunked_upload.delete()
            
            # Return the created document
            serializer = self.get_serializer(annotation)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except ChunkedUpload.DoesNotExist:
            return Response(
                {'error': 'Upload not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {'error': f'Failed to bind file: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=["delete"])
    def delete_folder(self, request):
        """Delete a shared document folder that the user owns"""
        folder_id = request.query_params.get('folder_id')
        
        if not folder_id:
            return Response(
                {'error': 'folder_id parameter is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            folder = AnnotationFolder.objects.get(id=folder_id)
        except AnnotationFolder.DoesNotExist:
            return Response(
                {'error': 'Folder not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if folder is a shared document folder
        if not folder.is_shared_document_folder:
            return Response(
                {'error': 'This folder is not a shared document folder'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check ownership
        if folder.owner != request.user:
            return Response(
                {'error': 'You can only delete folders you own'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if folder has any documents
        document_count = Annotation.objects.filter(folder=folder).count()
        if document_count > 0:
            return Response(
                {'error': f'Cannot delete folder with {document_count} document(s). Move or delete documents first.'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if folder has subfolders
        subfolder_count = AnnotationFolder.objects.filter(parent_folder=folder).count()
        if subfolder_count > 0:
            return Response(
                {'error': f'Cannot delete folder with {subfolder_count} subfolder(s). Delete subfolders first.'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Delete the folder
        folder_name = folder.folder_name
        folder.delete()
        
        return Response(
            {'message': f'Folder "{folder_name}" deleted successfully'}, 
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=["post"])
    def share_folder(self, request):
        """Share a folder with users or groups with granular permissions"""
        folder_id = request.data.get('folder_id')
        
        if not folder_id:
            return Response(
                {'error': 'folder_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            folder = AnnotationFolder.objects.get(id=folder_id)
        except AnnotationFolder.DoesNotExist:
            return Response(
                {'error': 'Folder not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if folder is a shared document folder
        if not folder.is_shared_document_folder:
            return Response(
                {'error': 'Can only share folders marked as shared document folders'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if user can share this folder
        if folder.owner != request.user and not DocumentPermission.user_can_access_folder(folder, request.user, "share"):
            return Response(
                {'error': 'You do not have permission to share this folder'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        users = request.data.get('users', [])
        lab_groups = request.data.get('lab_groups', [])
        permissions = request.data.get('permissions', {})
        
        if not users and not lab_groups:
            return Response(
                {'error': 'At least one user or lab_group must be specified'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create permissions
        created_permissions = []
        errors = []
        
        # Create user permissions
        for user_id in users:
            try:
                user = User.objects.get(id=user_id)
                # Check if permission already exists
                existing = DocumentPermission.objects.filter(folder=folder, user=user).first()
                if existing:
                    errors.append(f"Permission already exists for user {user.username}")
                    continue
                
                permission = DocumentPermission.objects.create(
                    folder=folder,
                    user=user,
                    shared_by=request.user,
                    can_view=permissions.get('can_view', True),
                    can_download=permissions.get('can_download', True),
                    can_comment=permissions.get('can_comment', False),
                    can_edit=permissions.get('can_edit', False),
                    can_share=permissions.get('can_share', False),
                    can_delete=permissions.get('can_delete', False)
                )
                created_permissions.append(permission)
            except User.DoesNotExist:
                errors.append(f"User with id {user_id} not found")
            except Exception as e:
                errors.append(f"Error creating permission for user {user_id}: {str(e)}")
        
        # Create lab group permissions
        for group_id in lab_groups:
            try:
                lab_group = LabGroup.objects.get(id=group_id)
                # Check if permission already exists
                existing = DocumentPermission.objects.filter(folder=folder, lab_group=lab_group).first()
                if existing:
                    errors.append(f"Permission already exists for lab group {lab_group.name}")
                    continue
                
                permission = DocumentPermission.objects.create(
                    folder=folder,
                    lab_group=lab_group,
                    shared_by=request.user,
                    can_view=permissions.get('can_view', True),
                    can_download=permissions.get('can_download', True),
                    can_comment=permissions.get('can_comment', False),
                    can_edit=permissions.get('can_edit', False),
                    can_share=permissions.get('can_share', False),
                    can_delete=permissions.get('can_delete', False)
                )
                created_permissions.append(permission)
            except LabGroup.DoesNotExist:
                errors.append(f"Lab group with id {group_id} not found")
            except Exception as e:
                errors.append(f"Error creating permission for lab group {group_id}: {str(e)}")
        
        if errors and not created_permissions:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        
        response_data = {
            'message': f'Folder shared with {len(created_permissions)} recipients',
            'permissions': DocumentPermissionSerializer(created_permissions, many=True).data
        }
        
        if errors:
            response_data['warnings'] = errors
        
        return Response(response_data, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=["delete"])
    def unshare_folder(self, request):
        """Remove folder sharing permissions for specific users or groups"""
        folder_id = request.query_params.get('folder_id')
        
        if not folder_id:
            return Response(
                {'error': 'folder_id parameter is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            folder = AnnotationFolder.objects.get(id=folder_id)
        except AnnotationFolder.DoesNotExist:
            return Response(
                {'error': 'Folder not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if user can manage sharing for this folder
        if folder.owner != request.user and not DocumentPermission.user_can_access_folder(folder, request.user, "share"):
            return Response(
                {'error': 'You do not have permission to manage sharing for this folder'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = request.data.get('user_id')
        lab_group_id = request.data.get('lab_group_id')
        
        if not user_id and not lab_group_id:
            return Response(
                {'error': 'Either user_id or lab_group_id must be provided'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Remove the permission
        filter_kwargs = {'folder': folder}
        if user_id:
            filter_kwargs['user_id'] = user_id
        if lab_group_id:
            filter_kwargs['lab_group_id'] = lab_group_id
        
        deleted_count, _ = DocumentPermission.objects.filter(**filter_kwargs).delete()
        
        return Response({
            'message': f'Removed {deleted_count} folder permission(s)',
            'deleted_count': deleted_count
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=["get"])
    def folder_permissions(self, request):
        """Get all permissions for a specific folder"""
        folder_id = request.query_params.get('folder_id')
        
        if not folder_id:
            return Response(
                {'error': 'folder_id parameter is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            folder = AnnotationFolder.objects.get(id=folder_id)
        except AnnotationFolder.DoesNotExist:
            return Response(
                {'error': 'Folder not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if user can view this folder
        if folder.owner != request.user and not DocumentPermission.user_can_access_folder(folder, request.user, "view"):
            return Response(
                {'error': 'You do not have permission to view this folder'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get all permissions for this folder
        permissions = DocumentPermission.objects.filter(folder=folder).select_related('user', 'lab_group', 'shared_by')
        
        return Response({
            'folder': {
                'id': folder.id,
                'name': folder.folder_name,
                'owner': {
                    'id': folder.owner.id,
                    'username': folder.owner.username,
                    'first_name': folder.owner.first_name,
                    'last_name': folder.owner.last_name
                } if folder.owner else None
            },
            'permissions': DocumentPermissionSerializer(permissions, many=True).data,
            'total_permissions': permissions.count()
        })

    @action(detail=False, methods=["post"])
    def rename(self, request):
        annotation_id = request.data.get('annotation_id', None)
        folder_id = request.data.get('folder_id', None)
        annotation_name = request.data.get('annotation_name', None)
        folder_name = request.data.get('folder_name', None)
        if annotation_id and folder_id:
            return Response(
                {"error": "You can only rename either an annotation or a folder, not both."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not annotation_id and not folder_id:
            return Response(
                {"error": "You must provide either an annotation_id or a folder_id."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not annotation_name and not folder_name:
            return Response(
                {"error": "You must provide either an annotation_name or a folder_name."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if annotation_id and annotation_name:
            try:
                annotation = Annotation.objects.get(id=annotation_id)
                if not annotation.file:
                    return Response(
                        {"error": "Annotation does not have an associated file."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                if not annotation.user == request.user and not DocumentPermission.user_can_access_annotation_with_folder_inheritance(annotation, request.user, "edit"):
                    return Response(
                        {"error": "You do not have permission to rename this annotation."},
                        status=status.HTTP_403_FORBIDDEN
                    )
                if Annotation.objects.filter(
                    annotation_name=annotation_name,
                    folder=annotation.folder
                ).exists():
                    return Response(
                        {"error": "An annotation with this name already exists in the same folder."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                annotation.annotation_name = annotation_name
                annotation.save()
                return Response(
                    {"message": "Annotation renamed successfully.", "annotation_name": annotation.annotation_name},
                    status=status.HTTP_200_OK
                )
            except Annotation.DoesNotExist:
                return Response(
                    {"error": "Annotation not found."},
                    status=status.HTTP_404_NOT_FOUND
                )
        elif folder_id and folder_name:
            try:
                folder = AnnotationFolder.objects.get(id=folder_id, owner=request.user)
                if not folder.is_shared_document_folder:
                    return Response(
                        {"error": "Only shared document folders can be renamed."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                if not folder.owner == request.user and not DocumentPermission.user_can_access_folder(folder, request.user, "edit"):
                    return Response(
                        {"error": "You do not have permission to rename this folder."},
                        status=status.HTTP_403_FORBIDDEN
                    )
                if AnnotationFolder.objects.filter(
                    folder_name=folder_name,
                    parent_folder=folder.parent_folder,
                    is_shared_document_folder=True
                ).exists():
                    return Response(
                        {"error": "A folder with this name already exists in the same location."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                folder.folder_name = folder_name
                folder.save()
                return Response(
                    {"message": "Folder renamed successfully.", "folder_name": folder.folder_name},
                    status=status.HTTP_200_OK
                )
            except AnnotationFolder.DoesNotExist:
                return Response(
                    {"error": "Folder not found."},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {"error": "Invalid request parameters."},
                status=status.HTTP_400_BAD_REQUEST
            )


class DocumentPermissionViewSet(ModelViewSet, FilterMixin):
    """ViewSet for managing document permissions"""
    queryset = DocumentPermission.objects.all()
    serializer_class = DocumentPermissionSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["annotation", "user", "lab_group"]
    ordering_fields = ["shared_at", "last_accessed"]
    ordering = ["-shared_at"]
    pagination_class = LimitOffsetPagination
    
    def get_queryset(self):
        """Get permissions for documents user owns or can manage"""
        user = self.request.user
        
        # Get annotations user owns
        owned_annotations = Annotation.objects.filter(user=user, file__isnull=False)
        
        # Get annotations user can share
        shareable_annotations = []
        for annotation in Annotation.objects.filter(file__isnull=False):
            if DocumentPermission.user_can_access_annotation_with_folder_inheritance(annotation, user, "share"):
                shareable_annotations.append(annotation.id)
        
        all_annotation_ids = list(owned_annotations.values_list("id", flat=True)) + shareable_annotations
        
        return DocumentPermission.objects.filter(annotation_id__in=all_annotation_ids).select_related(
            "annotation", "user", "lab_group", "shared_by"
        )
    
    def perform_create(self, serializer):
        """Set shared_by to current user"""
        serializer.save(shared_by=self.request.user)
    
    @action(detail=False, methods=["get"])
    def my_shares(self, request):
        """Get all permissions created by the current user"""
        permissions = DocumentPermission.objects.filter(shared_by=request.user).select_related(
            "annotation", "user", "lab_group"
        )
        
        queryset = self.filter_queryset(permissions)
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class ImportTrackerViewSet(ModelViewSet):
    """ViewSet for managing import tracking records"""
    queryset = ImportTracker.objects.all()
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['import_id', 'archive_path', 'user__username']
    ordering_fields = ['import_started_at', 'import_completed_at', 'archive_size_bytes']
    ordering = ['-import_started_at']
    filterset_fields = ['import_status', 'user', 'can_revert']
    pagination_class = LimitOffsetPagination
    
    def get_queryset(self):
        """Filter import tracking records by user permissions"""
        user = self.request.user
        if user.is_staff:
            return ImportTracker.objects.all()
        return ImportTracker.objects.filter(user=user)
    
    def get_serializer_class(self):
        """Use appropriate serializer based on action"""
        if self.action == 'list':
            return ImportTrackerListSerializer
        return ImportTrackerSerializer
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def revert_import(self, request, pk=None):
        """
        Revert an import by removing all imported data
        
        This action completely reverses the import process by:
        - Deleting all imported objects in proper dependency order
        - Removing all imported files
        - Clearing all imported relationships
        - Marking the import as reverted
        
        Returns:
            Response: Status of revert operation with detailed information
        """
        import_tracker = self.get_object()
        user = request.user
        
        # Check permissions - only the import user or staff can revert
        if import_tracker.user != user and not user.is_staff:
            raise PermissionDenied("You don't have permission to revert this import")
        
        # Check if import can be reverted
        if not import_tracker.can_revert:
            return Response(
                {'error': 'This import cannot be reverted. It may have already been reverted or failed during import.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if import_tracker.import_status != 'completed':
            return Response(
                {'error': 'Only completed imports can be reverted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:


            reverter = ImportReverter(import_tracker, user)
            revert_result = reverter.revert_import()
            
            if revert_result['success']:
                import_tracker.can_revert = False
                import_tracker.reverted_at = timezone.now()
                import_tracker.reverted_by = user
                import_tracker.import_status = 'reverted'
                import_tracker.save()
                
                return Response({
                    'success': True,
                    'message': 'Import successfully reverted',
                    'stats': revert_result['stats']
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'error': revert_result.get('error', 'Unknown error during reversion'),
                    'details': revert_result.get('details', {})
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Error during import reversion: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def user_import_stats(self, request):
        """
        Get import statistics for the current user
        
        Returns:
            Response: Import statistics including counts and summaries
        """
        user = request.user
        
        # Get queryset based on permissions
        if user.is_staff:
            queryset = ImportTracker.objects.all()
        else:
            queryset = ImportTracker.objects.filter(user=user)
        
        # Calculate statistics
        total_imports = queryset.count()
        completed_imports = queryset.filter(import_status='completed').count()
        failed_imports = queryset.filter(import_status='failed').count()
        reverted_imports = queryset.filter(import_status='reverted').count()
        in_progress_imports = queryset.filter(import_status='in_progress').count()
        
        # Calculate total objects and files
        total_objects_created = sum(queryset.values_list('total_objects_created', flat=True))
        total_files_imported = sum(queryset.values_list('total_files_imported', flat=True))
        
        # Get recent imports
        recent_imports = queryset.order_by('-import_started_at')[:5]
        recent_serializer = ImportTrackerListSerializer(recent_imports, many=True)
        
        return Response({
            'stats': {
                'total_imports': total_imports,
                'completed_imports': completed_imports,
                'failed_imports': failed_imports,
                'reverted_imports': reverted_imports,
                'in_progress_imports': in_progress_imports,
                'total_objects_created': total_objects_created,
                'total_files_imported': total_files_imported,
                'success_rate': round((completed_imports / total_imports * 100), 2) if total_imports > 0 else 0
            },
            'recent_imports': recent_serializer.data
        }, status=status.HTTP_200_OK)


class HistoricalRecordsViewSet(ReadOnlyModelViewSet):
    """
    Generic endpoint for accessing historical records of any model
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['history_user__username', 'history_type']
    ordering_fields = ['history_date', 'history_type']
    filterset_fields = ['history_type', 'history_user']
    pagination_class = LimitOffsetPagination
    queryset = Annotation.history.all()
    
    def get_queryset(self):
        """Get historical records for the specified model"""
        model_name = self.request.query_params.get('model')
        
        # Define allowed models that have history tracking
        allowed_models = {
            'annotation': Annotation,
            'annotationfolder': AnnotationFolder,
            'protocolmodel': ProtocolModel,
            'protocolstep': ProtocolStep,
            'session': Session,
            'instrument': Instrument,
            'instrumentusage': InstrumentUsage,
            'instrumentjob': InstrumentJob,
            'storedreagent': StoredReagent,
            'reagentaction': ReagentAction,
            'maintenancelog': MaintenanceLog,
            'supportinformation': SupportInformation,
            'labgroup': LabGroup,
            'sitesettings': SiteSettings,
            'backuplog': BackupLog,
        }
        
        if not model_name or model_name not in allowed_models:
            return Annotation.history.all()
            
        model_class = allowed_models[model_name]
        
        # Get the historical model
        if hasattr(model_class, 'history'):
            return model_class.history.all()
        else:
            return Annotation.history.all()
    
    serializer_class = HistoricalRecordSerializer
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get summary statistics for historical records"""
        queryset = self.get_queryset()
        model_name = request.query_params.get('model', 'annotation')
        
        total_records = queryset.count()
        created_records = queryset.filter(history_type='+').count()
        updated_records = queryset.filter(history_type='~').count()
        deleted_records = queryset.filter(history_type='-').count()
        
        # Recent changes (last 7 days)
        recent_date = timezone.now() - timedelta(days=7)
        recent_changes = queryset.filter(history_date__gte=recent_date).count()
        
        return Response({
            'model_name': model_name,
            'total_records': total_records,
            'created_records': created_records,
            'updated_records': updated_records,
            'deleted_records': deleted_records,
            'recent_changes_7_days': recent_changes
        })
    
    @action(detail=False, methods=['get'])
    def timeline(self, request):
        """Get timeline of changes for the model"""
        queryset = self.get_queryset()
        model_name = request.query_params.get('model', 'annotation')
        
        # Get changes grouped by date
        days_back = int(request.query_params.get('days', 30))
        start_date = timezone.now() - timedelta(days=days_back)
        
        timeline_data = queryset.filter(
            history_date__gte=start_date
        ).extra(
            select={'date': 'DATE(history_date)'}
        ).values('date').annotate(
            total_changes=Count('history_id'),
            created=Count('history_id', filter=Q(history_type='+')),
            updated=Count('history_id', filter=Q(history_type='~')),
            deleted=Count('history_id', filter=Q(history_type='-'))
        ).order_by('date')
        
        return Response({
            'model_name': model_name,
            'timeline': list(timeline_data),
            'period_days': days_back
        })



class ServiceTierViewSet(ModelViewSet):
    permission_classes = [IsCoreFacilityPermission]
    queryset = ServiceTier.objects.all()
    serializer_class = ServiceTierSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    search_fields = ['name', 'description']
    filterset_fields = ['lab_group', 'is_active']
    
    def get_queryset(self):
        # Only show service tiers for core facility lab groups the user belongs to
        user_core_facility_groups = self.request.user.lab_groups.filter(is_core_facility=True)
        return ServiceTier.objects.filter(lab_group__in=user_core_facility_groups)
    
    def perform_create(self, serializer):
        # Ensure the service tier is created for a core facility lab group
        lab_group = serializer.validated_data['lab_group']
        if not lab_group.is_core_facility:
            raise ValidationError("Service tiers can only be created for core facility lab groups")
        
        # Ensure user has access to this lab group
        if not self.request.user.lab_groups.filter(id=lab_group.id, is_core_facility=True).exists():
            raise PermissionDenied("You don't have permission to create service tiers for this lab group")
        
        serializer.save()


class ServicePriceViewSet(ModelViewSet):
    permission_classes = [IsCoreFacilityPermission]
    queryset = ServicePrice.objects.all()
    serializer_class = ServicePriceSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['service_tier', 'instrument', 'billing_unit', 'is_active']
    
    def get_queryset(self):
        # Only show service prices for core facility lab groups the user belongs to
        user_core_facility_groups = self.request.user.lab_groups.filter(is_core_facility=True)
        return ServicePrice.objects.filter(service_tier__lab_group__in=user_core_facility_groups)
    
    def perform_create(self, serializer):
        # Ensure the service price is created for a core facility lab group
        service_tier = serializer.validated_data['service_tier']
        if not service_tier.lab_group.is_core_facility:
            raise ValidationError("Service prices can only be created for core facility service tiers")
        
        # Ensure user has access to this service tier's lab group
        if not self.request.user.lab_groups.filter(id=service_tier.lab_group.id, is_core_facility=True).exists():
            raise PermissionDenied("You don't have permission to create service prices for this service tier")
        
        serializer.save()


class BillingRecordViewSet(ModelViewSet):
    permission_classes = [IsCoreFacilityPermission]
    queryset = BillingRecord.objects.all()
    serializer_class = BillingRecordSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'billing_date', 'user', 'service_tier']
    ordering_fields = ['billing_date', 'total_amount', 'created_at']
    ordering = ['-billing_date']
    
    def get_queryset(self):
        # Only show billing records for core facility lab groups the user belongs to
        user_core_facility_groups = self.request.user.lab_groups.filter(is_core_facility=True)
        return BillingRecord.objects.filter(service_tier__lab_group__in=user_core_facility_groups)
    
    def perform_create(self, serializer):
        # Ensure the billing record is created for a core facility lab group
        service_tier = serializer.validated_data['service_tier']
        if not service_tier.lab_group.is_core_facility:
            raise ValidationError("Billing records can only be created for core facility service tiers")

        # Ensure user has access to this service tier's lab group
        if not self.request.user.lab_groups.filter(id=service_tier.lab_group.id, is_core_facility=True).exists():
            raise PermissionDenied("You don't have permission to create billing records for this service tier")
        
        serializer.save()
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get billing summary statistics"""
        queryset = self.get_queryset()
        
        # Get query parameters for filtering
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        status = request.query_params.get('status')
        
        if start_date:
            queryset = queryset.filter(billing_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(billing_date__lte=end_date)
        if status:
            queryset = queryset.filter(status=status)
        
        summary_data = {
            'total_records': queryset.count(),
            'total_amount': queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00'),
            'by_status': {},
            'monthly_totals': {}
        }
        
        # Group by status
        for status_choice in BillingRecord.STATUS_CHOICES:
            status_key = status_choice[0]
            status_queryset = queryset.filter(status=status_key)
            summary_data['by_status'][status_key] = {
                'count': status_queryset.count(),
                'total_amount': status_queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
            }
        
        # Monthly totals for current year
        current_year = timezone.now().year
        monthly_data = queryset.filter(
            billing_date__year=current_year
        ).extra(
            select={'month': 'EXTRACT(month FROM billing_date)'}
        ).values('month').annotate(
            count=Count('id'),
            total_amount=Sum('total_amount')
        ).order_by('month')
        
        for month_data in monthly_data:
            month = int(month_data['month'])
            summary_data['monthly_totals'][month] = {
                'count': month_data['count'],
                'total_amount': month_data['total_amount'] or Decimal('0.00')
            }
        
        return Response(summary_data)
    
    @action(detail=False, methods=['post'])
    def calculate_billing(self, request):
        """Calculate billing for an instrument job"""
        job_id = request.data.get('job_id')
        service_tier_id = request.data.get('service_tier_id')
        
        if not job_id or not service_tier_id:
            return Response({'error': 'job_id and service_tier_id are required'}, status=400)
        
        try:
            job = InstrumentJob.objects.get(id=job_id)
            service_tier = ServiceTier.objects.get(id=service_tier_id)
            
            # Ensure user has access to this service tier
            if not self.request.user.lab_groups.filter(id=service_tier.lab_group.id, is_core_facility=True).exists():
                raise PermissionDenied("You don't have permission to calculate billing for this service tier")
            
            # Get pricing for this instrument and service tier
            try:
                instrument_price = ServicePrice.objects.get(
                    service_tier=service_tier,
                    instrument=job.instrument,
                    billing_unit='per_hour_instrument',
                    is_active=True
                )
            except ServicePrice.DoesNotExist:
                instrument_price = None
            
            try:
                personnel_price = ServicePrice.objects.get(
                    service_tier=service_tier,
                    instrument=job.instrument,
                    billing_unit='per_hour_personnel',
                    is_active=True
                )
            except ServicePrice.DoesNotExist:
                personnel_price = None
            
            # Calculate costs
            instrument_cost = Decimal('0.00')
            personnel_cost = Decimal('0.00')
            
            if instrument_price and job.instrument_hours:
                instrument_cost = Decimal(str(job.instrument_hours)) * instrument_price.price
            
            if personnel_price and job.personnel_hours:
                personnel_cost = Decimal(str(job.personnel_hours)) * personnel_price.price
            
            total_amount = instrument_cost + personnel_cost
            
            return Response({
                'instrument_hours': job.instrument_hours,
                'instrument_rate': instrument_price.price if instrument_price else None,
                'instrument_cost': instrument_cost,
                'personnel_hours': job.personnel_hours,
                'personnel_rate': personnel_price.price if personnel_price else None,
                'personnel_cost': personnel_cost,
                'total_amount': total_amount,
                'currency': instrument_price.currency if instrument_price else (personnel_price.currency if personnel_price else 'USD')
            })
            
        except InstrumentJob.DoesNotExist:
            return Response({'error': 'Instrument job not found'}, status=404)
        except ServiceTier.DoesNotExist:
            return Response({'error': 'Service tier not found'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class PublicPricingViewSet(ReadOnlyModelViewSet):
    """
    Public pricing display viewset for showing pricing information to users
    """
    permission_classes = [AllowAny]
    
    def get_queryset(self):
        # This viewset doesn't use a standard queryset
        return LabGroup.objects.filter(is_core_facility=True)
    
    @action(detail=False, methods=['get'])
    def pricing_display(self, request):
        """
        Get public pricing display for all or specific lab groups
        """
        from cc.billing_services import PublicPricingService
        
        lab_group_id = request.query_params.get('lab_group_id')
        
        try:
            if lab_group_id:
                lab_group = LabGroup.objects.get(id=lab_group_id, is_core_facility=True)
                pricing_service = PublicPricingService(lab_group)
                pricing_display = pricing_service.get_public_pricing_display()
            else:
                # Show all core facility pricing
                pricing_service = PublicPricingService()
                pricing_display = pricing_service.get_public_pricing_display()
            
            return Response({
                'success': True,
                'pricing_display': pricing_display
            })
            
        except LabGroup.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Lab group not found'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to get pricing display: {str(e)}'
            }, status=500)
    
    @action(detail=False, methods=['get'])
    def quote_form_config(self, request):
        """
        Get configuration for quote request form
        """
        from cc.billing_services import PublicPricingService
        
        lab_group_id = request.query_params.get('lab_group_id')
        
        try:
            if lab_group_id:
                lab_group = LabGroup.objects.get(id=lab_group_id, is_core_facility=True)
                pricing_service = PublicPricingService(lab_group)
            else:
                pricing_service = PublicPricingService()
            
            form_config = pricing_service.generate_quote_form_config()
            
            return Response({
                'success': True,
                'form_config': form_config
            })
            
        except LabGroup.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Lab group not found'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to get form config: {str(e)}'
            }, status=500)
    
    @action(detail=False, methods=['post'])
    def generate_quote(self, request):
        """
        Generate a quote based on the request parameters
        """
        from cc.billing_services import QuoteCalculator
        
        service_tier_id = request.data.get('service_tier_id')
        
        if not service_tier_id:
            return Response({
                'success': False,
                'error': 'service_tier_id is required'
            }, status=400)
        
        try:
            service_tier = ServiceTier.objects.get(id=service_tier_id, is_active=True)
            calculator = QuoteCalculator(service_tier)
            quote_result = calculator.calculate_quote(request.data)
            
            return Response(quote_result)
            
        except ServiceTier.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Service tier not found'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to generate quote: {str(e)}'
            }, status=500)
    
    @action(detail=False, methods=['get'])
    def pricing_options(self, request):
        """
        Get pricing options for a specific instrument and service tier
        """
        from cc.billing_services import QuoteCalculator
        
        instrument_id = request.query_params.get('instrument_id')
        service_tier_id = request.query_params.get('service_tier_id')
        
        if not instrument_id or not service_tier_id:
            return Response({
                'success': False,
                'error': 'instrument_id and service_tier_id are required'
            }, status=400)
        
        try:
            instrument = Instrument.objects.get(id=instrument_id, enabled=True)
            service_tier = ServiceTier.objects.get(id=service_tier_id, is_active=True)
            
            calculator = QuoteCalculator(service_tier)
            pricing_options = calculator.get_pricing_options(instrument)
            
            return Response({
                'success': True,
                'pricing_options': pricing_options
            })
            
        except (Instrument.DoesNotExist, ServiceTier.DoesNotExist):
            return Response({
                'success': False,
                'error': 'Instrument or service tier not found'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to get pricing options: {str(e)}'
            }, status=500)


class BillingManagementViewSet(ModelViewSet):
    """
    Billing management viewset for core facility administrators
    """
    permission_classes = [IsCoreFacilityPermission]
    
    def get_queryset(self):
        # This viewset doesn't use a standard queryset
        return ServiceTier.objects.filter(
            lab_group__in=self.request.user.lab_groups.filter(is_core_facility=True)
        )
    
    @action(detail=False, methods=['get'])
    def pricing_summary(self, request):
        """
        Get pricing summary for lab groups user has access to
        """
        from cc.billing_services import PricingManager
        
        lab_group_id = request.query_params.get('lab_group_id')
        
        try:
            if lab_group_id:
                lab_group = LabGroup.objects.get(
                    id=lab_group_id, 
                    is_core_facility=True,
                    id__in=self.request.user.lab_groups.filter(is_core_facility=True)
                )
                manager = PricingManager(lab_group)
                summary = manager.get_pricing_summary()
            else:
                # Get summary for all accessible lab groups
                user_lab_groups = self.request.user.lab_groups.filter(is_core_facility=True)
                summaries = []
                
                for lab_group in user_lab_groups:
                    manager = PricingManager(lab_group)
                    summary = manager.get_pricing_summary()
                    summaries.append(summary)
                
                summary = {'lab_groups': summaries}
            
            return Response({
                'success': True,
                'pricing_summary': summary
            })
            
        except LabGroup.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Lab group not found or access denied'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to get pricing summary: {str(e)}'
            }, status=500)
    
    @action(detail=False, methods=['post'])
    def create_service_tier(self, request):
        """
        Create a new service tier
        """
        from cc.billing_services import PricingManager
        
        lab_group_id = request.data.get('lab_group_id')
        name = request.data.get('name')
        description = request.data.get('description', '')
        
        if not lab_group_id or not name:
            return Response({
                'success': False,
                'error': 'lab_group_id and name are required'
            }, status=400)
        
        try:
            lab_group = LabGroup.objects.get(
                id=lab_group_id,
                is_core_facility=True,
                id__in=self.request.user.lab_groups.filter(is_core_facility=True)
            )
            
            manager = PricingManager(lab_group)
            service_tier = manager.create_service_tier(name, description)
            
            return Response({
                'success': True,
                'service_tier': {
                    'id': service_tier.id,
                    'name': service_tier.name,
                    'description': service_tier.description,
                    'lab_group': service_tier.lab_group.name,
                    'is_active': service_tier.is_active
                }
            })
            
        except LabGroup.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Lab group not found or access denied'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to create service tier: {str(e)}'
            }, status=500)
    
    @action(detail=False, methods=['post'])
    def bulk_update_prices(self, request):
        """
        Bulk update multiple service prices
        """
        from cc.billing_services import PricingManager
        
        lab_group_id = request.data.get('lab_group_id')
        price_updates = request.data.get('price_updates', [])
        
        if not lab_group_id or not price_updates:
            return Response({
                'success': False,
                'error': 'lab_group_id and price_updates are required'
            }, status=400)
        
        try:
            lab_group = LabGroup.objects.get(
                id=lab_group_id,
                is_core_facility=True,
                id__in=self.request.user.lab_groups.filter(is_core_facility=True)
            )
            
            manager = PricingManager(lab_group)
            updated_prices = manager.bulk_update_prices(price_updates)
            
            return Response({
                'success': True,
                'updated_count': len(updated_prices),
                'updated_prices': [
                    {
                        'id': price.id,
                        'service_tier': price.service_tier.name,
                        'instrument': price.instrument.instrument_name,
                        'billing_unit': price.billing_unit,
                        'price': price.price,
                        'currency': price.currency
                    }
                    for price in updated_prices
                ]
            })
            
        except LabGroup.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Lab group not found or access denied'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to bulk update prices: {str(e)}'
            }, status=500)
    
    @action(detail=False, methods=['post'])
    def create_service_price(self, request):
        """
        Create a new service price
        """
        from cc.billing_services import PricingManager
        from decimal import Decimal
        
        lab_group_id = request.data.get('lab_group_id')
        service_tier_id = request.data.get('service_tier_id')
        instrument_id = request.data.get('instrument_id')
        price = request.data.get('price')
        billing_unit = request.data.get('billing_unit')
        
        if not all([lab_group_id, service_tier_id, instrument_id, price, billing_unit]):
            return Response({
                'success': False,
                'error': 'lab_group_id, service_tier_id, instrument_id, price, and billing_unit are required'
            }, status=400)
        
        try:
            lab_group = LabGroup.objects.get(
                id=lab_group_id,
                is_core_facility=True,
                id__in=self.request.user.lab_groups.filter(is_core_facility=True)
            )
            
            service_tier = ServiceTier.objects.get(id=service_tier_id, lab_group=lab_group)
            instrument = Instrument.objects.get(id=instrument_id, enabled=True)
            
            manager = PricingManager(lab_group)
            service_price = manager.create_service_price(
                service_tier=service_tier,
                instrument=instrument,
                price=Decimal(str(price)),
                billing_unit=billing_unit,
                currency=request.data.get('currency', 'USD'),
                effective_date=request.data.get('effective_date', timezone.now().date()),
                expiry_date=request.data.get('expiry_date')
            )
            
            return Response({
                'success': True,
                'service_price': {
                    'id': service_price.id,
                    'service_tier': service_price.service_tier.name,
                    'instrument': service_price.instrument.instrument_name,
                    'billing_unit': service_price.billing_unit,
                    'price': service_price.price,
                    'currency': service_price.currency,
                    'effective_date': service_price.effective_date,
                    'expiry_date': service_price.expiry_date,
                    'is_active': service_price.is_active
                }
            })
            
        except (LabGroup.DoesNotExist, ServiceTier.DoesNotExist, Instrument.DoesNotExist):
            return Response({
                'success': False,
                'error': 'Lab group, service tier, or instrument not found'
            }, status=404)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Failed to create service price: {str(e)}'
            }, status=500)


class BackupViewSet(ModelViewSet):
    """
    ViewSet for backup operations and status monitoring
    """
    queryset = BackupLog.objects.all()
    serializer_class = BackupLogSerializer
    permission_classes = [IsAdminUser]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['backup_type', 'status', 'triggered_by']
    ordering_fields = ['created_at', 'completed_at']
    ordering = ['-created_at']

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def trigger(self, request):
        """
        Trigger a manual backup
        """
        # Check if user has permission to trigger backups
        if not request.user.is_staff:
            return Response({
                'error': 'Only staff members can trigger backups'
            }, status=status.HTTP_403_FORBIDDEN)

        # Check if backup module is enabled
        try:
            settings_obj = SiteSettings.get_or_create_default()
            if not getattr(settings_obj, 'enable_backup_module', True):
                return Response({
                    'error': 'Backup module is disabled'
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'error': f'Failed to check backup settings: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Check if there's already a backup in progress
        active_backup = BackupLog.objects.filter(
            status__in=['created', 'in_progress']
        ).first()
        
        if active_backup:
            return Response({
                'error': 'A backup is already in progress',
                'active_backup_id': active_backup.id
            }, status=status.HTTP_409_CONFLICT)

        try:
            triggered_by = request.data.get('triggered_by', 'manual')
            
            # Start the backup using the auto_backup command with --force
            from django.core.management import call_command
            from io import StringIO
            import threading
            
            # Create a backup log entry
            backup_log = BackupLog.objects.create(
                backup_type='database',
                triggered_by=triggered_by,
                status='created'
            )
            
            def run_backup():
                try:
                    backup_log.status = 'in_progress'
                    backup_log.save()
                    
                    # Call the auto_backup command with force flag and user info
                    output = StringIO()
                    call_command('auto_backup', '--force', 
                               '--user-id', str(request.user.id),
                               '--backup-id', str(backup_log.id),
                               stdout=output)
                    
                    # The auto_backup command will create its own backup logs
                    # We can delete this temporary one
                    backup_log.delete()
                    
                except Exception as e:
                    backup_log.mark_failed(f'Manual backup failed: {str(e)}')
            
            # Run backup in a separate thread
            backup_thread = threading.Thread(target=run_backup)
            backup_thread.daemon = True
            backup_thread.start()
            
            return Response({
                'success': True,
                'message': 'Backup started successfully',
                'backup_id': backup_log.id
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                'error': f'Failed to start backup: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def status(self, request):
        """
        Get current backup status
        """
        if not request.user.is_staff:
            return Response({
                'error': 'Only staff members can view backup status'
            }, status=status.HTTP_403_FORBIDDEN)

        try:
            # Get the most recent backup
            recent_backup = BackupLog.objects.order_by('-created_at').first()
            
            if not recent_backup:
                return Response({
                    'status': 'idle',
                    'message': 'No backups found',
                    'details': 'No backup history available'
                })
            
            # Check for active backups
            active_backup = BackupLog.objects.filter(
                status__in=['created', 'in_progress']
            ).order_by('-created_at').first()
            
            if active_backup:
                # Calculate progress based on time elapsed
                elapsed = (timezone.now() - active_backup.created_at).total_seconds()
                # Estimate 2-5 minutes for a typical backup
                estimated_duration = 300  # 5 minutes
                progress = min(int((elapsed / estimated_duration) * 100), 95)
                
                return Response({
                    'status': 'in_progress',
                    'message': 'Backup in progress',
                    'details': f'Started {int(elapsed // 60)} minutes ago',
                    'progress': progress,
                    'backup_id': active_backup.id
                })
            
            # Return status of most recent backup
            if recent_backup.status == 'completed':
                time_ago = timezone.now() - recent_backup.completed_at
                if time_ago.days > 0:
                    time_str = f'{time_ago.days} days ago'
                elif time_ago.seconds > 3600:
                    time_str = f'{time_ago.seconds // 3600} hours ago'
                else:
                    time_str = f'{time_ago.seconds // 60} minutes ago'
                
                return Response({
                    'status': 'completed',
                    'message': f'Last backup completed {time_str}',
                    'details': f'Size: {recent_backup.file_size_mb:.1f} MB' if recent_backup.file_size_mb else 'Size unknown'
                })
            elif recent_backup.status == 'failed':
                return Response({
                    'status': 'failed',
                    'message': 'Last backup failed',
                    'details': recent_backup.error_message[:100] if recent_backup.error_message else 'Unknown error'
                })
            else:
                return Response({
                    'status': 'idle',
                    'message': 'Ready for backup',
                    'details': 'No recent backup activity'
                })
                
        except Exception as e:
            return Response({
                'status': 'error',
                'message': 'Failed to get backup status',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def history(self, request):
        """
        Get backup history
        """
        if not request.user.is_staff:
            return Response({
                'error': 'Only staff members can view backup history'
            }, status=status.HTTP_403_FORBIDDEN)

        try:
            days = int(request.query_params.get('days', 30))
            limit = int(request.query_params.get('limit', 50))
            
            start_date = timezone.now() - timedelta(days=days)
            backups = BackupLog.objects.filter(
                created_at__gte=start_date
            ).order_by('-created_at')[:limit]
            
            backup_history = []
            for backup in backups:
                backup_data = {
                    'id': backup.id,
                    'backup_type': backup.backup_type,
                    'status': backup.status,
                    'triggered_by': backup.triggered_by,
                    'created_at': backup.created_at,
                    'completed_at': backup.completed_at,
                    'file_size_mb': backup.file_size_mb,
                    'error_message': backup.error_message
                }
                
                if backup.completed_at and backup.created_at:
                    duration = (backup.completed_at - backup.created_at).total_seconds()
                    backup_data['duration_seconds'] = int(duration)
                
                backup_history.append(backup_data)
            
            return Response({
                'backups': backup_history,
                'total_count': BackupLog.objects.filter(created_at__gte=start_date).count(),
                'period_days': days
            })
            
        except Exception as e:
            return Response({
                'error': f'Failed to get backup history: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def progress(self, request, pk=None):
        """
        Get progress of a specific backup
        """
        if not request.user.is_staff:
            return Response({
                'error': 'Only staff members can view backup progress'
            }, status=status.HTTP_403_FORBIDDEN)

        try:
            backup = self.get_object()
            
            if backup.status == 'completed':
                return Response({
                    'status': 'completed',
                    'message': 'Backup completed successfully',
                    'progress': 100,
                    'file_size_mb': backup.file_size_mb
                })
            elif backup.status == 'failed':
                return Response({
                    'status': 'failed',
                    'message': 'Backup failed',
                    'progress': 0,
                    'error': backup.error_message
                })
            elif backup.status in ['created', 'in_progress']:
                # Calculate estimated progress
                elapsed = (timezone.now() - backup.created_at).total_seconds()
                estimated_duration = 300  # 5 minutes
                progress = min(int((elapsed / estimated_duration) * 100), 95)
                
                return Response({
                    'status': 'in_progress',
                    'message': 'Backup in progress',
                    'progress': progress,
                    'elapsed_seconds': int(elapsed)
                })
            else:
                return Response({
                    'status': backup.status,
                    'message': f'Backup status: {backup.status}',
                    'progress': 0
                })
                
        except Exception as e:
            return Response({
                'error': f'Failed to get backup progress: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SamplePoolViewSet(ModelViewSet):
    """ViewSet for managing sample pools"""
    serializer_class = SamplePoolSerializer
    queryset = SamplePool.objects.all()
    permission_classes = [IsAuthenticated]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    
    def get_queryset(self):
        """Get pools for a specific instrument job"""
        instrument_job_id = self.kwargs.get('instrument_job_id')
        if instrument_job_id:
            return SamplePool.objects.filter(instrument_job_id=instrument_job_id)
        return SamplePool.objects.all()
    
    def _check_instrument_job_permissions(self, instrument_job, user, action='read'):
        """
        Check if user has permission to perform action on instrument job
        Returns (has_permission, is_staff_user)
        """
        # System admin always has access
        if user.is_staff:
            return True, True
        
        # Job owner has read access only
        if instrument_job.user == user:
            return action == 'read', False
        
        # Check staff assignment
        staff_users = instrument_job.staff.all()
        if staff_users.count() > 0:
            if user in staff_users:
                return True, True
        else:
            # No specific staff assigned, check service lab group
            if instrument_job.service_lab_group:
                service_staff = instrument_job.service_lab_group.users.all()
                if user in service_staff:
                    return True, True
        
        return False, False
    
    def perform_create(self, serializer):
        """Create a new sample pool"""
        instrument_job_id = self.kwargs.get('instrument_job_id')
        instrument_job = get_object_or_404(InstrumentJob, id=instrument_job_id)
        
        # Check if user has permission to create pools (write access + staff role)
        has_permission, is_staff_user = self._check_instrument_job_permissions(
            instrument_job, self.request.user, 'write'
        )
        if not has_permission or not is_staff_user:
            raise PermissionDenied("Only staff members can create pools")
        
        # Validate pool name is unique for this instrument job
        pool_name = serializer.validated_data.get('pool_name')
        if SamplePool.objects.filter(instrument_job=instrument_job, pool_name=pool_name).exists():
            raise ValidationError(
                f"A pool with name '{pool_name}' already exists for this instrument job"
            )
        
        # Validate sample indices are within range
        pooled_only = serializer.validated_data.get('pooled_only_samples', [])
        pooled_and_independent = serializer.validated_data.get('pooled_and_independent_samples', [])
        all_samples = set(pooled_only + pooled_and_independent)
        
        if all_samples:
            max_sample = max(all_samples)
            if max_sample > instrument_job.sample_number:
                raise ValidationError(
                    f"Sample index {max_sample} is invalid. "
                    f"Instrument job has only {instrument_job.sample_number} samples"
                )
        
        # Save the pool
        sample_pool = serializer.save(
            instrument_job=instrument_job,
            created_by=self.request.user
        )
        
        return sample_pool
    
    def perform_update(self, serializer):
        """Update an existing sample pool"""
        instance = serializer.instance
        
        # Check permissions (write access + staff role)
        has_permission, is_staff_user = self._check_instrument_job_permissions(
            instance.instrument_job, self.request.user, 'write'
        )
        if not has_permission or not is_staff_user:
            raise PermissionDenied("Only staff members can update pools")
        
        # Validate sample indices are within range
        pooled_only = serializer.validated_data.get('pooled_only_samples', [])
        pooled_and_independent = serializer.validated_data.get('pooled_and_independent_samples', [])
        all_samples = set(pooled_only + pooled_and_independent)
        
        if all_samples:
            max_sample = max(all_samples)
            if max_sample > instance.instrument_job.sample_number:
                raise ValidationError(
                    f"Sample index {max_sample} is invalid. "
                    f"Instrument job has only {instance.instrument_job.sample_number} samples"
                )
        
        # Save the updated pool
        sample_pool = serializer.save()
        
        return sample_pool
    
    def perform_destroy(self, instance):
        """Delete a sample pool"""
        # Check permissions (write access + staff role)
        has_permission, is_staff_user = self._check_instrument_job_permissions(
            instance.instrument_job, self.request.user, 'write'
        )
        if not has_permission or not is_staff_user:
            raise PermissionDenied("Only staff members can delete pools")
        
        instrument_job = instance.instrument_job
        
        # Store the samples that were in this pool for metadata update
        affected_samples = set(instance.pooled_only_samples + instance.pooled_and_independent_samples)
        
        # Delete the pool
        instance.delete()
        
        # Update pooled sample metadata for the instrument job after deletion
        # This will recalculate the pooled sample values for all samples
        # Call the method from InstrumentJobViewSets
        instrument_job_viewset = InstrumentJobViewSets()
        instrument_job_viewset._update_pooled_sample_metadata_after_pool_deletion(instrument_job, affected_samples)
    
    @action(detail=False, methods=['get'])
    def sample_status_overview(self, request, instrument_job_id=None):
        """Get overview of sample pooling status for all samples"""
        instrument_job = get_object_or_404(InstrumentJob, id=instrument_job_id)
        
        # Check permissions (read access allowed)
        has_permission, _ = self._check_instrument_job_permissions(
            instrument_job, request.user, 'read'
        )
        if not has_permission:
            raise PermissionDenied("You don't have permission to view sample status")
        
        pools = SamplePool.objects.filter(instrument_job=instrument_job)
        
        # Get source names for all samples
        source_names = self._get_source_names_for_samples(instrument_job)
        
        overview = []
        for i in range(1, instrument_job.sample_number + 1):
            sample_pools = []
            status = "Independent"
            sdrf_value = "not pooled"
            
            for pool in pools:
                if i in pool.pooled_only_samples:
                    sample_pools.append(pool.pool_name)
                    status = "Pooled Only"
                    sdrf_value = pool.sdrf_value
                elif i in pool.pooled_and_independent_samples:
                    sample_pools.append(pool.pool_name)
                    if status == "Independent":
                        status = "Mixed"
                    # For independent samples, SDRF value remains "not pooled"
            
            # Get source name or fallback to sample index
            source_name = source_names.get(i, f'Sample {i}')
            
            overview.append({
                'sample_index': i,
                'sample_name': source_name,
                'status': status,
                'pool_names': sample_pools,
                'sdrf_value': sdrf_value
            })
        
        return Response(overview)
    
    @action(detail=True, methods=['post'])
    def add_sample(self, request, pk=None, instrument_job_id=None):
        """Add a sample to the pool"""
        pool = self.get_object()
        sample_index = request.data.get('sample_index')
        sample_status = request.data.get('status', 'pooled_only')
        
        # Check permissions (write access + staff role)
        has_permission, is_staff_user = self._check_instrument_job_permissions(
            pool.instrument_job, request.user, 'write'
        )
        if not has_permission or not is_staff_user:
            raise PermissionDenied("Only staff members can modify pools")
        
        # Validate sample index
        if not isinstance(sample_index, int) or sample_index < 1:
            raise ValidationError("Sample index must be a positive integer")
        
        if sample_index > pool.instrument_job.sample_number:
            raise ValidationError(
                f"Sample index {sample_index} is invalid. "
                f"Instrument job has only {pool.instrument_job.sample_number} samples"
            )
        
        # Add the sample
        pool.add_sample(sample_index, sample_status)
        pool.save()
        
        return Response({
            'message': f'Sample {sample_index} added to pool as {sample_status}',
            'pool': SamplePoolSerializer(pool).data
        })
    
    @action(detail=True, methods=['post'])
    def remove_sample(self, request, pk=None, instrument_job_id=None):
        """Remove a sample from the pool"""
        pool = self.get_object()
        sample_index = request.data.get('sample_index')
        
        # Check permissions (write access + staff role)
        has_permission, is_staff_user = self._check_instrument_job_permissions(
            pool.instrument_job, request.user, 'write'
        )
        if not has_permission or not is_staff_user:
            raise PermissionDenied("Only staff members can modify pools")
        
        # Validate sample index
        if not isinstance(sample_index, int) or sample_index < 1:
            raise ValidationError("Sample index must be a positive integer")
        
        # Remove the sample
        pool.remove_sample(sample_index)
        pool.save()
        
        return Response({
            'message': f'Sample {sample_index} removed from pool',
            'pool': SamplePoolSerializer(pool).data
        })

    def _get_source_names_for_samples(self, instrument_job):
        """Get source names for all samples from metadata"""
        
        # Get the Source name metadata column
        source_name_column = None
        for metadata_column in list(instrument_job.user_metadata.all()) + list(instrument_job.staff_metadata.all()):
            if metadata_column.name == "Source name":
                source_name_column = metadata_column
                break
        
        if not source_name_column:
            # No source name metadata found, return empty dict to use fallback
            return {}
        
        source_names = {}
        
        # Set default value for all samples
        if source_name_column.value:
            for i in range(1, instrument_job.sample_number + 1):
                source_names[i] = source_name_column.value
        
        # Override with modifier values if they exist
        if source_name_column.modifiers:
            try:
                modifiers = json.loads(source_name_column.modifiers) if isinstance(source_name_column.modifiers, str) else source_name_column.modifiers
                for modifier in modifiers:
                    samples_str = modifier.get("samples", "")
                    value = modifier.get("value", "")
                    
                    # Parse sample indices from the modifier string
                    sample_indices = self._parse_sample_indices_from_modifier_string(samples_str)
                    for sample_index in sample_indices:
                        if 1 <= sample_index <= instrument_job.sample_number:
                            source_names[sample_index] = value
            except (json.JSONDecodeError, ValueError):
                pass
        
        return source_names
    
    def _parse_sample_indices_from_modifier_string(self, samples_str):
        """Parse sample indices from modifier string like '1,2,3' or '1-3,5'"""
        indices = []
        if not samples_str:
            return indices
            
        parts = samples_str.split(",")
        for part in parts:
            part = part.strip()
            if "-" in part:
                # Handle range like "1-3"
                try:
                    start, end = part.split("-", 1)
                    start_idx = int(start.strip())
                    end_idx = int(end.strip())
                    indices.extend(range(start_idx, end_idx + 1))
                except ValueError:
                    pass
            else:
                # Handle single number
                try:
                    indices.append(int(part))
                except ValueError:
                    pass
        
        return indices

    @action(detail=True, methods=['patch'])
    def update_metadata(self, request, pk=None):
        """Update a specific metadata column for this pool"""
        pool = self.get_object()
        
        # Check permissions via the parent instrument job
        has_permission, is_staff_user = self._check_instrument_job_permissions(
            pool.instrument_job, request.user, 'write'
        )
        
        if not has_permission:
            return Response(
                {'error': 'You do not have permission to update metadata for this pool'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get the metadata column data from request
        metadata_column_id = request.data.get('metadata_column_id')
        new_value = request.data.get('value', '')
        
        if not metadata_column_id:
            return Response(
                {'error': 'metadata_column_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Find the metadata column in the pool's metadata
            metadata_column = None
            
            # Check user metadata first
            if pool.user_metadata.filter(id=metadata_column_id).exists():
                metadata_column = pool.user_metadata.get(id=metadata_column_id)
            # Then check staff metadata
            elif pool.staff_metadata.filter(id=metadata_column_id).exists():
                metadata_column = pool.staff_metadata.get(id=metadata_column_id)
            
            if not metadata_column:
                return Response(
                    {'error': 'Metadata column not found in this pool'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Update the metadata column value
            metadata_column.value = new_value
            metadata_column.save()
            
            # Special handling for pool name updates
            if metadata_column.name.lower() in ['source name', 'source_name']:
                pool.pool_name = new_value
                pool.save()
            
            return Response({
                'success': True,
                'metadata_column_id': metadata_column.id,
                'new_value': new_value,
                'message': f'Pool metadata updated: {metadata_column.name}'
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {'error': f'Failed to update metadata: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RemoteHostViewSet(ModelViewSet):
    """ViewSet for managing RemoteHost instances for distributed sync"""
    
    queryset = RemoteHost.objects.all()
    serializer_class = RemoteHostSerializer
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['host_name', 'host_description']
    ordering_fields = ['host_name', 'created_at', 'updated_at']
    filterset_fields = ['host_protocol']
    
    def get_queryset(self):
        """Filter RemoteHost instances - for now, show all to authenticated users"""
        queryset = RemoteHost.objects.all()
        
        # Add any additional filtering logic here if needed
        # For example, could restrict based on user permissions in the future
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['post'], url_path='test-connection')
    def test_connection(self, request, pk=None):
        """Test connection to a remote host"""
        remote_host = self.get_object()
        
        from cc.utils.sync_auth import SyncAuthenticator
        
        try:
            with SyncAuthenticator(remote_host) as auth:
                result = auth.test_connection()
                
                if result['success']:
                    return Response({
                        'success': True,
                        'status': 'connected',
                        'message': result['message'],
                        'response_time': result.get('response_time'),
                        'host_name': result['host_name'],
                        'url': result.get('url')
                    }, status=status.HTTP_200_OK)
                else:
                    error_code = result.get('error', 'unknown_error')
                    if error_code == 'timeout':
                        status_code = status.HTTP_408_REQUEST_TIMEOUT
                    elif error_code == 'connection_error':
                        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                    else:
                        status_code = status.HTTP_400_BAD_REQUEST
                    
                    return Response({
                        'success': False,
                        'status': error_code,
                        'message': result['message'],
                        'details': result.get('details'),
                        'host_name': result['host_name']
                    }, status=status_code)
                
        except Exception as e:
            return Response({
                'success': False,
                'status': 'error',
                'message': 'Unexpected error during connection test',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'], url_path='test-authentication')
    def test_authentication(self, request, pk=None):
        """Test authentication with a remote host"""
        remote_host = self.get_object()
        
        from cc.utils.sync_auth import test_remote_host_auth
        
        try:
            # Run comprehensive authentication test
            results = test_remote_host_auth(remote_host)
            
            if results['success']:
                return Response({
                    'success': True,
                    'message': f'Full authentication test passed for {remote_host.host_name}',
                    'results': results
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': f'Authentication test failed for {remote_host.host_name}',
                    'results': results
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                'success': False,
                'message': 'Unexpected error during authentication test',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['get'], url_path='sync-status')
    def sync_status(self, request, pk=None):
        """Get sync status for a remote host"""
        remote_host = self.get_object()
        
        from cc.services.sync_service import SyncService
        
        try:
            with SyncService(remote_host, request.user) as sync_service:
                status_result = sync_service.get_sync_status()
                
                if status_result['success']:
                    return Response({
                        'success': True,
                        'remote_host_id': remote_host.id,
                        'remote_host_name': remote_host.host_name,
                        'sync_status': status_result['status']
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        'success': False,
                        'error': status_result['error']
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'], url_path='sync-pull')
    def sync_pull(self, request, pk=None):
        """Pull data from a remote host"""
        remote_host = self.get_object()
        
        from cc.services.sync_service import SyncService, SyncError
        from cc.utils.sync_auth import SyncAuthError
        
        # Get parameters from request
        models_to_sync = request.data.get('models', None)
        limit_per_model = request.data.get('limit', None)
        
        try:
            with SyncService(remote_host, request.user) as sync_service:
                # Perform the sync
                results = sync_service.pull_all_data(
                    models=models_to_sync,
                    limit_per_model=limit_per_model
                )
                
                if results['success']:
                    return Response({
                        'success': True,
                        'message': f'Successfully synced data from {remote_host.host_name}',
                        'results': results
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        'success': False,
                        'message': f'Sync completed with errors from {remote_host.host_name}',
                        'results': results
                    }, status=status.HTTP_207_MULTI_STATUS)  # Partial success
                    
        except SyncAuthError as e:
            return Response({
                'success': False,
                'error': 'authentication_failed',
                'message': f'Authentication failed: {str(e)}'
            }, status=status.HTTP_401_UNAUTHORIZED)
            
        except SyncError as e:
            return Response({
                'success': False,
                'error': 'sync_failed',
                'message': f'Sync failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': 'unexpected_error',
                'message': f'Unexpected error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'], url_path='sync-push')
    def sync_push(self, request, pk=None):
        """Push local data to a remote host"""
        remote_host = self.get_object()
        
        from cc.services.sync_service import SyncService, SyncError
        from cc.utils.sync_auth import SyncAuthError
        from datetime import datetime, timezone
        
        # Get parameters from request
        models_to_sync = request.data.get('models', None)
        limit_per_model = request.data.get('limit', None)
        conflict_strategy = request.data.get('conflict_strategy', 'timestamp')
        modified_since_str = request.data.get('modified_since', None)
        
        # Parse modified_since if provided
        modified_since = None
        if modified_since_str:
            try:
                modified_since = datetime.fromisoformat(modified_since_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'error': 'invalid_date_format',
                    'message': 'modified_since must be in ISO format (YYYY-MM-DDTHH:MM:SS[Z])'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate conflict strategy
        valid_strategies = ['timestamp', 'force_push', 'skip']
        if conflict_strategy not in valid_strategies:
            return Response({
                'success': False,
                'error': 'invalid_conflict_strategy',
                'message': f'conflict_strategy must be one of: {", ".join(valid_strategies)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with SyncService(remote_host, request.user) as sync_service:
                # Perform the push
                results = sync_service.push_local_changes(
                    models=models_to_sync,
                    modified_since=modified_since,
                    conflict_strategy=conflict_strategy,
                    limit_per_model=limit_per_model
                )
                
                if results['success']:
                    response_status = status.HTTP_200_OK
                    if results['summary']['total_conflicts'] > 0:
                        response_status = status.HTTP_207_MULTI_STATUS  # Partial success with conflicts
                        
                    return Response({
                        'success': True,
                        'message': f'Successfully pushed data to {remote_host.host_name}',
                        'results': results
                    }, status=response_status)
                else:
                    return Response({
                        'success': False,
                        'message': f'Push completed with errors to {remote_host.host_name}',
                        'results': results
                    }, status=status.HTTP_207_MULTI_STATUS)  # Partial success
                    
        except SyncAuthError as e:
            return Response({
                'success': False,
                'error': 'authentication_failed',
                'message': f'Authentication failed: {str(e)}'
            }, status=status.HTTP_401_UNAUTHORIZED)
            
        except SyncError as e:
            return Response({
                'success': False,
                'error': 'sync_failed',
                'message': f'Push failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': 'unexpected_error',
                'message': f'Unexpected error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='connection-summary')
    def connection_summary(self, request):
        """Get a summary of connection status for all remote hosts"""
        remote_hosts = self.get_queryset()
        
        summary = {
            'total_hosts': remote_hosts.count(),
            'hosts': []
        }
        
        for host in remote_hosts:
            host_info = {
                'id': host.id,
                'name': host.host_name,
                'url': f"{host.host_protocol}://{host.host_name}:{host.host_port}",
                'description': host.host_description,
                'created_at': host.created_at,
                'last_connection_test': None,  # TODO: Track this in Phase 2
                'status': 'unknown'  # TODO: Implement status tracking
            }
            summary['hosts'].append(host_info)
        
        return Response(summary, status=status.HTTP_200_OK)
