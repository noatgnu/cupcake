"""
Protocol analyzer tool for MCP server.

This tool analyzes protocol steps and extracts relevant biological
and analytical information for SDRF metadata generation.
"""

from typing import Dict, List, Optional, Any
from dataclasses import asdict
import json

from mcp_server.utils.django_setup import get_protocol_steps, get_authenticated_user
from mcp_server.utils.nlp_processor import ProtocolStepAnalyzer, ExtractedTerm, TermType
from mcp_server.utils.term_matcher import OntologyTermMatcher, MatchResult
from mcp_server.utils.anthropic_analyzer import SyncAnthropicAnalyzer


class ProtocolAnalyzer:
    """
    Analyzes protocol steps to extract terms and match them to ontologies.
    """
    
    def __init__(self, use_anthropic: bool = False, anthropic_api_key: Optional[str] = None):
        """
        Initialize the protocol analyzer with NLP and matching components.
        
        Args:
            use_anthropic: Whether to use Anthropic Claude for enhanced analysis
            anthropic_api_key: Anthropic API key (if not provided, uses environment variable)
        """
        self.use_anthropic = use_anthropic
        self.step_analyzer = ProtocolStepAnalyzer()
        self.term_matcher = OntologyTermMatcher()
        
        # Initialize Anthropic analyzer if requested
        self.anthropic_analyzer = None
        if use_anthropic:
            try:
                print(f"DEBUG: Initializing SyncAnthropicAnalyzer with api_key={anthropic_api_key is not None}")
                self.anthropic_analyzer = SyncAnthropicAnalyzer(anthropic_api_key)
                print(f"DEBUG: Successfully initialized Anthropic analyzer")
            except Exception as e:
                print(f"Warning: Could not initialize Anthropic analyzer: {e}")
                import traceback
                traceback.print_exc()
                self.use_anthropic = False
    
    def analyze_protocol_step(self, step_id: int, user_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze a single protocol step and extract relevant terms.
        
        Args:
            step_id (int): Protocol step ID
            user_token (str, optional): Authentication token
            
        Returns:
            Dict containing analysis results
        """
        try:
            # Authenticate user if token provided
            user = None
            if user_token:
                user = get_authenticated_user(user_token)
            
            # Get step from database
            from cc.models import ProtocolStep
            try:
                step = ProtocolStep.objects.get(id=step_id)
            except ProtocolStep.DoesNotExist:
                return {
                    'success': False,
                    'error': f'Protocol step {step_id} not found',
                    'step_id': step_id
                }
            
            # Check permissions if user provided
            if user and step.protocol:
                from ..utils.django_setup import validate_user_permissions
                if not validate_user_permissions(user, step.protocol.id):
                    return {
                        'success': False,
                        'error': 'Access denied to this protocol',
                        'step_id': step_id
                    }
            
            # Choose analysis method based on configuration
            print(f"DEBUG: self.use_anthropic={self.use_anthropic}, self.anthropic_analyzer={self.anthropic_analyzer is not None}")
            if self.use_anthropic and self.anthropic_analyzer:
                print("DEBUG: Using enhanced (Anthropic) analysis")
                analysis_result = self._analyze_step_content_enhanced(step)
            else:
                print("DEBUG: Using standard analysis")
                analysis_result = self._analyze_step_content(step)
            
            analysis_result['step_id'] = step_id
            analysis_result['success'] = True
            
            return analysis_result
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Analysis failed: {str(e)}',
                'step_id': step_id
            }
    
    def analyze_protocol(self, protocol_id: int, user_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze all steps in a protocol.
        
        Args:
            protocol_id (int): Protocol ID
            user_token (str, optional): Authentication token
            
        Returns:
            Dict containing analysis results for all steps
        """
        try:
            # Authenticate user if token provided
            user = None
            if user_token:
                user = get_authenticated_user(user_token)
            
            # Get protocol steps
            steps = get_protocol_steps(protocol_id, user)
            if steps is None:
                return {
                    'success': False,
                    'error': f'Protocol {protocol_id} not found or access denied',
                    'protocol_id': protocol_id
                }
            
            # Analyze each step
            step_analyses = []
            protocol_summary = {
                'organisms': set(),
                'tissues': set(),
                'instruments': set(),
                'diseases': set(),
                'modifications': set(),
                'chemicals': set(),
                'procedures': set(),
                'cellular_components': set()
            }
            
            for step in steps:
                step_analysis = self._analyze_step_content(step)
                step_analysis['step_id'] = step.id
                step_analyses.append(step_analysis)
                
                # Update protocol summary
                self._update_protocol_summary(protocol_summary, step_analysis)
            
            # Convert sets to lists for JSON serialization
            for key in protocol_summary:
                if isinstance(protocol_summary[key], set):
                    protocol_summary[key] = list(protocol_summary[key])
            
            return {
                'success': True,
                'protocol_id': protocol_id,
                'total_steps': len(step_analyses),
                'step_analyses': step_analyses,
                'protocol_summary': protocol_summary
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Protocol analysis failed: {str(e)}',
                'protocol_id': protocol_id
            }
    
    def _analyze_step_content(self, step) -> Dict[str, Any]:
        """
        Analyze the content of a single protocol step.
        
        Args:
            step: ProtocolStep model instance
            
        Returns:
            Dict containing analysis results
        """
        # Extract step information
        step_text = step.step_description or ""
        step_duration = step.step_duration
        section_name = step.step_section.section_description if step.step_section else None
        
        # Analyze text with NLP
        extracted_terms = self.step_analyzer.analyze_step_text(step_text)
        
        # Get term summary
        term_summary = self.step_analyzer.get_term_summary(extracted_terms)
        
        # Match terms to ontologies
        ontology_matches = self._match_terms_to_ontologies(extracted_terms)
        
        # Categorize matches by ontology type
        categorized_matches = self._categorize_matches(ontology_matches)
        
        return {
            'step_description': step_text,
            'step_duration': step_duration,
            'section_name': section_name,
            'extracted_terms': [term.to_dict() for term in extracted_terms],
            'term_summary': term_summary,
            'ontology_matches': [asdict(match) for match in ontology_matches],
            'categorized_matches': categorized_matches,
            'analysis_metadata': {
                'total_terms_extracted': len(extracted_terms),
                'total_ontology_matches': len(ontology_matches),
                'high_confidence_matches': len([m for m in ontology_matches if m.confidence >= 0.8])
            }
        }
    
    def _analyze_step_content_enhanced(self, step) -> Dict[str, Any]:
        """
        Analyze the content of a protocol step using Anthropic Claude.
        
        Args:
            step: ProtocolStep model instance
            
        Returns:
            Dict containing enhanced analysis results
        """
        # Extract step information
        step_text = step.step_description or ""
        step_duration = step.step_duration
        section_name = step.step_section.section_description if step.step_section else None
        
        # Build context for Claude
        context = {
            'section_name': section_name,
            'step_duration': step_duration
        }
        
        if step.protocol:
            context['protocol_title'] = step.protocol.protocol_title
            context['protocol_description'] = step.protocol.protocol_description[:200] if step.protocol.protocol_description else None
        
        # Get Claude analysis
        print(f"DEBUG: Calling Claude with step_text length: {len(step_text)}")
        claude_result = self.anthropic_analyzer.analyze_protocol_step_enhanced(step_text, context)
        print(f"DEBUG: Claude result success: {claude_result.get('success')}")
        
        if not claude_result.get('success'):
            # Fall back to standard analysis if Claude fails
            print(f"DEBUG: Claude analysis failed: {claude_result.get('error', 'Unknown error')}")
            return self._analyze_step_content(step)
        
        # Convert Claude's enhanced terms to standard format for compatibility
        extracted_terms = []
        for enhanced_term in claude_result.get('enhanced_terms', []):
            claude_term = enhanced_term['claude_term']
            
            # Create ExtractedTerm object
            term = ExtractedTerm(
                text=claude_term['text'],
                term_type=TermType(claude_term['term_type']),
                context=claude_term.get('biological_context', ''),
                confidence=claude_term['confidence'],
                start_pos=0,  # Claude doesn't provide exact positions
                end_pos=len(claude_term['text'])
            )
            extracted_terms.append(term)
        
        # Extract ontology matches from Claude's enhanced results
        ontology_matches = []
        for enhanced_term in claude_result.get('enhanced_terms', []):
            for match in enhanced_term.get('ontology_matches', []):
                # Create MatchResult object
                match_result = MatchResult(
                    ontology_type=match['ontology_type'],
                    ontology_id=match['ontology_id'],
                    ontology_name=match['ontology_name'],
                    accession=match['accession'],
                    confidence=match['combined_confidence'],
                    match_type=match['match_type'],
                    extracted_term=enhanced_term['claude_term']['text']
                )
                ontology_matches.append(match_result)
        
        # Get term summary
        term_summary = self.step_analyzer.get_term_summary(extracted_terms)
        
        # Categorize matches by ontology type
        categorized_matches = self._categorize_matches(ontology_matches)
        
        # Ensure claude_analysis is JSON serializable
        claude_analysis = claude_result.get('claude_analysis', {})
        serializable_claude_analysis = self._ensure_json_serializable(claude_analysis)
        
        # Ensure sdrf_suggestions_enhanced is JSON serializable
        sdrf_suggestions_enhanced = claude_result.get('sdrf_suggestions', {})
        serializable_sdrf_suggestions = self._ensure_json_serializable(sdrf_suggestions_enhanced)
        
        return {
            'step_description': step_text,
            'step_duration': step_duration,
            'section_name': section_name,
            'extracted_terms': [term.to_dict() for term in extracted_terms],
            'term_summary': term_summary,
            'ontology_matches': [asdict(match) for match in ontology_matches],
            'categorized_matches': categorized_matches,
            'analysis_metadata': {
                'analyzer_type': 'anthropic_claude',
                'total_terms_extracted': len(extracted_terms),
                'total_ontology_matches': len(ontology_matches),
                'high_confidence_matches': len([m for m in ontology_matches if m.confidence >= 0.8]),
                'claude_insights': claude_result.get('biological_insights', {}),
                'quality_assessment': claude_result.get('claude_analysis', {}).get('quality_assessment', {})
            },
            'claude_analysis': serializable_claude_analysis,
            'sdrf_suggestions_enhanced': serializable_sdrf_suggestions
        }
    
    def _ensure_json_serializable(self, obj: Any) -> Any:
        """
        Recursively ensure all objects in a data structure are JSON serializable.
        Converts ClaudeExtractedTerm and other custom objects to dictionaries.
        """
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        elif isinstance(obj, dict):
            return {key: self._ensure_json_serializable(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._ensure_json_serializable(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            # For any other object type, try to convert to string as fallback
            try:
                return str(obj)
            except:
                return None
    
    def _match_terms_to_ontologies(self, extracted_terms: List[ExtractedTerm]) -> List[MatchResult]:
        """
        Match extracted terms to ontology terms.
        
        Args:
            extracted_terms: List of ExtractedTerm objects
            
        Returns:
            List of MatchResult objects
        """
        # Group terms by type for targeted matching
        term_groups = {}
        for term in extracted_terms:
            if term.term_type not in term_groups:
                term_groups[term.term_type] = []
            term_groups[term.term_type].append(term.text)
        
        all_matches = []
        
        # Match each term type to appropriate ontologies
        for term_type, terms in term_groups.items():
            if term_type == TermType.ORGANISM:
                matches = self.term_matcher.match_terms(terms, ['species'], min_confidence=0.6)
                all_matches.extend(matches)
                
            elif term_type == TermType.TISSUE:
                matches = self.term_matcher.match_terms(terms, ['tissue'], min_confidence=0.6)
                all_matches.extend(matches)
                
            elif term_type == TermType.DISEASE:
                matches = self.term_matcher.match_terms(terms, ['human_disease'], min_confidence=0.6)
                all_matches.extend(matches)
                
            elif term_type == TermType.CELLULAR_COMPONENT:
                matches = self.term_matcher.match_terms(terms, ['subcellular_location'], min_confidence=0.6)
                all_matches.extend(matches)
                
            elif term_type == TermType.MODIFICATION:
                matches = self.term_matcher.match_terms(terms, ['unimod'], min_confidence=0.6)
                all_matches.extend(matches)
                
            elif term_type == TermType.INSTRUMENT:
                # Use MS vocabularies with instrument term type
                for term in terms:
                    matches = self.term_matcher.search_by_term_type(term, 'instrument')
                    all_matches.extend(matches)
                    
            elif term_type == TermType.CHEMICAL:
                # Try multiple MS vocabulary term types for chemicals
                chemical_types = ['cleavage agent', 'reduction reagent', 'alkylation reagent']
                for term in terms:
                    for chem_type in chemical_types:
                        matches = self.term_matcher.search_by_term_type(term, chem_type)
                        all_matches.extend(matches)
        
        return all_matches
    
    def _categorize_matches(self, matches: List[MatchResult]) -> Dict[str, List[Dict]]:
        """
        Categorize ontology matches by ontology type.
        
        Args:
            matches: List of MatchResult objects
            
        Returns:
            Dict mapping ontology types to match lists
        """
        categorized = {}
        
        for match in matches:
            if match.ontology_type not in categorized:
                categorized[match.ontology_type] = []
            
            categorized[match.ontology_type].append({
                'ontology_id': match.ontology_id,
                'ontology_name': match.ontology_name,
                'accession': match.accession,
                'confidence': match.confidence,
                'match_type': match.match_type,
                'extracted_term': match.extracted_term
            })
        
        # Sort each category by confidence
        for ontology_type in categorized:
            categorized[ontology_type].sort(key=lambda x: x['confidence'], reverse=True)
        
        return categorized
    
    def _update_protocol_summary(self, summary: Dict, step_analysis: Dict):
        """
        Update protocol-level summary with step analysis results.
        
        Args:
            summary: Protocol summary dict to update
            step_analysis: Individual step analysis results
        """
        term_summary = step_analysis.get('term_summary', {})
        
        for term_type, terms in term_summary.items():
            if term_type in summary:
                summary[term_type].update(terms)
    
    def get_step_sdrf_suggestions(self, step_id: int, user_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Get SDRF metadata suggestions for a protocol step.
        
        Args:
            step_id (int): Protocol step ID
            user_token (str, optional): Authentication token
            
        Returns:
            Dict containing SDRF metadata suggestions
        """
        # Analyze the step
        analysis = self.analyze_protocol_step(step_id, user_token)
        
        if not analysis.get('success'):
            return analysis
        
        # Generate SDRF suggestions based on matches
        sdrf_suggestions = self._generate_sdrf_suggestions(analysis)
        
        # Add SDRF-specific suggestions using new term matcher functions
        step_text = analysis.get('step_description', '')
        if step_text:
            # Add label suggestions
            label_suggestions = self.term_matcher.get_sdrf_label_suggestions(step_text)
            if label_suggestions:
                sdrf_suggestions['label'] = [{'suggested_value': label, 'confidence': 0.8, 'source': 'text_analysis'} for label in label_suggestions]
            
            # Add modification suggestions
            mod_suggestions = self.term_matcher.get_sdrf_modification_suggestions(step_text)
            if mod_suggestions:
                sdrf_suggestions['modification parameters'] = [{'key_value_format': mod, 'confidence': 0.8, 'source': 'text_analysis'} for mod in mod_suggestions]
            
            # Add cleavage agent suggestions
            cleavage_suggestions = self.term_matcher.get_sdrf_cleavage_suggestions(step_text)
            if cleavage_suggestions:
                sdrf_suggestions['cleavage agent details'] = [{'key_value_format': enzyme, 'confidence': 0.8, 'source': 'text_analysis'} for enzyme in cleavage_suggestions]
            
            # Add demographic and experimental metadata suggestions
            demographic_columns = ['age', 'sex', 'biological_replicate', 'technical_replicate', 'fraction_identifier']
            for column in demographic_columns:
                demo_suggestions = self.term_matcher.get_sdrf_demographic_suggestions(step_text, column)
                if demo_suggestions:
                    # Convert to expected format and add ontology information
                    formatted_suggestions = []
                    for demo_sugg in demo_suggestions:
                        formatted_sugg = {
                            'ontology_type': column,
                            'ontology_id': f'{column}_{demo_sugg["suggested_value"]}',
                            'ontology_name': demo_sugg['suggested_value'],
                            'accession': '',
                            'confidence': demo_sugg['confidence'],
                            'extracted_term': demo_sugg['suggested_value'],
                            'match_type': 'demographic_suggestion',
                            'source': demo_sugg['source'],
                            'ontology_source': demo_sugg['ontology_source'],
                            'suggested_value': demo_sugg['suggested_value']
                        }
                        formatted_suggestions.append(formatted_sugg)
                    
                    sdrf_suggestions[column] = formatted_suggestions
            
        
        return {
            'success': True,
            'step_id': step_id,
            'sdrf_suggestions': sdrf_suggestions,
            'analysis_summary': {
                'total_matches': len(analysis.get('ontology_matches', [])),
                'high_confidence_matches': analysis.get('analysis_metadata', {}).get('high_confidence_matches', 0),
                'sdrf_specific_suggestions': sum(len(suggestions) for suggestions in sdrf_suggestions.values())
            }
        }
    
    def _generate_sdrf_suggestions(self, analysis: Dict) -> Dict[str, List[Dict]]:
        """
        Generate SDRF metadata column suggestions from analysis results.
        
        Args:
            analysis: Step analysis results
            
        Returns:
            Dict mapping SDRF column types to suggested values
        """
        suggestions = {}
        categorized_matches = analysis.get('categorized_matches', {})
        
        # Map ontology types to SDRF column names (name only, not type)
        ontology_to_sdrf = {
            # Legacy ontologies -> SDRF names
            'species': 'organism',
            'tissue': 'organism part',
            'human_disease': 'disease',
            'subcellular_location': 'subcellular localization',
            'cell_type': 'cell type',
            'ms_vocabularies': None,  # Will be determined by term_type
            'unimod': 'modification parameters',
            
            # Enhanced ontologies -> SDRF names
            'mondo_disease': 'disease',
            'uberon_anatomy': 'organism part', 
            'ncbi_taxonomy': 'organism',
            'chebi_compound': None,  # Will be determined by compound type
            'psims_ontology': None,  # Will be determined by category
            'cell_type': 'cell type'
        }
        
        for ontology_type, matches in categorized_matches.items():
            # Skip low confidence matches
            high_conf_matches = [m for m in matches if m['confidence'] >= 0.7]
            
            if not high_conf_matches:
                continue
            
            if ontology_type == 'ms_vocabularies':
                # Group MS vocabulary matches by term type
                ms_groups = {}
                for match in high_conf_matches:
                    # Get the actual term type from the database
                    term_type = self._get_ms_term_type(match['ontology_id'])
                    if term_type:
                        sdrf_column = self._ms_term_type_to_sdrf(term_type)
                        if sdrf_column:
                            if sdrf_column not in ms_groups:
                                ms_groups[sdrf_column] = []
                            ms_groups[sdrf_column].append(match)
                
                suggestions.update(ms_groups)
            elif ontology_type == 'unimod':
                # Process UniMod matches with rich metadata in key-value format
                unimod_suggestions = []
                for match in high_conf_matches:
                    # Create key-value format for UniMod as expected by frontend
                    key_value_format = {
                        'NT': match.get('ontology_name', ''),  # Name
                        'AC': match.get('accession', '')       # Accession
                    }
                    
                    # Add rich metadata if available
                    if match.get('additional_metadata'):
                        metadata = match['additional_metadata']
                        if metadata.get('target_aa'):
                            key_value_format['TA'] = metadata['target_aa']
                        if metadata.get('modification_type'):
                            key_value_format['MT'] = metadata['modification_type']
                        if metadata.get('position'):
                            key_value_format['PP'] = metadata['position']
                    
                    # Add monoisotopic mass if available
                    if match.get('mass_info'):
                        key_value_format['MM'] = match['mass_info']
                    
                    # Create suggestion with key-value format
                    unimod_suggestion = {
                        'ontology_type': 'modification parameters',
                        'ontology_id': match['ontology_id'],
                        'ontology_name': match['ontology_name'],
                        'accession': match['accession'],
                        'confidence': match['confidence'],
                        'extracted_term': match['extracted_term'],
                        'match_type': match['match_type'],
                        'key_value_format': key_value_format,
                        'source': 'standard_analysis',
                        'ontology_source': 'legacy',
                        # Include rich metadata for display
                        'target_aa': key_value_format.get('TA'),
                        'monoisotopic_mass': key_value_format.get('MM'),
                        'modification_type': key_value_format.get('MT'),
                        'position': key_value_format.get('PP'),
                        'definition': match.get('definition'),
                        'chemical_formula': match.get('chemical_formula')
                    }
                    unimod_suggestions.append(unimod_suggestion)
                
                if unimod_suggestions:
                    suggestions['modification parameters'] = unimod_suggestions
            else:
                sdrf_column = ontology_to_sdrf.get(ontology_type)
                if sdrf_column:
                    suggestions[sdrf_column] = high_conf_matches
        
        return suggestions
    
    def _get_ms_term_type(self, ontology_id: str) -> Optional[str]:
        """Get the term_type for an MS vocabulary entry."""
        try:
            from cc.models import MSUniqueVocabularies
            ms_term = MSUniqueVocabularies.objects.get(pk=ontology_id)
            return ms_term.term_type
        except:
            return None
    
    def _ms_term_type_to_sdrf(self, term_type: str) -> Optional[str]:
        """Map MS vocabulary term types to SDRF column names."""
        mapping = {
            'instrument': 'instrument',
            'cleavage agent': 'cleavage agent details',
            'dissociation method': 'dissociation method',
            'enrichment process': 'enrichment process',
            'fractionation method': 'fractionation method',
            'reduction reagent': 'reduction reagent',
            'alkylation reagent': 'alkylation reagent',
            'mass analyzer type': 'MS2 analyzer type',
            'cell line': 'cell line',
            'collision energy': 'collision energy',
            'proteomics data acquisition method': 'proteomics data acquisition method',
            'precursor mass tolerance': 'precursor mass tolerance',
            'fragment mass tolerance': 'fragment mass tolerance'
        }
        return mapping.get(term_type)