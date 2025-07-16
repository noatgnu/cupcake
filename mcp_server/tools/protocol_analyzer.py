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
from mcp_server.utils.mcp_claude_client import SyncMCPClaudeClient


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
        
        # Initialize MCP-enabled Claude analyzer if requested
        self.anthropic_analyzer = None
        if use_anthropic:
            try:
                print(f"DEBUG: Initializing MCP Claude Client with database access")
                self.anthropic_analyzer = SyncMCPClaudeClient(anthropic_api_key)
                print(f"DEBUG: Successfully initialized MCP Claude analyzer with database tools")
            except Exception as e:
                print(f"Warning: Could not initialize MCP Claude analyzer: {e}")
                # Fallback to regular Anthropic analyzer
                try:
                    print(f"DEBUG: Falling back to regular Anthropic analyzer")
                    self.anthropic_analyzer = SyncAnthropicAnalyzer(anthropic_api_key)
                    print(f"DEBUG: Fallback successful - using regular Claude without database access")
                except Exception as e2:
                    print(f"Warning: Could not initialize any Anthropic analyzer: {e2}")
                    import traceback
                    traceback.print_exc()
                    self.use_anthropic = False
        
        # Initialize NLP processor with AI client for enhanced term extraction
        ai_client = self.anthropic_analyzer if use_anthropic else None
        self.step_analyzer = ProtocolStepAnalyzer(ai_client=ai_client)
        self.term_matcher = OntologyTermMatcher()
    
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
                print("DEBUG: Using enhanced (Claude) analysis")
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
    
    def _analyze_step_content(self, step, ai_context: dict = None) -> Dict[str, Any]:
        """
        Analyze the content of a single protocol step.
        
        Args:
            step: ProtocolStep model instance
            ai_context: Optional AI analysis context for enhanced scoring
            
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
        
        # Match terms to ontologies with AI context
        ontology_matches = self._match_terms_to_ontologies(extracted_terms, ai_context)
        
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
                'analyzer_type': 'standard_nlp',
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
        
        # Get Claude analysis with MCP database access
        print(f"DEBUG: Calling MCP Claude with step_text length: {len(step_text)}")
        print(f"DEBUG: Step text preview: {step_text[:200]}...")
        
        # Check if we're using MCP client or regular analyzer  
        # MCP client is SyncMCPClaudeClient, regular is SyncAnthropicAnalyzer
        if type(self.anthropic_analyzer).__name__ == 'SyncMCPClaudeClient':
            print(f"DEBUG: Using MCP Claude client with database tools")
            claude_result = self.anthropic_analyzer.analyze_protocol_step_enhanced(step_text, context)
        else:
            print(f"DEBUG: Using regular Claude analyzer (fallback)")
            claude_result = self.anthropic_analyzer.analyze_protocol_step_enhanced(step_text, context)
        
        print(f"DEBUG: Claude result success: {claude_result.get('success')}")
        print(f"DEBUG: Claude result keys: {list(claude_result.keys())}")
        if claude_result.get('extracted_terms'):
            print(f"DEBUG: Extracted terms count: {len(claude_result.get('extracted_terms', []))}")
        if claude_result.get('sdrf_suggestions'):
            print(f"DEBUG: SDRF suggestions keys: {list(claude_result.get('sdrf_suggestions', {}).keys())}")
            print(f"DEBUG: SDRF suggestions: {claude_result.get('sdrf_suggestions', {})}")
        
        if not claude_result.get('success'):
            # Fall back to standard analysis if Claude fails
            print(f"DEBUG: Claude analysis failed: {claude_result.get('error', 'Unknown error')}")
            return self._analyze_step_content(step)
        
        # Handle different response formats from MCP vs regular Claude
        extracted_terms = []
        ontology_matches = []
        
        # Determine analyzer type first (needed throughout)
        analyzer_type = 'mcp_claude' if type(self.anthropic_analyzer).__name__ == 'SyncMCPClaudeClient' else 'anthropic_claude'
        
        if type(self.anthropic_analyzer).__name__ == 'SyncMCPClaudeClient':
            # MCP client format - Claude used database tools directly
            print(f"DEBUG: Processing MCP Claude response format")
            
            # Extract terms from MCP response
            for term_data in claude_result.get('extracted_terms', []):
                term = ExtractedTerm(
                    text=term_data['text'],
                    term_type=TermType(term_data['term_type']),
                    context=term_data.get('context', ''),
                    confidence=term_data['confidence'],
                    start_pos=term_data.get('start_pos', 0),
                    end_pos=term_data.get('end_pos', len(term_data['text']))
                )
                extracted_terms.append(term)
            
            # Convert MCP tool results to MatchResult objects
            tools_used = []
            if 'analysis_metadata' in claude_result and 'tools_used' in claude_result['analysis_metadata']:
                tools_used = claude_result['analysis_metadata']['tools_used']
            elif 'tools_used' in claude_result:
                tools_used = claude_result['tools_used']
            
            print(f"DEBUG: Processing {len(tools_used)} tools from MCP")
            
            for tool in tools_used:
                tool_name = tool.get('tool', '')
                tool_results = tool.get('result', [])
                
                print(f"DEBUG: Processing tool {tool_name} with {len(tool_results)} results")
                
                if tool_name == 'search_unimod_modifications' and tool_results:
                    for result in tool_results:
                        # Create MatchResult object from MCP tool result
                        match_result = MatchResult(
                            ontology_type='unimod',
                            ontology_id=result.get('accession', ''),
                            ontology_name=result.get('name', ''),
                            accession=result.get('accession', ''),
                            confidence=result.get('confidence', 1.0),
                            match_type=result.get('match_type', 'exact'),
                            extracted_term=tool.get('input', {}).get('query', 'unknown'),
                            # Add rich metadata
                            chemical_formula=result.get('chemical_formula'),
                            mass_info=result.get('monoisotopic_mass'),
                            target_info=result.get('target_amino_acids'),
                            additional_metadata={
                                'modification_type': result.get('modification_type'),
                                'position': result.get('position'),
                                'target_aa': result.get('target_amino_acids'),
                                'sdrf_format': result.get('sdrf_format')
                            }
                        )
                        ontology_matches.append(match_result)
                        print(f"DEBUG: Added UniMod match: {result.get('name', '')} ({result.get('accession', '')})")
                
                elif tool_name == 'search_ontology' and tool_results:
                    for result in tool_results:
                        # Create MatchResult object from ontology search
                        match_result = MatchResult(
                            ontology_type=result.get('ontology_type', ''),
                            ontology_id=result.get('accession', ''),
                            ontology_name=result.get('ontology_name', ''),
                            accession=result.get('accession', ''),
                            confidence=result.get('confidence', 0.5),
                            match_type=result.get('match_type', 'fuzzy'),
                            extracted_term=result.get('extracted_term', ''),
                            definition=result.get('definition'),
                            chemical_formula=result.get('chemical_formula'),
                            mass_info=result.get('mass_info')
                        )
                        ontology_matches.append(match_result)
                        print(f"DEBUG: Added ontology match: {result.get('ontology_name', '')} ({result.get('ontology_type', '')})")
            
            print(f"DEBUG: Total ontology matches created: {len(ontology_matches)}")
            
            # SDRF suggestions start empty - will be generated from ontology matches
            sdrf_suggestions = claude_result.get('sdrf_suggestions', {})
            
        else:
            # Regular Claude format - needs ontology matching
            print(f"DEBUG: Processing regular Claude response format")
            
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
            
            # Extract ontology matches from regular Claude results
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
            
            # Get SDRF suggestions from regular Claude results
            sdrf_suggestions = claude_result.get('sdrf_suggestions', {})
        
        # Get term summary
        term_summary = self.step_analyzer.get_term_summary(extracted_terms)
        
        # Categorize matches by ontology type
        categorized_matches = self._categorize_matches(ontology_matches)
        
        # Generate SDRF suggestions from ontology matches if sdrf_suggestions is empty
        if not sdrf_suggestions and ontology_matches:
            mock_analysis = {
                'categorized_matches': categorized_matches,
                'ontology_matches': ontology_matches
            }
            generated_suggestions = self._generate_sdrf_suggestions(mock_analysis)
            if generated_suggestions:
                sdrf_suggestions = generated_suggestions
        
        # Ensure SDRF suggestions are JSON serializable
        serializable_sdrf_suggestions = self._ensure_json_serializable(sdrf_suggestions)
        
        return {
            'step_description': step_text,
            'step_duration': step_duration,
            'section_name': section_name,
            'extracted_terms': [term.to_dict() for term in extracted_terms],
            'term_summary': term_summary,
            'ontology_matches': [asdict(match) for match in ontology_matches],
            'categorized_matches': categorized_matches,
            'analysis_metadata': {
                'analyzer_type': analyzer_type,
                'total_terms_extracted': len(extracted_terms),
                'total_ontology_matches': len(ontology_matches),
                'high_confidence_matches': len([m for m in ontology_matches if m.confidence >= 0.8]),
                'tools_used': claude_result.get('analysis_metadata', {}).get('tools_used', []),
                'database_access': type(self.anthropic_analyzer).__name__ == 'SyncMCPClaudeClient'
            },
            'claude_analysis': claude_result.get('claude_analysis', {}),
            'sdrf_suggestions': serializable_sdrf_suggestions
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
    
    def _match_terms_to_ontologies(self, extracted_terms: List[ExtractedTerm], ai_context: dict = None) -> List[MatchResult]:
        """
        Match extracted terms to ontology terms.
        
        Args:
            extracted_terms: List of ExtractedTerm objects
            ai_context: Optional AI analysis context for enhanced scoring
            
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
                matches = self.term_matcher.match_terms(terms, ['species'], min_confidence=0.6, ai_context=ai_context)
                all_matches.extend(matches)
                
            elif term_type == TermType.TISSUE:
                matches = self.term_matcher.match_terms(terms, ['tissue'], min_confidence=0.6, ai_context=ai_context)
                all_matches.extend(matches)
                
            elif term_type == TermType.DISEASE:
                matches = self.term_matcher.match_terms(terms, ['human_disease'], min_confidence=0.6, ai_context=ai_context)
                all_matches.extend(matches)
                
            elif term_type == TermType.CELLULAR_COMPONENT:
                matches = self.term_matcher.match_terms(terms, ['subcellular_location'], min_confidence=0.6, ai_context=ai_context)
                all_matches.extend(matches)
                
            elif term_type == TermType.MODIFICATION:
                matches = self.term_matcher.match_terms(terms, ['unimod'], min_confidence=0.6, ai_context=ai_context)
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
        # Determine analyzer type based on configuration
        analyzer_type = self._get_analyzer_type()
        
        # Try to get cached suggestions first
        cached_result = self._get_cached_suggestions(step_id, analyzer_type)
        
        if cached_result:
            print(f"DEBUG: Using cached suggestions for step {step_id} with analyzer {analyzer_type}")
            return cached_result
        
        print(f"DEBUG: No cache found for step {step_id} with analyzer {analyzer_type}, performing analysis")
        
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
            demographic_columns = ['age', 'sex']
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
            
        
        result = {
            'success': True,
            'step_id': step_id,
            'sdrf_suggestions': sdrf_suggestions,
            'analysis_metadata': analysis.get('analysis_metadata', {}),
            'extracted_terms': analysis.get('extracted_terms', []),
            'analysis_summary': {
                'total_matches': len(analysis.get('ontology_matches', [])),
                'high_confidence_matches': analysis.get('analysis_metadata', {}).get('high_confidence_matches', 0),
                'sdrf_specific_suggestions': sum(len(suggestions) for suggestions in sdrf_suggestions.values())
            }
        }
        
        # Cache the result for future use
        self._cache_suggestions(step_id, analyzer_type, result)
        print(f"DEBUG: Cached suggestions for step {step_id} with analyzer {analyzer_type}")
        
        return result
    
    def analyze_protocol_steps_batch(self, step_ids: List[int], user_token: Optional[str] = None, batch_size: int = 5) -> List[Dict[str, Any]]:
        """
        Analyze multiple protocol steps using batch processing for efficiency.
        
        Args:
            step_ids: List of protocol step IDs
            user_token: Optional authentication token  
            batch_size: Number of steps to process per batch
            
        Returns:
            List of analysis results for each step
        """
        if not self.use_anthropic or not self.anthropic_analyzer:
            # Fall back to individual processing for standard analysis
            results = []
            for step_id in step_ids:
                result = self.get_step_sdrf_suggestions(step_id, user_token)
                results.append(result)
            return results
        
        # Get all steps first
        from cc.models import ProtocolStep
        steps = []
        for step_id in step_ids:
            try:
                step = ProtocolStep.objects.get(id=step_id)
                steps.append((step_id, step))
            except ProtocolStep.DoesNotExist:
                steps.append((step_id, None))
        
        # Prepare batch data for Claude
        step_texts = []
        valid_steps = []
        
        for step_id, step in steps:
            if step:
                step_texts.append(step.step_description)
                valid_steps.append((step_id, step))
            else:
                valid_steps.append((step_id, None))
        
        # Use batch analysis if we have MCP Claude client
        if hasattr(self.anthropic_analyzer, 'analyze_protocol_steps_batch'):
            print(f"DEBUG: Using batch analysis for {len(step_texts)} steps")
            batch_results = self.anthropic_analyzer.analyze_protocol_steps_batch(step_texts, batch_size=batch_size)
        else:
            # Fallback to individual analysis
            print(f"DEBUG: Falling back to individual analysis")
            batch_results = []
            for step_text in step_texts:
                result = self.anthropic_analyzer.analyze_protocol_step_enhanced(step_text)
                batch_results.append(result)
        
        # Process results and generate SDRF suggestions
        final_results = []
        batch_index = 0
        
        for step_id, step in valid_steps:
            if step is None:
                # Step not found
                final_results.append({
                    'success': False,
                    'error': f'Protocol step {step_id} not found',
                    'step_id': step_id
                })
            else:
                # Process batch result
                if batch_index < len(batch_results):
                    analysis = batch_results[batch_index]
                    batch_index += 1
                    
                    if analysis.get('success'):
                        # Generate SDRF suggestions
                        sdrf_suggestions = self._generate_sdrf_suggestions(analysis)
                        
                        # Add SDRF-specific suggestions  
                        step_text = analysis.get('step_description', step.step_description)
                        if step_text:
                            # Add all the demographic/experimental suggestions
                            demographic_columns = ['age', 'sex']
                            for column in demographic_columns:
                                demo_suggestions = self.term_matcher.get_sdrf_demographic_suggestions(step_text, column)
                                if demo_suggestions:
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
                        
                        final_results.append({
                            'success': True,
                            'step_id': step_id,
                            'sdrf_suggestions': sdrf_suggestions,
                            'analysis_metadata': analysis.get('analysis_metadata', {}),
                            'extracted_terms': analysis.get('extracted_terms', []),
                            'analysis_summary': {
                                'total_matches': len(analysis.get('ontology_matches', [])),
                                'high_confidence_matches': analysis.get('analysis_metadata', {}).get('high_confidence_matches', 0),
                                'sdrf_specific_suggestions': sum(len(suggestions) for suggestions in sdrf_suggestions.values())
                            }
                        })
                    else:
                        final_results.append({
                            'success': False,
                            'error': analysis.get('error', 'Analysis failed'),
                            'step_id': step_id
                        })
                else:
                    # No batch result available
                    final_results.append({
                        'success': False,
                        'error': 'Batch analysis incomplete',
                        'step_id': step_id
                    })
        
        return final_results
    
    def _get_analyzer_type(self) -> str:
        """Get the current analyzer type based on configuration."""
        if self.use_anthropic and self.anthropic_analyzer:
            if hasattr(self.anthropic_analyzer, 'analyze_protocol_steps_batch'):
                return 'mcp_claude'
            else:
                return 'anthropic_claude'
        else:
            return 'standard_nlp'
    
    def _get_cached_suggestions(self, step_id: int, analyzer_type: str):
        """Get cached suggestions for a step."""
        try:
            from cc.models import ProtocolStepSuggestionCache
            return ProtocolStepSuggestionCache.get_cached_suggestions(step_id, analyzer_type)
        except ImportError:
            print("DEBUG: Could not import ProtocolStepSuggestionCache")
            return None
    
    def _cache_suggestions(self, step_id: int, analyzer_type: str, suggestions_data: dict):
        """Cache suggestions for a step."""
        try:
            from cc.models import ProtocolStepSuggestionCache
            return ProtocolStepSuggestionCache.cache_suggestions(step_id, analyzer_type, suggestions_data)
        except ImportError:
            print("DEBUG: Could not import ProtocolStepSuggestionCache")
            return None
    
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
                    
                    # Add rich metadata - get comprehensive data from UniMod database
                    try:
                        from cc.models import Unimod
                        unimod_record = Unimod.objects.get(accession=match.get('accession'))
                        
                        # Parse additional_data for comprehensive metadata
                        if unimod_record.additional_data:
                            additional_data = unimod_record.additional_data
                            metadata_dict = {}
                            
                            # Convert list format to dictionary
                            if isinstance(additional_data, list):
                                for item in additional_data:
                                    if isinstance(item, dict) and 'id' in item and 'description' in item:
                                        metadata_dict[item['id']] = item['description']
                            
                            # Extract target amino acids and position from spec fields
                            target_sites = []
                            positions = []
                            classifications = []
                            
                            for i in range(1, 10):  # Check spec_1, spec_2, etc.
                                site_key = f'spec_{i}_site'
                                pos_key = f'spec_{i}_position'
                                class_key = f'spec_{i}_classification'
                                
                                if site_key in metadata_dict:
                                    site = metadata_dict[site_key]
                                    if site and site != 'N-term' and site != 'C-term':
                                        target_sites.append(site)
                                
                                if pos_key in metadata_dict:
                                    position = metadata_dict[pos_key]
                                    if position:
                                        positions.append(position)
                                
                                if class_key in metadata_dict:
                                    classification = metadata_dict[class_key]
                                    if classification:
                                        classifications.append(classification)
                            
                            # Add target amino acids (filter to common ones)
                            if target_sites:
                                valid_sites = [site for site in set(target_sites) if len(site) == 1 and site.isalpha()]
                                if valid_sites:
                                    sorted_sites = sorted(valid_sites)
                                    if len(sorted_sites) > 5:
                                        # Use common targets for well-known modifications
                                        common_targets = {
                                            'Phospho': ['S', 'T', 'Y'],
                                            'Acetyl': ['K'],
                                            'Methyl': ['K', 'R'],
                                            'Oxidation': ['M']
                                        }
                                        mod_name = match.get('ontology_name', '')
                                        if mod_name in common_targets:
                                            key_value_format['TA'] = ','.join(common_targets[mod_name])
                                        else:
                                            key_value_format['TA'] = ','.join(sorted_sites[:5])
                                    else:
                                        key_value_format['TA'] = ','.join(sorted_sites)
                            
                            # Add modification type (map to SDRF values)
                            if classifications:
                                unique_classifications = list(dict.fromkeys(classifications))
                                classification = unique_classifications[0].lower()
                                if 'post-translational' in classification or 'ptm' in classification:
                                    key_value_format['MT'] = "Variable"
                                elif 'chemical' in classification or 'artifact' in classification:
                                    key_value_format['MT'] = "Fixed"
                                else:
                                    key_value_format['MT'] = "Variable"
                            
                            # Add position (remove duplicates)
                            if positions:
                                unique_positions = list(dict.fromkeys(positions))
                                position_value = unique_positions[0]
                                # Additional check: if the position value itself has comma-separated duplicates
                                if ',' in position_value:
                                    position_parts = [p.strip() for p in position_value.split(',')]
                                    unique_position_parts = list(dict.fromkeys(position_parts))
                                    position_value = ','.join(unique_position_parts)
                                key_value_format['PP'] = position_value
                            else:
                                # Default position
                                key_value_format['PP'] = "Anywhere"
                    
                    except Exception as e:
                        # Fallback to basic metadata if comprehensive extraction fails
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
                    
                    # Create comprehensive SDRF string format
                    sdrf_parts = []
                    for key in ['NT', 'AC', 'TA', 'MT', 'PP', 'MM']:
                        if key in key_value_format and key_value_format[key]:
                            value = str(key_value_format[key])
                            # Remove duplicates from comma-separated values
                            if ',' in value:
                                parts = [p.strip() for p in value.split(',')]
                                unique_parts = list(dict.fromkeys(parts))
                                value = ','.join(unique_parts)
                            sdrf_parts.append(f"{key}={value}")
                    
                    sdrf_format_string = ';'.join(sdrf_parts)
                    
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
                        'sdrf_format': sdrf_format_string,
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