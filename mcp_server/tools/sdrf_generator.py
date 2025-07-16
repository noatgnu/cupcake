"""
SDRF metadata generation tool for MCP server.

This tool generates SDRF-compliant metadata columns based on
protocol step analysis and ontology term matching.
"""

from typing import Dict, List, Optional, Any, Tuple
import json
from datetime import datetime

from cc.models import MetadataColumn, ProtocolStep
from ..utils.django_setup import get_authenticated_user, validate_user_permissions


class SDRFMetadataGenerator:
    """
    Generates SDRF metadata columns from protocol analysis results.
    """
    
    def __init__(self):
        """Initialize the SDRF metadata generator."""
        self._setup_sdrf_mappings()
    
    def _setup_sdrf_mappings(self):
        """Setup mappings between ontology terms and SDRF format."""
        
        # SDRF column types and their metadata types
        self.sdrf_column_types = {
            'organism': 'Characteristics',
            'organism part': 'Characteristics', 
            'disease': 'Characteristics',
            'cell line': 'Characteristics',
            'subcellular localization': 'Characteristics',
            'instrument': 'Comment',
            'cleavage agent details': 'Comment',
            'dissociation method': 'Comment',
            'enrichment process': 'Comment',
            'fractionation method': 'Comment',
            'reduction reagent': 'Comment',
            'alkylation reagent': 'Comment',
            'mass analyzer type': 'Comment',
            'modification parameters': 'Comment'
        }
        
        # Default SDRF columns that should be present
        self.default_sdrf_columns = [
            ('Source name', 'Source name'),
            ('Assay name', 'Assay name'),
            ('Material type', 'Material type'),
            ('Technology type', 'Technology type')
        ]
    
    def generate_metadata_columns(self, step_id: int, sdrf_suggestions: Dict[str, List[Dict]], 
                                user_token: Optional[str] = None, 
                                auto_create: bool = False) -> Dict[str, Any]:
        """
        Generate MetadataColumn objects from SDRF suggestions.
        
        Args:
            step_id (int): Protocol step ID
            sdrf_suggestions (Dict): SDRF suggestions from protocol analysis
            user_token (str, optional): Authentication token
            auto_create (bool): Whether to automatically create MetadataColumn objects
            
        Returns:
            Dict containing generated metadata columns information
        """
        try:
            # Authenticate user if token provided
            user = None
            if user_token:
                user = get_authenticated_user(user_token)
                if not user:
                    return {
                        'success': False,
                        'error': 'Invalid authentication token'
                    }
            
            # Get the protocol step
            from cc.models import ProtocolStep
            try:
                step = ProtocolStep.objects.get(id=step_id)
            except ProtocolStep.DoesNotExist:
                return {
                    'success': False,
                    'error': f'Protocol step {step_id} not found'
                }
            
            # Check permissions
            if user and step.protocol:
                if not validate_user_permissions(user, step.protocol.id):
                    return {
                        'success': False,
                        'error': 'Access denied to this protocol'
                    }
            
            # Generate metadata column specifications
            metadata_specs = self._create_metadata_specifications(sdrf_suggestions, step)
            
            created_columns = []
            if auto_create and user:
                # Create actual MetadataColumn objects
                created_columns = self._create_metadata_columns(metadata_specs, step, user)
            
            return {
                'success': True,
                'step_id': step_id,
                'metadata_specifications': metadata_specs,
                'created_columns': len(created_columns) if auto_create else 0,
                'auto_created': auto_create,
                'column_details': [self._serialize_metadata_column(col) for col in created_columns] if auto_create else []
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Metadata generation failed: {str(e)}',
                'step_id': step_id
            }
    
    def _create_metadata_specifications(self, sdrf_suggestions: Dict[str, List[Dict]], 
                                      step) -> List[Dict[str, Any]]:
        """
        Create metadata column specifications from SDRF suggestions.
        
        Args:
            sdrf_suggestions: Dictionary of SDRF suggestions
            step: ProtocolStep instance
            
        Returns:
            List of metadata column specifications
        """
        specifications = []
        position = 0
        
        # Add default SDRF columns first
        for col_name, col_type in self.default_sdrf_columns:
            specifications.append({
                'name': col_name,
                'type': col_type,
                'column_position': position,
                'value': '',
                'mandatory': True,
                'auto_generated': False,
                'readonly': False,
                'hidden': False
            })
            position += 1
        
        # Add suggested columns based on analysis
        for sdrf_column, matches in sdrf_suggestions.items():
            if not matches:
                continue
            
            # Get the best match (highest confidence)
            best_match = max(matches, key=lambda x: x['confidence'])
            
            # Create SDRF-formatted value
            sdrf_value = self._format_sdrf_value(best_match, sdrf_column)
            
            # Determine metadata type
            metadata_type = self.sdrf_column_types.get(sdrf_column, 'Comment')
            
            specifications.append({
                'name': sdrf_column,
                'type': metadata_type,
                'column_position': position,
                'value': sdrf_value,
                'mandatory': False,
                'auto_generated': False,
                'readonly': False,
                'hidden': False,
                'ontology_info': {
                    'ontology_type': best_match['ontology_type'] if best_match else None,
                    'ontology_id': best_match['ontology_id'] if best_match else None,
                    'accession': best_match['accession'] if best_match else None,
                    'confidence': best_match['confidence'] if best_match else None,
                    'extracted_term': best_match['extracted_term'] if best_match else None
                }
            })
            position += 1
        
        return specifications
    
    def _format_sdrf_value(self, match: Dict, sdrf_column: str) -> str:
        """
        Format ontology match as SDRF-compliant value.
        
        Args:
            match: Ontology match dictionary
            sdrf_column: SDRF column name
            
        Returns:
            SDRF-formatted value string
        """
        if not match:
            return ''
        
        ontology_name = match.get('ontology_name', '')
        accession = match.get('accession', '')
        
        # Format according to SDRF standards (NT=name;AC=accession)
        if accession and ontology_name:
            return f"NT={ontology_name};AC={accession}"
        elif ontology_name:
            return ontology_name
        else:
            return ''
    
    def _create_metadata_columns(self, specifications: List[Dict], step, user) -> List:
        """
        Create actual MetadataColumn objects in the database.
        
        Args:
            specifications: List of metadata column specifications
            step: ProtocolStep instance
            user: User creating the columns
            
        Returns:
            List of created MetadataColumn objects
        """
        
        created_columns = []
        
        try:
            for spec in specifications:
                # Check if column already exists for this step
                existing = MetadataColumn.objects.filter(
                    name=spec['name'],
                    type=spec['type'],
                    protocol=step.protocol
                ).first()
                
                if existing:
                    # Update existing column
                    existing.value = spec['value']
                    existing.column_position = spec['column_position']
                    existing.auto_generated = spec['auto_generated']
                    existing.save()
                    created_columns.append(existing)
                else:
                    # Create new column
                    metadata_column = MetadataColumn.objects.create(
                        name=spec['name'],
                        type=spec['type'],
                        column_position=spec['column_position'],
                        value=spec['value'],
                        mandatory=spec['mandatory'],
                        auto_generated=spec['auto_generated'],
                        readonly=spec['readonly'],
                        hidden=spec['hidden'],
                        protocol=step.protocol
                    )
                    
                    # Add ontology information as modifiers if available
                    if 'ontology_info' in spec and spec['ontology_info']['ontology_id']:
                        modifiers = {
                            'ontology_type': spec['ontology_info']['ontology_type'],
                            'ontology_id': spec['ontology_info']['ontology_id'],
                            'accession': spec['ontology_info']['accession'],
                            'confidence': spec['ontology_info']['confidence'],
                            'extracted_term': spec['ontology_info']['extracted_term'],
                            'auto_generated_at': datetime.now().isoformat()
                        }
                        metadata_column.modifiers = json.dumps(modifiers)
                        metadata_column.save()
                    
                    created_columns.append(metadata_column)
        
        except Exception as e:
            # If any creation fails, we still return what was created
            print(f"Error creating metadata columns: {e}")
        
        return created_columns
    
    def _serialize_metadata_column(self, column) -> Dict[str, Any]:
        """
        Serialize a MetadataColumn object for API response.
        
        Args:
            column: MetadataColumn instance
            
        Returns:
            Dictionary representation of the column
        """
        modifiers = {}
        if column.modifiers:
            try:
                modifiers = json.loads(column.modifiers)
            except:
                pass
        
        return {
            'id': column.id,
            'name': column.name,
            'type': column.type,
            'column_position': column.column_position,
            'value': column.value,
            'mandatory': column.mandatory,
            'auto_generated': column.auto_generated,
            'readonly': column.readonly,
            'hidden': column.hidden,
            'created_at': column.created_at.isoformat() if column.created_at else None,
            'updated_at': column.updated_at.isoformat() if column.updated_at else None,
            'modifiers': modifiers
        }
    
    def validate_sdrf_compliance(self, step_id: int, user_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Validate SDRF compliance for existing metadata columns on a step.
        
        Args:
            step_id (int): Protocol step ID
            user_token (str, optional): Authentication token
            
        Returns:
            Dict containing validation results
        """
        try:
            # Authenticate user if token provided
            user = None
            if user_token:
                user = get_authenticated_user(user_token)

            try:
                step = ProtocolStep.objects.get(id=step_id)
            except ProtocolStep.DoesNotExist:
                return {
                    'success': False,
                    'error': f'Protocol step {step_id} not found'
                }
            
            # Check permissions
            if user and step.protocol:
                if not validate_user_permissions(user, step.protocol.id):
                    return {
                        'success': False,
                        'error': 'Access denied to this protocol'
                    }
            
            # Get existing metadata columns for the protocol
            existing_columns = MetadataColumn.objects.filter(protocol=step.protocol)
            
            # Validate SDRF compliance
            validation_results = self._validate_sdrf_structure(existing_columns)
            
            return {
                'success': True,
                'step_id': step_id,
                'protocol_id': step.protocol.id,
                'validation_results': validation_results,
                'total_columns': len(existing_columns),
                'compliant': validation_results['is_compliant']
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'SDRF validation failed: {str(e)}',
                'step_id': step_id
            }
    
    def _validate_sdrf_structure(self, columns) -> Dict[str, Any]:
        """
        Validate that metadata columns follow SDRF structure requirements.
        
        Args:
            columns: QuerySet of MetadataColumn objects
            
        Returns:
            Dict containing validation results
        """
        validation_results = {
            'is_compliant': True,
            'missing_required_columns': [],
            'invalid_column_types': [],
            'warnings': [],
            'suggestions': []
        }
        
        # Check for required SDRF columns
        required_columns = ['Source name', 'Assay name', 'Material type', 'Technology type']
        existing_column_names = {col.name for col in columns}
        
        for required in required_columns:
            if required not in existing_column_names:
                validation_results['missing_required_columns'].append(required)
                validation_results['is_compliant'] = False
        
        # Check column types
        for column in columns:
            if column.type not in ['Source name', 'Assay name', 'Material type', 'Technology type', 
                                 'Characteristics', 'Comment', 'Factor value']:
                validation_results['invalid_column_types'].append({
                    'column_name': column.name,
                    'current_type': column.type,
                    'suggested_type': self._suggest_column_type(column.name)
                })
        
        # Add suggestions for improvement
        if not validation_results['missing_required_columns'] and not validation_results['invalid_column_types']:
            validation_results['suggestions'].append("SDRF structure is compliant")
        else:
            if validation_results['missing_required_columns']:
                validation_results['suggestions'].append(
                    f"Add required columns: {', '.join(validation_results['missing_required_columns'])}"
                )
            if validation_results['invalid_column_types']:
                validation_results['suggestions'].append(
                    "Review column types for SDRF compliance"
                )
        
        return validation_results
    
    def _suggest_column_type(self, column_name: str) -> str:
        """
        Suggest appropriate SDRF column type for a given column name.
        
        Args:
            column_name: Name of the metadata column
            
        Returns:
            Suggested SDRF column type
        """
        # Map common column names to SDRF types
        name_lower = column_name.lower()
        
        if any(term in name_lower for term in ['organism', 'species', 'tissue', 'disease', 'cell line']):
            return 'Characteristics'
        elif any(term in name_lower for term in ['instrument', 'method', 'agent', 'modification']):
            return 'Comment'
        elif 'factor' in name_lower:
            return 'Factor value'
        else:
            return 'Comment'  # Default to Comment for unknown columns
    
    def export_sdrf_file(self, protocol_id: int, user_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Export protocol metadata as SDRF file format.
        
        Args:
            protocol_id (int): Protocol ID
            user_token (str, optional): Authentication token
            
        Returns:
            Dict containing SDRF file content and metadata
        """
        try:
            # Authenticate user if token provided
            user = None
            if user_token:
                user = get_authenticated_user(user_token)
            
            # Get protocol
            from cc.models import ProtocolModel, MetadataColumn
            try:
                protocol = ProtocolModel.objects.get(id=protocol_id)
            except ProtocolModel.DoesNotExist:
                return {
                    'success': False,
                    'error': f'Protocol {protocol_id} not found'
                }
            
            # Check permissions
            if user:
                if not validate_user_permissions(user, protocol_id):
                    return {
                        'success': False,
                        'error': 'Access denied to this protocol'
                    }
            
            # Get metadata columns for the protocol
            metadata_columns = MetadataColumn.objects.filter(protocol=protocol).order_by('column_position')
            
            # Generate SDRF content
            sdrf_content = self._generate_sdrf_content(metadata_columns, protocol)
            
            return {
                'success': True,
                'protocol_id': protocol_id,
                'protocol_title': protocol.protocol_title,
                'sdrf_content': sdrf_content,
                'total_columns': len(metadata_columns),
                'export_timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'SDRF export failed: {str(e)}',
                'protocol_id': protocol_id
            }
    
    def _generate_sdrf_content(self, metadata_columns, protocol) -> Dict[str, Any]:
        """
        Generate SDRF file content from metadata columns.
        
        Args:
            metadata_columns: QuerySet of MetadataColumn objects
            protocol: ProtocolModel instance
            
        Returns:
            Dict containing SDRF headers and data
        """
        # Build SDRF headers
        headers = []
        for column in metadata_columns:
            if column.type in ['Source name', 'Assay name', 'Material type', 'Technology type']:
                headers.append(column.name)
            else:
                headers.append(f"{column.type}[{column.name}]")
        
        # Build sample data (placeholder - in real implementation, this would come from samples)
        sample_data = []
        if headers:
            # Create a sample row with values
            sample_row = []
            for column in metadata_columns:
                value = column.value if column.value else 'not applicable'
                sample_row.append(value)
            sample_data.append(sample_row)
        
        return {
            'headers': headers,
            'data': sample_data,
            'file_format': 'tab-separated',
            'sdrf_version': '1.1'
        }