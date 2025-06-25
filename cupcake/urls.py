"""
URL configuration for cupcake project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from cc.views import GetProtocolIO, DataChunkedUploadView, set_csrf
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework import routers

from cc.viewsets import ProtocolViewSet, SessionViewSet, StepViewSet, AnnotationViewSet, VariationViewSet, \
    TimeKeeperViewSet, ProtocolSectionViewSet, UserViewSet, ReagentViewSet, ProtocolTagViewSet, StepTagViewSet, \
    TagViewSet, AnnotationFolderViewSet, ProjectViewSet, InstrumentViewSet, InstrumentUsageViewSet, \
    StorageObjectViewSet, StoredReagentViewSet, ReagentActionViewSet, LabGroupViewSet, SpeciesViewSet, \
    MetadataColumnViewSet, TissueViewSet, SubcellularLocationViewSet, HumanDiseaseViewSet, MSUniqueVocabulariesViewSet, \
    UnimodViewSets, InstrumentJobViewSets, FavouriteMetadataOptionViewSets, PresetViewSet, \
    MetadataTableTemplateViewSets, SupportInformationViewSet, ExternalContactViewSet, ExternalContactDetailsViewSet, \
    MaintenanceLogViewSet, MessageThreadViewSet, MessageViewSet, MessageRecipientViewSet, MessageAttachmentViewSet, \
    ReagentDocumentViewSet, SiteSettingsViewSet

router = routers.DefaultRouter()
router.register(r'protocol', ProtocolViewSet)
router.register(r'session', SessionViewSet)
router.register(r'step', StepViewSet)
router.register(r'annotation', AnnotationViewSet)
router.register(r'variation', VariationViewSet)
router.register(r'timekeeper', TimeKeeperViewSet)
router.register(r'section', ProtocolSectionViewSet)
router.register(r'user', UserViewSet)
router.register(r'reagent', ReagentViewSet)
router.register(r'protocol_tag', ProtocolTagViewSet)
router.register(r'step_tag', StepTagViewSet)
router.register(r'tag', TagViewSet)
router.register(r'folder', AnnotationFolderViewSet)
router.register(r'project', ProjectViewSet)
router.register(r'instrument', InstrumentViewSet)
router.register(r'instrument_usage', InstrumentUsageViewSet)
router.register(r'storage_object', StorageObjectViewSet)
router.register(r'stored_reagent', StoredReagentViewSet)
router.register(r'reagent_action', ReagentActionViewSet)
router.register(r'lab_groups', LabGroupViewSet)
router.register(r'species', SpeciesViewSet)
router.register(r'metadata_columns', MetadataColumnViewSet)
router.register(r'tissues', TissueViewSet)
router.register(r'subcellular_locations', SubcellularLocationViewSet)
router.register(r'human_diseases', HumanDiseaseViewSet)
router.register(r"ms_vocab", MSUniqueVocabulariesViewSet)
router.register(r"unimod", UnimodViewSets)
router.register('instrument_jobs', InstrumentJobViewSets)
router.register(r'favourite_metadata_option', FavouriteMetadataOptionViewSets)
router.register(r'preset', PresetViewSet)
router.register(r'metadata_table_templates', MetadataTableTemplateViewSets)
router.register(r'support_information', SupportInformationViewSet)
router.register(r'external-contacts', ExternalContactViewSet)
router.register(r'contact-details', ExternalContactDetailsViewSet)
router.register(r'maintenance_logs', MaintenanceLogViewSet)
router.register(r'message_threads', MessageThreadViewSet)
router.register(r'messages', MessageViewSet)
router.register(r'message_recipients', MessageRecipientViewSet)
router.register(r'message_attachments', MessageAttachmentViewSet)
router.register(r'reagent_documents', ReagentDocumentViewSet, basename="reagent_documents")
router.register(r'site_settings', SiteSettingsViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/get-protocol/', GetProtocolIO.as_view(), name="get-protocol"),
    path('api/token-auth/', obtain_auth_token),
    path('api/chunked_upload/', DataChunkedUploadView.as_view(), name='chunked_upload'),
    path('api/chunked_upload/<uuid:pk>/', DataChunkedUploadView.as_view(), name='chunkedupload-detail'),
    path("api/set-csrf/", set_csrf, name="set_csrf"),
]
