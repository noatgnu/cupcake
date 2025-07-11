"""
Serializers for MCP SDRF functionality.

These serializers handle request/response data for the MCP API endpoints.
"""

from rest_framework import serializers
from .models import ProtocolStep, ProtocolModel, MetadataColumn


class AnalyzeStepRequestSerializer(serializers.Serializer):
    """Serializer for protocol step analysis requests."""
    step_id = serializers.IntegerField(help_text="Protocol step ID to analyze")
    use_anthropic = serializers.BooleanField(
        default=False,
        help_text="Use Anthropic Claude for enhanced analysis"
    )
    anthropic_api_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Anthropic API key (optional if set in environment)"
    )


class MatchTermsRequestSerializer(serializers.Serializer):
    """Serializer for ontology term matching requests."""
    terms = serializers.ListField(
        child=serializers.CharField(max_length=200),
        help_text="List of terms to match against ontologies"
    )
    ontology_types = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        help_text="Optional list of ontology types to search"
    )
    min_confidence = serializers.FloatField(
        default=0.5,
        min_value=0.0,
        max_value=1.0,
        help_text="Minimum confidence threshold for matches"
    )


class GenerateMetadataRequestSerializer(serializers.Serializer):
    """Serializer for SDRF metadata generation requests."""
    step_id = serializers.IntegerField(help_text="Protocol step ID")
    auto_create = serializers.BooleanField(
        default=False,
        help_text="Whether to automatically create MetadataColumn objects"
    )


class ValidateComplianceRequestSerializer(serializers.Serializer):
    """Serializer for SDRF compliance validation requests."""
    step_id = serializers.IntegerField(help_text="Protocol step ID to validate")


class ExportSDRFRequestSerializer(serializers.Serializer):
    """Serializer for SDRF file export requests."""
    protocol_id = serializers.IntegerField(help_text="Protocol ID to export")


class AnalyzeProtocolRequestSerializer(serializers.Serializer):
    """Serializer for full protocol analysis requests."""
    protocol_id = serializers.IntegerField(help_text="Protocol ID to analyze")
    use_anthropic = serializers.BooleanField(
        default=False,
        help_text="Use Anthropic Claude for enhanced analysis"
    )
    anthropic_api_key = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Anthropic API key (optional if set in environment)"
    )


class ExtractedTermSerializer(serializers.Serializer):
    """Serializer for extracted terms."""
    text = serializers.CharField()
    term_type = serializers.CharField()
    context = serializers.CharField()
    confidence = serializers.FloatField()
    start_pos = serializers.IntegerField()
    end_pos = serializers.IntegerField()


class OntologyMatchSerializer(serializers.Serializer):
    """Serializer for ontology matches."""
    ontology_type = serializers.CharField()
    ontology_id = serializers.CharField()
    ontology_name = serializers.CharField()
    accession = serializers.CharField()
    confidence = serializers.FloatField()
    match_type = serializers.CharField()
    extracted_term = serializers.CharField()


class SDRFSuggestionSerializer(serializers.Serializer):
    """Serializer for SDRF suggestions."""
    ontology_type = serializers.CharField()
    ontology_id = serializers.CharField()
    ontology_name = serializers.CharField()
    accession = serializers.CharField()
    confidence = serializers.FloatField()
    extracted_term = serializers.CharField()


class MetadataSpecificationSerializer(serializers.Serializer):
    """Serializer for metadata column specifications."""
    name = serializers.CharField()
    type = serializers.CharField()
    column_position = serializers.IntegerField()
    value = serializers.CharField()
    mandatory = serializers.BooleanField()
    auto_generated = serializers.BooleanField()
    readonly = serializers.BooleanField()
    hidden = serializers.BooleanField()
    ontology_info = serializers.DictField(required=False)


class AnalysisMetadataSerializer(serializers.Serializer):
    """Serializer for analysis metadata."""
    total_terms_extracted = serializers.IntegerField()
    total_ontology_matches = serializers.IntegerField()
    high_confidence_matches = serializers.IntegerField()


class AnalyzeStepResponseSerializer(serializers.Serializer):
    """Serializer for protocol step analysis responses."""
    success = serializers.BooleanField()
    step_id = serializers.IntegerField()
    sdrf_suggestions = serializers.DictField(required=False)
    analysis_summary = serializers.DictField(required=False)
    detailed_analysis = serializers.DictField(required=False)
    claude_analysis = serializers.DictField(required=False)
    biological_insights = serializers.DictField(required=False)
    analyzer_type = serializers.CharField(required=False)
    error = serializers.CharField(required=False)


class MatchTermsResponseSerializer(serializers.Serializer):
    """Serializer for term matching responses."""
    success = serializers.BooleanField()
    total_terms = serializers.IntegerField()
    total_matches = serializers.IntegerField()
    matches = OntologyMatchSerializer(many=True, required=False)
    min_confidence = serializers.FloatField()
    error = serializers.CharField(required=False)


class GenerateMetadataResponseSerializer(serializers.Serializer):
    """Serializer for metadata generation responses."""
    success = serializers.BooleanField()
    step_id = serializers.IntegerField()
    metadata_specifications = MetadataSpecificationSerializer(many=True, required=False)
    created_columns = serializers.IntegerField(required=False)
    auto_created = serializers.BooleanField(required=False)
    column_details = serializers.ListField(required=False)
    analysis_summary = serializers.DictField(required=False)
    error = serializers.CharField(required=False)


class ValidationResultSerializer(serializers.Serializer):
    """Serializer for SDRF validation results."""
    is_compliant = serializers.BooleanField()
    missing_required_columns = serializers.ListField(child=serializers.CharField())
    invalid_column_types = serializers.ListField(child=serializers.DictField())
    warnings = serializers.ListField(child=serializers.CharField())
    suggestions = serializers.ListField(child=serializers.CharField())


class ValidateComplianceResponseSerializer(serializers.Serializer):
    """Serializer for compliance validation responses."""
    success = serializers.BooleanField()
    step_id = serializers.IntegerField()
    protocol_id = serializers.IntegerField(required=False)
    validation_results = ValidationResultSerializer(required=False)
    total_columns = serializers.IntegerField(required=False)
    compliant = serializers.BooleanField(required=False)
    error = serializers.CharField(required=False)


class SDRFContentSerializer(serializers.Serializer):
    """Serializer for SDRF file content."""
    headers = serializers.ListField(child=serializers.CharField())
    data = serializers.ListField(child=serializers.ListField(child=serializers.CharField()))
    file_format = serializers.CharField()
    sdrf_version = serializers.CharField()


class ExportSDRFResponseSerializer(serializers.Serializer):
    """Serializer for SDRF export responses."""
    success = serializers.BooleanField()
    protocol_id = serializers.IntegerField()
    protocol_title = serializers.CharField(required=False)
    sdrf_content = SDRFContentSerializer(required=False)
    total_columns = serializers.IntegerField(required=False)
    export_timestamp = serializers.CharField(required=False)
    error = serializers.CharField(required=False)


class ProtocolSummarySerializer(serializers.Serializer):
    """Serializer for protocol-level summary."""
    organisms = serializers.ListField(child=serializers.CharField())
    tissues = serializers.ListField(child=serializers.CharField())
    instruments = serializers.ListField(child=serializers.CharField())
    diseases = serializers.ListField(child=serializers.CharField())
    modifications = serializers.ListField(child=serializers.CharField())
    chemicals = serializers.ListField(child=serializers.CharField())
    procedures = serializers.ListField(child=serializers.CharField())
    cellular_components = serializers.ListField(child=serializers.CharField())


class StepAnalysisSerializer(serializers.Serializer):
    """Serializer for individual step analysis."""
    step_id = serializers.IntegerField()
    step_description = serializers.CharField()
    step_duration = serializers.IntegerField(required=False, allow_null=True)
    section_name = serializers.CharField(required=False, allow_null=True)
    extracted_terms = ExtractedTermSerializer(many=True)
    term_summary = serializers.DictField()
    ontology_matches = OntologyMatchSerializer(many=True)
    categorized_matches = serializers.DictField()
    analysis_metadata = AnalysisMetadataSerializer()


class AnalyzeProtocolResponseSerializer(serializers.Serializer):
    """Serializer for full protocol analysis responses."""
    success = serializers.BooleanField()
    protocol_id = serializers.IntegerField()
    total_steps = serializers.IntegerField(required=False)
    step_analyses = StepAnalysisSerializer(many=True, required=False)
    protocol_summary = ProtocolSummarySerializer(required=False)
    protocol_sdrf_suggestions = serializers.DictField(required=False)
    step_sdrf_suggestions = serializers.DictField(required=False)
    error = serializers.CharField(required=False)


class MCPToolSerializer(serializers.Serializer):
    """Serializer for MCP tool information."""
    name = serializers.CharField()
    description = serializers.CharField()
    parameters = serializers.ListField(child=serializers.CharField())


class MCPServerInfoSerializer(serializers.Serializer):
    """Serializer for MCP server information."""
    name = serializers.CharField()
    version = serializers.CharField()
    description = serializers.CharField()
    tools = MCPToolSerializer(many=True)
    supported_ontologies = serializers.ListField(child=serializers.CharField())


# WebSocket message serializers
class WebSocketProgressSerializer(serializers.Serializer):
    """Serializer for WebSocket progress messages."""
    type = serializers.CharField()
    message = serializers.CharField()
    percentage = serializers.IntegerField(min_value=0, max_value=100)


class WebSocketErrorSerializer(serializers.Serializer):
    """Serializer for WebSocket error messages."""
    type = serializers.CharField()
    error = serializers.CharField()


class WebSocketResultSerializer(serializers.Serializer):
    """Serializer for WebSocket result messages."""
    type = serializers.CharField()
    data = serializers.DictField()