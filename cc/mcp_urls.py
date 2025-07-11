"""
URL patterns for MCP SDRF functionality.
"""

from django.urls import path
from . import mcp_views

app_name = 'mcp'

urlpatterns = [
    # Django class-based views (no authentication required)
    path('analyze-step/', mcp_views.AnalyzeProtocolStepView.as_view(), name='analyze_step'),
    path('match-terms/', mcp_views.MatchOntologyTermsView.as_view(), name='match_terms'),
    path('generate-metadata/', mcp_views.GenerateSDRFMetadataView.as_view(), name='generate_metadata'),
    path('validate-compliance/', mcp_views.ValidateSDRFComplianceView.as_view(), name='validate_compliance'),
    path('export-sdrf/', mcp_views.ExportSDRFFileView.as_view(), name='export_sdrf'),
    path('analyze-protocol/', mcp_views.AnalyzeFullProtocolView.as_view(), name='analyze_protocol'),
    
    # DRF API views (authentication required)
    path('api/analyze-step/', mcp_views.analyze_protocol_step_api, name='api_analyze_step'),
    path('api/generate-metadata/', mcp_views.generate_sdrf_metadata_api, name='api_generate_metadata'),
]