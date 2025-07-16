"""
Anthropic Claude-powered protocol analysis.

This module provides enhanced protocol step analysis using Claude API
while still leveraging the existing ontology database for term matching.
"""

import os
import json
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
import asyncio
import aiohttp
from datetime import datetime

from .nlp_processor import ExtractedTerm, TermType
from .django_setup import get_ontology_models


@dataclass
class ClaudeExtractedTerm:
    """Term extracted by Claude with enhanced metadata."""
    text: str
    term_type: TermType
    context: str
    confidence: float
    start_pos: int
    end_pos: int
    claude_reasoning: str
    suggested_ontology: Optional[str] = None
    biological_context: Optional[str] = None
    
    def to_dict(self):
        """Convert to JSON-serializable dictionary."""
        return {
            'text': self.text,
            'term_type': self.term_type.value,  # Convert enum to string
            'context': self.context,
            'confidence': self.confidence,
            'start_pos': self.start_pos,
            'end_pos': self.end_pos,
            'claude_reasoning': self.claude_reasoning,
            'suggested_ontology': self.suggested_ontology,
            'biological_context': self.biological_context
        }


class AnthropicProtocolAnalyzer:
    """
    Enhanced protocol analyzer using Anthropic Claude API.
    
    This analyzer uses Claude for sophisticated natural language understanding
    while still matching terms against your existing ontology database.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Anthropic analyzer.
        
        Args:
            api_key: Anthropic API key. If None, will try to get from environment.
        """
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY environment variable.")
        
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.model = "claude-3-5-sonnet-20241022"  # Latest Claude 3.5 Sonnet model
        
        # Get available ontologies for Claude context
        try:
            self.ontology_models = get_ontology_models()
            self._setup_ontology_context()
        except Exception as e:
            print(f"Warning: Could not setup ontology context: {e}")
            self.ontology_models = {}
            self.ontology_context = {}
    
    def _setup_ontology_context(self):
        """Setup comprehensive SDRF ontology context information for Claude."""
        self.ontology_context = {
            'species': {
                'description': 'Organism species with NCBI Taxonomy IDs for characteristics[organism]',
                'examples': ['Homo sapiens', 'Mus musculus', 'Rattus norvegicus', 'Escherichia coli'],
                'fields': ['official_name', 'common_name', 'taxon', 'code'],
                'sdrf_column': 'organism'
            },
            'tissue': {
                'description': 'Tissue and organism parts with Uberon ontology for characteristics[organism part]',
                'examples': ['liver', 'brain cortex', 'blood plasma', 'muscle tissue', 'kidney', 'heart', 'lung'],
                'fields': ['identifier', 'accession', 'synonyms'],
                'sdrf_column': 'organism part'
            },
            'human_disease': {
                'description': 'Human diseases and conditions from MONDO for characteristics[disease]',
                'examples': ['cancer', 'diabetes mellitus', 'Alzheimer disease', 'liver cancer', 'normal'],
                'fields': ['identifier', 'accession', 'acronym', 'synonyms'],
                'sdrf_column': 'disease'
            },
            'subcellular_location': {
                'description': 'Cellular components and subcellular locations for characteristics[subcellular localization]',
                'examples': ['nucleus', 'mitochondria', 'endoplasmic reticulum', 'cytoplasm', 'membrane'],
                'fields': ['location_identifier', 'accession', 'synonyms'],
                'sdrf_column': 'subcellular localization'
            },
            'cell_type': {
                'description': 'Cell types and cell lines for characteristics[cell type]',
                'examples': ['HEK293', 'HeLa', 'MCF-7', 'Jurkat', 'epithelial cell', 'fibroblast'],
                'fields': ['name', 'identifier', 'synonyms', 'cell_line', 'organism'],
                'sdrf_column': 'cell type'
            },
            'mondo_disease': {
                'description': 'Enhanced disease ontology from MONDO for characteristics[disease]',
                'examples': ['cancer', 'diabetes mellitus', 'Alzheimer disease', 'breast cancer', 'normal'],
                'fields': ['name', 'identifier', 'definition', 'synonyms', 'xrefs'],
                'sdrf_column': 'disease'
            },
            'uberon_anatomy': {
                'description': 'Comprehensive anatomy from UBERON for characteristics[organism part]',
                'examples': ['liver', 'brain', 'kidney', 'heart', 'blood plasma', 'muscle tissue'],
                'fields': ['name', 'identifier', 'definition', 'synonyms', 'part_of'],
                'sdrf_column': 'organism part'
            },
            'ncbi_taxonomy': {
                'description': 'Complete NCBI taxonomy for characteristics[organism]',
                'examples': ['Homo sapiens', 'Mus musculus', 'Rattus norvegicus', 'Escherichia coli'],
                'fields': ['scientific_name', 'common_name', 'tax_id', 'rank', 'synonyms'],
                'sdrf_column': 'organism'
            },
            'chebi_compound': {
                'description': 'Chemical compounds from ChEBI for reagents and chemicals',
                'examples': ['formic acid', 'acetonitrile', 'trypsin', 'DTT', 'iodoacetamide'],
                'fields': ['name', 'identifier', 'definition', 'formula', 'synonyms'],
                'sdrf_column': 'varies'
            },
            'psims_ontology': {
                'description': 'PSI-MS ontology for mass spectrometry instruments and methods',
                'examples': ['LTQ Orbitrap XL', 'Q Exactive HF', 'collision-induced dissociation', 'HCD'],
                'fields': ['name', 'identifier', 'definition', 'category', 'synonyms'],
                'sdrf_column': 'varies'
            },
            'ms_vocabularies': {
                'description': 'Mass spectrometry instruments, methods, and reagents from PSI-MS',
                'examples': ['LTQ Orbitrap XL', 'Q Exactive', 'trypsin', 'DTT', 'iodoacetamide', 'HCD', 'CID'],
                'fields': ['name', 'accession', 'term_type'],
                'sdrf_column': 'varies by term_type'
            },
            'unimod': {
                'description': 'Protein modifications from UniMod database for comment[modification parameters]',
                'examples': ['Oxidation', 'Acetyl', 'Phospho', 'Deamidated', 'Carbamidomethyl', 'TMT6plex'],
                'fields': ['name', 'accession'],
                'sdrf_column': 'modification parameters'
            }
        }
        
        # Additional SDRF-specific context
        self.sdrf_context = {
            'required_characteristics': [
                'organism', 'disease', 'organism part', 'cell type'
            ],
            'optional_characteristics': [
                'subcellular localization', 'enrichment process', 'biological replicate'
            ],
            'required_comments': [
                'instrument', 'label', 'fraction identifier', 'data file'
            ],
            'label_types': [
                'label free sample', 'TMT126', 'TMT127', 'TMT127C', 'TMT127N', 
                'TMT128', 'TMT128C', 'TMT128N', 'TMT129', 'TMT129C', 'TMT129N',
                'TMT130', 'TMT130C', 'TMT130N', 'TMT131'
            ],
            'modification_format': 'NT=Name;AC=Accession;MT=Type;PP=Position;TA=Target_AA',
            'cleavage_format': 'NT=Name;AC=Accession;CS=Cleavage_Site'
        }
    
    async def analyze_protocol_step_enhanced(self, step_text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Analyze protocol step using Claude with enhanced understanding.
        
        Args:
            step_text: Protocol step description
            context: Optional context (protocol title, previous steps, etc.)
            
        Returns:
            Enhanced analysis results with Claude insights
        """
        if not step_text.strip():
            return {
                'success': False,
                'error': 'Empty step text provided'
            }
        
        try:
            # Prepare Claude prompt
            prompt = self._build_analysis_prompt(step_text, context)
            print(f"DEBUG: Claude prompt length: {len(prompt)}")
            
            # Call Claude API
            claude_response = await self._call_claude_api(prompt)
            print(f"DEBUG: Claude API response received")
            
            # Parse Claude's response
            analysis_result = self._parse_claude_response(claude_response, step_text)
            print(f"DEBUG: Parsed Claude response, extracted_terms: {len(analysis_result.get('extracted_terms', []))}")
            
            # Enhance with ontology matching
            enhanced_result = await self._enhance_with_ontology_matching(analysis_result)
            print(f"DEBUG: Enhanced with ontology matching, enhanced_terms: {len(enhanced_result.get('enhanced_terms', []))}")
            
            return {
                'success': True,
                'step_text': step_text,
                'claude_analysis': analysis_result,
                'enhanced_terms': enhanced_result['enhanced_terms'],
                'sdrf_suggestions': enhanced_result['sdrf_suggestions'],
                'biological_insights': analysis_result.get('biological_insights', {}),
                'analysis_metadata': {
                    'analyzer_type': 'anthropic_claude',
                    'model': self.model,
                    'timestamp': datetime.now().isoformat(),
                    'total_terms_found': len(enhanced_result['enhanced_terms']),
                    'ontology_matches': enhanced_result['ontology_match_count']
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Claude analysis failed: {str(e)}',
                'step_text': step_text
            }
    
    def _build_analysis_prompt(self, step_text: str, context: Optional[Dict] = None) -> str:
        """Build the prompt for Claude analysis."""
        
        # Build comprehensive SDRF ontology information for Claude
        ontology_info = ""
        for ont_name, ont_data in self.ontology_context.items():
            ontology_info += f"\n- {ont_name}: {ont_data['description']}\n"
            ontology_info += f"  SDRF Column: {ont_data['sdrf_column']}\n"
            ontology_info += f"  Examples: {', '.join(ont_data['examples'])}\n"
        
        # Add SDRF-specific context
        sdrf_info = f"""
SDRF-Proteomics Specification Context:
- Required characteristics: {', '.join(self.sdrf_context['required_characteristics'])}
- Required comments: {', '.join(self.sdrf_context['required_comments'])}
- Label types: {', '.join(self.sdrf_context['label_types'][:10])}... (and more TMT variants)
- Modification format: {self.sdrf_context['modification_format']}
- Cleavage agent format: {self.sdrf_context['cleavage_format']}
"""
        
        context_info = ""
        if context:
            if context.get('protocol_title'):
                context_info += f"Protocol: {context['protocol_title']}\n"
            if context.get('previous_steps'):
                context_info += f"Previous steps: {context['previous_steps']}\n"
            if context.get('section_name'):
                context_info += f"Section: {context['section_name']}\n"
        
        prompt = f"""
You are an SDRF-Proteomics metadata annotation specialist. Your ONLY job is to analyze protocol steps and suggest SDRF-compliant metadata values that can be found in the available ontology databases.

CRITICAL: You must ONLY recommend terms that exist in the provided ontology databases. Do NOT suggest general biological insights or interpretations outside of SDRF metadata scope.

{context_info}

Protocol Step to Analyze:
"{step_text}"

Available Ontology Databases (ONLY suggest terms from these):
{ontology_info}

{sdrf_info}

Your task is to extract ONLY terms that can be mapped to SDRF metadata columns using the available ontologies. Focus on identifying specific entities mentioned in the text that have corresponding entries in the ontology databases.

Return JSON in this exact format:

{{
    "extracted_terms": [
        {{
            "text": "exact term from protocol text",
            "term_type": "organism|tissue|disease|instrument|chemical|modification|cellular_component",
            "confidence": 0.0-1.0,
            "suggested_ontology": "which ontology database to search",
            "sdrf_column": "exact SDRF column name"
        }}
    ],
    "sdrf_relevance": {{
        "organism": ["specific organism/species names found in text"],
        "organism part": ["specific tissues/organs/body parts found in text"],
        "disease": ["specific diseases/conditions found in text"],
        "cell type": ["specific cell lines/cell types found in text"],
        "subcellular localization": ["specific cellular components found in text"],
        "instrument": ["specific instrument models found in text"],
        "modification parameters": ["specific protein modifications found in text"],
        "cleavage agent details": ["specific enzymes/proteases found in text"],
        "label": ["specific labeling methods found in text"],
        "reduction reagent": ["specific reduction chemicals found in text"],
        "alkylation reagent": ["specific alkylation chemicals found in text"]
    }}
}}

RULES:
1. ONLY extract terms explicitly mentioned in the protocol text
2. ONLY suggest terms that exist in the provided ontology databases
3. Do NOT provide biological interpretations or insights
4. Do NOT suggest demographic data unless explicitly mentioned
5. Be conservative - if unsure whether a term exists in ontologies, exclude it
6. Focus on concrete entities: specific chemicals, instruments, cell lines, organisms
7. Exclude general procedural terms unless they map to specific ontology entries

Be precise and conservative. Only assign high confidence (>0.8) to terms explicitly mentioned and certain to exist in ontologies.
"""
        return prompt
    
    async def _call_claude_api(self, prompt: str) -> Dict[str, Any]:
        """Call the Claude API with the analysis prompt."""
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01'
        }
        
        payload = {
            'model': self.model,
            'max_tokens': 4000,
            'messages': [
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            'temperature': 0.1  # Low temperature for consistent analysis
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.base_url, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Claude API error {response.status}: {error_text}")
                
                response_data = await response.json()
                return response_data
    
    def _parse_claude_response(self, claude_response: Dict[str, Any], original_text: str) -> Dict[str, Any]:
        """Parse Claude's response into structured data."""
        try:
            # Extract the content from Claude's response
            content = claude_response['content'][0]['text']
            
            # Parse JSON from Claude's response
            # Claude sometimes wraps JSON in markdown, so we need to extract it
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON found in Claude's response")
            
            json_content = content[json_start:json_end]
            parsed_analysis = json.loads(json_content)
            
            # Convert to our ExtractedTerm format with Claude enhancements
            claude_terms = []
            for term_data in parsed_analysis.get('extracted_terms', []):
                # Map term type
                term_type_mapping = {
                    'organism': TermType.ORGANISM,
                    'tissue': TermType.TISSUE,
                    'disease': TermType.DISEASE,
                    'instrument': TermType.INSTRUMENT,
                    'chemical': TermType.CHEMICAL,
                    'modification': TermType.MODIFICATION,
                    'procedure': TermType.PROCEDURE,
                    'cellular_component': TermType.CELLULAR_COMPONENT
                }
                
                term_type = term_type_mapping.get(term_data.get('term_type'), TermType.PROCEDURE)
                
                # Find position in text (approximate)
                term_text = term_data.get('text', '')
                start_pos = original_text.lower().find(term_text.lower())
                end_pos = start_pos + len(term_text) if start_pos != -1 else 0
                
                claude_term = ClaudeExtractedTerm(
                    text=term_text,
                    term_type=term_type,
                    context='',
                    confidence=float(term_data.get('confidence', 0.5)),
                    start_pos=max(0, start_pos),
                    end_pos=max(0, end_pos),
                    claude_reasoning='',
                    suggested_ontology=term_data.get('suggested_ontology'),
                    biological_context=''
                )
                claude_terms.append(claude_term)
            
            return {
                'extracted_terms': claude_terms,
                'sdrf_relevance': parsed_analysis.get('sdrf_relevance', {}),
                'raw_claude_response': content
            }
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse Claude's JSON response: {e}")
        except Exception as e:
            raise ValueError(f"Failed to process Claude's response: {e}")
    
    async def _enhance_with_ontology_matching(self, claude_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance Claude's analysis with database ontology matching."""
        from .term_matcher import OntologyTermMatcher
        
        matcher = OntologyTermMatcher()
        enhanced_terms = []
        ontology_match_count = 0
        sdrf_suggestions = {}
        
        for claude_term in claude_analysis['extracted_terms']:
            # Use Claude's suggested ontology or map term type to ontologies
            ontology_types = self._map_term_to_ontologies(claude_term)
            
            # Match against database
            matches = matcher.match_terms(
                [claude_term.text], 
                ontology_types, 
                min_confidence=0.4  # Lower threshold since Claude pre-filtered
            )
            
            # Enhance the term with database matches
            enhanced_term = {
                'claude_term': {
                    'text': claude_term.text,
                    'term_type': claude_term.term_type.value,
                    'confidence': claude_term.confidence,
                    'reasoning': claude_term.claude_reasoning,
                    'biological_context': claude_term.biological_context,
                    'suggested_ontology': claude_term.suggested_ontology
                },
                'ontology_matches': []
            }
            
            # Add ontology matches with rich metadata
            for match in matches:
                match_data = {
                    'ontology_type': match.ontology_type,
                    'ontology_id': match.ontology_id,
                    'ontology_name': match.ontology_name,
                    'accession': match.accession,
                    'confidence': match.confidence,
                    'match_type': match.match_type,
                    'combined_confidence': (claude_term.confidence + match.confidence) / 2
                }
                
                # Add rich metadata fields if available
                if match.definition:
                    match_data['definition'] = match.definition
                if match.synonyms:
                    match_data['synonyms'] = match.synonyms
                if match.xrefs:
                    match_data['xrefs'] = match.xrefs
                if match.parent_terms:
                    match_data['parent_terms'] = match.parent_terms
                    
                # Add UniMod-specific fields
                if match.chemical_formula:
                    match_data['chemical_formula'] = match.chemical_formula
                if match.mass_info:
                    match_data['monoisotopic_mass'] = match.mass_info
                if match.target_info:
                    match_data['target_aa'] = match.target_info
                    
                # Add additional metadata for complete UniMod info
                if match.additional_metadata:
                    if match.additional_metadata.get('target_aa'):
                        match_data['target_aa'] = match.additional_metadata['target_aa']
                    if match.additional_metadata.get('modification_type'):
                        match_data['modification_type'] = match.additional_metadata['modification_type']
                    if match.additional_metadata.get('position'):
                        match_data['position'] = match.additional_metadata['position']
                
                enhanced_term['ontology_matches'].append(match_data)
                ontology_match_count += 1
            
            enhanced_terms.append(enhanced_term)
            
            # Generate SDRF suggestions with rich metadata
            if enhanced_term['ontology_matches']:
                sdrf_column = self._map_to_sdrf_column(claude_term.term_type, claude_term.suggested_ontology)
                if sdrf_column:
                    if sdrf_column not in sdrf_suggestions:
                        sdrf_suggestions[sdrf_column] = []
                    
                    # Add best match for this term with enhanced formatting
                    best_match = max(enhanced_term['ontology_matches'], 
                                   key=lambda x: x['combined_confidence'])
                    
                    # Format UniMod suggestions with key-value format like standard analysis
                    if sdrf_column == 'modification parameters' and best_match.get('ontology_type') == 'unimod':
                        # Create key-value format for UniMod as expected by frontend
                        key_value_format = {
                            'NT': best_match.get('ontology_name', ''),  # Name
                            'AC': best_match.get('accession', '')       # Accession
                        }
                        
                        # Add rich metadata if available
                        if best_match.get('target_aa'):
                            key_value_format['TA'] = best_match['target_aa']
                        if best_match.get('modification_type'):
                            key_value_format['MT'] = best_match['modification_type']
                        if best_match.get('position'):
                            key_value_format['PP'] = best_match['position']
                        if best_match.get('monoisotopic_mass'):
                            key_value_format['MM'] = best_match['monoisotopic_mass']
                        
                        # Create enhanced suggestion with key-value format
                        enhanced_suggestion = {
                            **best_match,
                            'key_value_format': key_value_format,
                            'source': 'claude_enhanced_analysis',
                            'ontology_source': 'enhanced',
                            # Include rich metadata for display
                            'target_aa': key_value_format.get('TA'),
                            'monoisotopic_mass': key_value_format.get('MM'),
                            'modification_type': key_value_format.get('MT'),
                            'position': key_value_format.get('PP'),
                            'extracted_term': claude_term.text
                        }
                        sdrf_suggestions[sdrf_column].append(enhanced_suggestion)
                    else:
                        # For non-UniMod suggestions, add rich metadata directly
                        enhanced_suggestion = {
                            **best_match,
                            'source': 'claude_enhanced_analysis',
                            'ontology_source': 'enhanced',
                            'extracted_term': claude_term.text
                        }
                        sdrf_suggestions[sdrf_column].append(enhanced_suggestion)
        
        # Use Claude's SDRF relevance to enhance suggestions
        claude_sdrf = claude_analysis.get('sdrf_relevance', {})
        for sdrf_column, terms in claude_sdrf.items():
            if sdrf_column not in sdrf_suggestions:
                sdrf_suggestions[sdrf_column] = []
            
            # Add Claude's suggestions even if not matched to ontology
            for term in terms:
                claude_suggestion = {
                    'ontology_type': sdrf_column,
                    'ontology_id': f'claude_{sdrf_column}_{len(sdrf_suggestions[sdrf_column])}',
                    'ontology_name': term,
                    'accession': '',
                    'confidence': 0.7,  # Claude's suggestions get moderate confidence
                    'extracted_term': term,
                    'match_type': 'claude_suggestion',
                    'source': 'claude_analysis',
                    'ontology_source': 'enhanced'
                }
                sdrf_suggestions[sdrf_column].append(claude_suggestion)
        
        return {
            'enhanced_terms': enhanced_terms,
            'sdrf_suggestions': sdrf_suggestions,
            'ontology_match_count': ontology_match_count
        }
    
    def _map_term_to_ontologies(self, claude_term: ClaudeExtractedTerm) -> List[str]:
        """Map Claude's term type and suggestions to ontology databases."""
        # If Claude suggested a specific ontology, use it
        if claude_term.suggested_ontology:
            suggested = claude_term.suggested_ontology.lower()
            for ont_name in self.ontology_models.keys():
                if ont_name in suggested or suggested in ont_name:
                    return [ont_name]
        
        # Map term types to ontologies
        type_mapping = {
            TermType.ORGANISM: ['species'],
            TermType.TISSUE: ['tissue'],
            TermType.DISEASE: ['human_disease'],
            TermType.CELLULAR_COMPONENT: ['subcellular_location'],
            TermType.MODIFICATION: ['unimod'],
            TermType.INSTRUMENT: ['ms_vocabularies'],
            TermType.CHEMICAL: ['ms_vocabularies']
        }
        
        return type_mapping.get(claude_term.term_type, ['ms_vocabularies'])
    
    def _map_to_sdrf_column(self, term_type: TermType, suggested_ontology: Optional[str]) -> Optional[str]:
        """Map term type to SDRF column name."""
        mapping = {
            TermType.ORGANISM: 'organism',
            TermType.TISSUE: 'organism part',
            TermType.DISEASE: 'disease',
            TermType.CELLULAR_COMPONENT: 'subcellular localization',
            TermType.MODIFICATION: 'modification parameters',
            TermType.INSTRUMENT: 'instrument',
            TermType.CHEMICAL: 'cleavage agent details'  # Default for chemicals
        }
        
        return mapping.get(term_type)
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics for the Anthropic analyzer."""
        return {
            'analyzer_type': 'anthropic_claude',
            'model': self.model,
            'api_key_configured': bool(self.api_key),
            'available_ontologies': list(self.ontology_models.keys()),
            'supported_term_types': [t.value for t in TermType]
        }


# Sync wrapper for Django views
class SyncAnthropicAnalyzer:
    """Synchronous wrapper for AnthropicProtocolAnalyzer."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.async_analyzer = AnthropicProtocolAnalyzer(api_key)
    
    def analyze_protocol_step_enhanced(self, step_text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """Synchronous version of enhanced analysis."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.async_analyzer.analyze_protocol_step_enhanced(step_text, context)
            )
        finally:
            loop.close()
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return self.async_analyzer.get_usage_stats()