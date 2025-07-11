"""
Term matching utilities for ontology term lookup and matching.

This module provides algorithms to match extracted terms from protocol steps
to ontology terms in the database with confidence scoring.
"""

from typing import List, Dict, Optional, Tuple, Set, Any
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from .django_setup import get_ontology_models


@dataclass
class MatchResult:
    """Represents a match between extracted term and ontology term."""
    ontology_type: str
    ontology_id: str
    ontology_name: str
    accession: str
    confidence: float
    match_type: str  # 'exact', 'partial', 'synonym', 'fuzzy'
    extracted_term: str
    # Optional rich metadata fields
    definition: Optional[str] = None
    synonyms: Optional[str] = None
    xrefs: Optional[str] = None
    parent_terms: Optional[str] = None
    # UniMod-specific fields
    chemical_formula: Optional[str] = None
    mass_info: Optional[str] = None
    target_info: Optional[str] = None
    # Enhanced ontology fields
    additional_metadata: Optional[Dict[str, Any]] = None


class OntologyTermMatcher:
    """
    Matches extracted terms to ontology terms with confidence scoring.
    """
    
    def __init__(self):
        """Initialize the matcher with ontology models."""
        self.ontology_models = get_ontology_models()
        self._setup_term_caches()
    
    def _setup_term_caches(self):
        """Setup term caches for efficient lookup."""
        self.term_caches = {}
        
        # Cache terms for each ontology type
        for ontology_name, model_class in self.ontology_models.items():
            self.term_caches[ontology_name] = self._build_term_cache(model_class, ontology_name)
    
    def _build_term_cache(self, model_class, ontology_name: str) -> Dict[str, List[dict]]:
        """
        Build a searchable cache of terms for an ontology model.
        
        Args:
            model_class: Django model class
            ontology_name: Name of the ontology
            
        Returns:
            Dict mapping normalized terms to ontology entries
        """
        cache = {}
        
        try:
            # Get all records from the ontology
            records = model_class.objects.all()
            
            for record in records:
                entry = self._extract_searchable_terms(record, ontology_name)
                
                # Add all searchable terms to cache
                for term in entry['searchable_terms']:
                    normalized_term = self._normalize_term(term)
                    if normalized_term not in cache:
                        cache[normalized_term] = []
                    cache[normalized_term].append(entry)
        
        except Exception as e:
            print(f"Error building cache for {ontology_name}: {e}")
            
        return cache
    
    def _extract_searchable_terms(self, record, ontology_name: str) -> dict:
        """
        Extract searchable terms from an ontology record.
        
        Args:
            record: Django model instance
            ontology_name: Name of the ontology
            
        Returns:
            Dict containing record info and searchable terms
        """
        entry = {
            'id': str(record.pk),
            'searchable_terms': [],
            'ontology_type': ontology_name
        }
        
        if ontology_name == 'species':
            entry.update({
                'name': getattr(record, 'official_name', ''),
                'accession': str(getattr(record, 'taxon', '')),
                'common_name': getattr(record, 'common_name', ''),
                'code': getattr(record, 'code', '')
            })
            # Add searchable terms
            terms = [
                getattr(record, 'official_name', ''),
                getattr(record, 'common_name', ''),
                getattr(record, 'synonym', '')
            ]
            entry['searchable_terms'] = [t for t in terms if t]
            
        elif ontology_name == 'tissue':
            entry.update({
                'name': getattr(record, 'identifier', ''),
                'accession': getattr(record, 'accession', '')
            })
            # Add searchable terms
            terms = [getattr(record, 'identifier', '')]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
            
        elif ontology_name == 'human_disease':
            entry.update({
                'name': getattr(record, 'identifier', ''),
                'accession': getattr(record, 'accession', ''),
                'acronym': getattr(record, 'acronym', '')
            })
            # Add searchable terms
            terms = [
                getattr(record, 'identifier', ''),
                getattr(record, 'acronym', '')
            ]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
            
        elif ontology_name == 'subcellular_location':
            entry.update({
                'name': getattr(record, 'location_identifier', ''),
                'accession': getattr(record, 'accession', '')
            })
            # Add searchable terms
            terms = [getattr(record, 'location_identifier', '')]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
            
        elif ontology_name == 'ms_vocabularies':
            entry.update({
                'name': getattr(record, 'name', ''),
                'accession': getattr(record, 'accession', ''),
                'term_type': getattr(record, 'term_type', '')
            })
            # Add searchable terms
            entry['searchable_terms'] = [getattr(record, 'name', '')]
            
        elif ontology_name == 'unimod':
            # Extract rich metadata from UniMod in the format frontend expects
            additional_data = getattr(record, 'additional_data', [])
            definition = getattr(record, 'definition', '')
            
            # Parse additional metadata from xrefs and definition
            entry.update({
                'name': getattr(record, 'name', ''),
                'accession': getattr(record, 'accession', ''),
                'definition': definition,
                'additional_data': additional_data
            })
            
            # Extract frontend-compatible metadata
            delta_mono_mass = None
            target_aa = None
            modification_type = None
            position_info = None
            
            # Process additional_data to extract structured information
            if additional_data:
                for xref in additional_data:
                    if isinstance(xref, dict):
                        xref_id = xref.get('id', '').lower()
                        desc = xref.get('description', '')
                        
                        # Extract delta monoisotopic mass
                        if xref_id == 'delta_mono_mass':
                            try:
                                delta_mono_mass = float(desc)
                                entry['monoisotopic_mass'] = desc  # For SDRF display
                            except:
                                pass
                        
                        # Extract amino acid and position info from spec_ entries
                        elif xref_id.startswith('spec_'):
                            if 'amino_acid' in xref_id or 'residues' in xref_id:
                                target_aa = desc
                            elif 'position' in xref_id:
                                position_info = desc
                            elif 'classification' in xref_id:
                                modification_type = desc.split(',')[0] if desc else None
            
            # Add structured fields for SDRF format
            entry.update({
                'target_aa': target_aa,
                'modification_type': modification_type, 
                'position': position_info,
                'chemical_formula': definition  # Chemical formula from definition
            })
            
            # Add searchable terms
            entry['searchable_terms'] = [getattr(record, 'name', '')]
            
        elif ontology_name == 'cell_type':
            entry.update({
                'name': getattr(record, 'name', ''),
                'identifier': getattr(record, 'identifier', ''),
                'cell_line': getattr(record, 'cell_line', False),
                'organism': getattr(record, 'organism', ''),
                'accession': getattr(record, 'accession', '')
            })
            # Add searchable terms
            terms = [
                getattr(record, 'name', ''),
                getattr(record, 'identifier', '')
            ]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
            
        elif ontology_name == 'mondo_disease':
            entry.update({
                'name': getattr(record, 'name', ''),
                'identifier': getattr(record, 'identifier', ''),
                'definition': getattr(record, 'definition', ''),
                'accession': getattr(record, 'identifier', '')  # Use identifier as accession
            })
            # Add searchable terms
            terms = [getattr(record, 'name', '')]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
            
        elif ontology_name == 'uberon_anatomy':
            entry.update({
                'name': getattr(record, 'name', ''),
                'identifier': getattr(record, 'identifier', ''),
                'definition': getattr(record, 'definition', ''),
                'accession': getattr(record, 'identifier', '')
            })
            # Add searchable terms
            terms = [getattr(record, 'name', '')]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
            
        elif ontology_name == 'ncbi_taxonomy':
            entry.update({
                'name': getattr(record, 'scientific_name', ''),
                'common_name': getattr(record, 'common_name', ''),
                'tax_id': getattr(record, 'tax_id', ''),
                'rank': getattr(record, 'rank', ''),
                'accession': str(getattr(record, 'tax_id', ''))
            })
            # Add searchable terms
            terms = [
                getattr(record, 'scientific_name', ''),
                getattr(record, 'common_name', '')
            ]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
            
        elif ontology_name == 'chebi_compound':
            entry.update({
                'name': getattr(record, 'name', ''),
                'identifier': getattr(record, 'identifier', ''),
                'definition': getattr(record, 'definition', ''),
                'formula': getattr(record, 'formula', ''),
                'accession': getattr(record, 'identifier', '')
            })
            # Add searchable terms
            terms = [getattr(record, 'name', '')]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
            
        elif ontology_name == 'psims_ontology':
            entry.update({
                'name': getattr(record, 'name', ''),
                'identifier': getattr(record, 'identifier', ''),
                'definition': getattr(record, 'definition', ''),
                'category': getattr(record, 'category', ''),
                'accession': getattr(record, 'identifier', '')
            })
            # Add searchable terms
            terms = [getattr(record, 'name', '')]
            synonyms = getattr(record, 'synonyms', '')
            if synonyms:
                terms.extend(synonyms.split(';'))
            entry['searchable_terms'] = [t.strip() for t in terms if t.strip()]
        
        return entry
    
    def _normalize_term(self, term: str) -> str:
        """Normalize term for consistent matching."""
        if not term:
            return ""
        # Convert to lowercase, remove extra spaces, remove special characters
        normalized = re.sub(r'[^\w\s]', ' ', term.lower())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    def match_terms(self, extracted_terms: List[str], 
                   ontology_types: Optional[List[str]] = None,
                   min_confidence: float = 0.5) -> List[MatchResult]:
        """
        Match extracted terms to ontology terms.
        
        Args:
            extracted_terms: List of terms extracted from protocol steps
            ontology_types: List of ontology types to search (None for all)
            min_confidence: Minimum confidence threshold for matches
            
        Returns:
            List of MatchResult objects
        """
        if ontology_types is None:
            ontology_types = list(self.ontology_models.keys())
        
        all_matches = []
        
        for term in extracted_terms:
            matches = self._match_single_term(term, ontology_types, min_confidence)
            all_matches.extend(matches)
        
        # Sort by confidence and remove low-confidence duplicates
        all_matches.sort(key=lambda x: x.confidence, reverse=True)
        return self._deduplicate_matches(all_matches, min_confidence)
    
    def _match_single_term(self, term: str, ontology_types: List[str], 
                          min_confidence: float) -> List[MatchResult]:
        """
        Match a single term against specified ontologies.
        
        Args:
            term: Term to match
            ontology_types: List of ontology types to search
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of MatchResult objects
        """
        matches = []
        normalized_term = self._normalize_term(term)
        
        for ontology_type in ontology_types:
            if ontology_type not in self.term_caches:
                continue
                
            cache = self.term_caches[ontology_type]
            
            # 1. Exact match
            if normalized_term in cache:
                for entry in cache[normalized_term]:
                    matches.append(MatchResult(
                        ontology_type=ontology_type,
                        ontology_id=entry['id'],
                        ontology_name=entry['name'],
                        accession=entry.get('accession', ''),
                        confidence=1.0,
                        match_type='exact',
                        extracted_term=term,
                        # Rich metadata fields
                        definition=entry.get('definition'),
                        synonyms=entry.get('synonyms'),
                        xrefs=entry.get('xrefs'),
                        parent_terms=entry.get('parent_terms'),
                        # UniMod-specific fields
                        chemical_formula=entry.get('chemical_formula'),
                        mass_info=entry.get('monoisotopic_mass'),
                        target_info=entry.get('target_aa'),
                        # Store full additional metadata for frontend processing
                        additional_metadata={
                            'target_aa': entry.get('target_aa'),
                            'modification_type': entry.get('modification_type'),
                            'position': entry.get('position'),
                            'additional_data': entry.get('additional_data')
                        } if ontology_type == 'unimod' else None
                    ))
            
            # 2. Partial and fuzzy matches
            else:
                partial_matches = self._find_partial_matches(
                    normalized_term, cache, term, ontology_type, min_confidence
                )
                matches.extend(partial_matches)
        
        return matches
    
    def _find_partial_matches(self, normalized_term: str, cache: Dict, 
                            original_term: str, ontology_type: str,
                            min_confidence: float) -> List[MatchResult]:
        """
        Find partial and fuzzy matches for a term.
        
        Args:
            normalized_term: Normalized term to match
            cache: Term cache for the ontology
            original_term: Original extracted term
            ontology_type: Ontology type being searched
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of MatchResult objects
        """
        matches = []
        
        for cached_term, entries in cache.items():
            # Skip if terms are too different in length
            if abs(len(normalized_term) - len(cached_term)) > max(len(normalized_term), len(cached_term)) * 0.5:
                continue
            
            # Calculate similarity
            similarity = SequenceMatcher(None, normalized_term, cached_term).ratio()
            
            if similarity >= min_confidence:
                match_type = 'partial' if similarity >= 0.8 else 'fuzzy'
                
                for entry in entries:
                    matches.append(MatchResult(
                        ontology_type=ontology_type,
                        ontology_id=entry['id'],
                        ontology_name=entry['name'],
                        accession=entry.get('accession', ''),
                        confidence=similarity,
                        match_type=match_type,
                        extracted_term=original_term,
                        # Rich metadata fields
                        definition=entry.get('definition'),
                        synonyms=entry.get('synonyms'),
                        xrefs=entry.get('xrefs'),
                        parent_terms=entry.get('parent_terms'),
                        # UniMod-specific fields
                        chemical_formula=entry.get('chemical_formula'),
                        mass_info=entry.get('monoisotopic_mass'),
                        target_info=entry.get('target_aa'),
                        # Store full additional metadata for frontend processing
                        additional_metadata={
                            'target_aa': entry.get('target_aa'),
                            'modification_type': entry.get('modification_type'),
                            'position': entry.get('position'),
                            'additional_data': entry.get('additional_data')
                        } if ontology_type == 'unimod' else None
                    ))
        
        return matches
    
    def _deduplicate_matches(self, matches: List[MatchResult], 
                           min_confidence: float) -> List[MatchResult]:
        """
        Remove duplicate matches and apply confidence filtering.
        
        Args:
            matches: List of MatchResult objects
            min_confidence: Minimum confidence threshold
            
        Returns:
            Deduplicated list of MatchResult objects
        """
        # Filter by confidence
        filtered_matches = [m for m in matches if m.confidence >= min_confidence]
        
        # Remove duplicates based on ontology_type + ontology_id + extracted_term
        seen = set()
        deduplicated = []
        
        for match in filtered_matches:
            key = (match.ontology_type, match.ontology_id, match.extracted_term)
            if key not in seen:
                seen.add(key)
                deduplicated.append(match)
        
        return deduplicated
    
    def match_by_ontology_type(self, term: str, ontology_type: str, 
                              min_confidence: float = 0.5) -> List[MatchResult]:
        """
        Match a term against a specific ontology type.
        
        Args:
            term: Term to match
            ontology_type: Specific ontology type to search
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of MatchResult objects
        """
        return self._match_single_term(term, [ontology_type], min_confidence)
    
    def get_best_match(self, term: str, ontology_type: str) -> Optional[MatchResult]:
        """
        Get the best match for a term in a specific ontology.
        
        Args:
            term: Term to match
            ontology_type: Ontology type to search
            
        Returns:
            Best MatchResult or None if no good match found
        """
        matches = self.match_by_ontology_type(term, ontology_type, min_confidence=0.5)
        return matches[0] if matches else None
    
    def search_by_term_type(self, term: str, ms_term_type: str) -> List[MatchResult]:
        """
        Search MS vocabularies by specific term type.
        
        Args:
            term: Term to search for
            ms_term_type: MS term type (e.g., 'instrument', 'cleavage agent')
            
        Returns:
            List of MatchResult objects
        """
        if 'ms_vocabularies' not in self.term_caches:
            return []
        
        matches = []
        normalized_term = self._normalize_term(term)
        
        # Search through MS vocabulary cache
        for cached_term, entries in self.term_caches['ms_vocabularies'].items():
            for entry in entries:
                if entry.get('term_type') == ms_term_type:
                    similarity = SequenceMatcher(None, normalized_term, cached_term).ratio()
                    
                    if similarity >= 0.5:
                        match_type = 'exact' if similarity >= 0.95 else 'partial'
                        matches.append(MatchResult(
                            ontology_type='ms_vocabularies',
                            ontology_id=entry['id'],
                            ontology_name=entry['name'],
                            accession=entry['accession'],
                            confidence=similarity,
                            match_type=match_type,
                            extracted_term=term
                        ))
        
        return sorted(matches, key=lambda x: x.confidence, reverse=True)
    
    def get_sdrf_label_suggestions(self, text: str) -> List[str]:
        """
        Get SDRF-compliant label suggestions based on text analysis.
        
        Args:
            text: Protocol step text to analyze
            
        Returns:
            List of suggested SDRF label values
        """
        text_lower = text.lower()
        suggested_labels = []
        
        # Label-free detection
        if any(term in text_lower for term in ['label free', 'label-free', 'lf', 'unlabeled']):
            suggested_labels.append('label free sample')
        
        # TMT detection
        tmt_patterns = [
            'tmt126', 'tmt127', 'tmt127c', 'tmt127n', 'tmt128', 'tmt128c', 'tmt128n',
            'tmt129', 'tmt129c', 'tmt129n', 'tmt130', 'tmt130c', 'tmt130n', 'tmt131'
        ]
        for pattern in tmt_patterns:
            if pattern.replace('tmt', 'tmt ') in text_lower or pattern in text_lower:
                suggested_labels.append(pattern.upper())
        
        # SILAC detection
        if any(term in text_lower for term in ['silac', 'heavy', 'light', 'medium']):
            if 'heavy' in text_lower:
                suggested_labels.append('SILAC heavy')
            elif 'light' in text_lower:
                suggested_labels.append('SILAC light')
            elif 'medium' in text_lower:
                suggested_labels.append('SILAC medium')
            else:
                suggested_labels.append('SILAC')
        
        # iTRAQ detection
        if 'itraq' in text_lower:
            suggested_labels.append('iTRAQ')
        
        return list(set(suggested_labels))  # Remove duplicates
    
    def get_sdrf_modification_suggestions(self, text: str) -> List[Dict[str, Any]]:
        """
        Get SDRF-compliant modification parameter suggestions with detailed UniMod specs.
        
        Args:
            text: Protocol step text to analyze
            
        Returns:
            List of modification dictionaries with SDRF key-value format and detailed specs
        """
        text_lower = text.lower()
        modifications = []
        
        # Enhanced modifications with detailed UniMod specifications
        if 'phospho' in text_lower or 'phosphoryl' in text_lower:
            modifications.extend(self._get_phospho_specifications())
        
        if 'oxidation' in text_lower or 'oxidized' in text_lower:
            modifications.extend(self._get_oxidation_specifications())
            
        if 'carbamidomethyl' in text_lower or 'iaa' in text_lower or 'iodoacetamide' in text_lower:
            modifications.extend(self._get_carbamidomethyl_specifications())
            
        if 'acetyl' in text_lower or 'acetylation' in text_lower:
            modifications.extend(self._get_acetyl_specifications())
            
        if 'deamidated' in text_lower or 'deamidation' in text_lower:
            modifications.extend(self._get_deamidated_specifications())
            
        if any(term in text_lower for term in ['tmt', 'tandem mass tag']):
            modifications.extend(self._get_tmt_specifications())
        
        return modifications
    
    def _get_phospho_specifications(self) -> List[Dict[str, Any]]:
        """Get detailed phosphorylation specifications with grouped amino acids."""
        try:
            from cc.models import Unimod
            phospho = Unimod.objects.filter(name='Phospho').first()
            if phospho and phospho.additional_data:
                return self._extract_unimod_specs_grouped(phospho, 'Phospho', 'Variable')
                    
        except Exception as e:
            print(f"Error getting phospho specifications: {e}")
        
        # Fallback to basic specification with grouped amino acids
        return [{'NT': 'Phospho', 'AC': 'UNIMOD:21', 'MT': 'Variable', 'TA': 'S,T,Y', 'MM': '79.966331'}]
    
    def _get_oxidation_specifications(self) -> List[Dict[str, Any]]:
        """Get detailed oxidation specifications."""
        try:
            from cc.models import Unimod
            oxidation = Unimod.objects.filter(name='Oxidation').first()
            if oxidation and oxidation.additional_data:
                return self._extract_unimod_specs(oxidation, 'Oxidation', 'Variable')
        except Exception:
            pass
            
        # Fallback
        return [{'NT': 'Oxidation', 'AC': 'UNIMOD:35', 'MT': 'Variable', 'TA': 'M', 'MM': '15.994915'}]
    
    def _get_carbamidomethyl_specifications(self) -> List[Dict[str, Any]]:
        """Get detailed carbamidomethyl specifications."""
        try:
            from cc.models import Unimod
            carb = Unimod.objects.filter(name='Carbamidomethyl').first()
            if carb and carb.additional_data:
                return self._extract_unimod_specs(carb, 'Carbamidomethyl', 'Fixed')
        except Exception:
            pass
            
        # Fallback
        return [{'NT': 'Carbamidomethyl', 'AC': 'UNIMOD:4', 'MT': 'Fixed', 'TA': 'C', 'MM': '57.021464'}]
    
    def _get_acetyl_specifications(self) -> List[Dict[str, Any]]:
        """Get detailed acetyl specifications."""
        try:
            from cc.models import Unimod
            acetyl = Unimod.objects.filter(name='Acetyl').first()
            if acetyl and acetyl.additional_data:
                return self._extract_unimod_specs(acetyl, 'Acetyl', 'Variable')
        except Exception:
            pass
            
        # Fallback
        return [{'NT': 'Acetyl', 'AC': 'UNIMOD:1', 'MT': 'Variable', 'PP': 'Protein N-term', 'TA': 'Any', 'MM': '42.010565'}]
    
    def _get_deamidated_specifications(self) -> List[Dict[str, Any]]:
        """Get detailed deamidated specifications."""
        try:
            from cc.models import Unimod
            deamidated = Unimod.objects.filter(name='Deamidated').first()
            if deamidated and deamidated.additional_data:
                return self._extract_unimod_specs(deamidated, 'Deamidated', 'Variable')
        except Exception:
            pass
            
        # Fallback
        return [
            {'NT': 'Deamidated', 'AC': 'UNIMOD:7', 'MT': 'Variable', 'TA': 'N', 'MM': '0.984016'},
            {'NT': 'Deamidated', 'AC': 'UNIMOD:7', 'MT': 'Variable', 'TA': 'Q', 'MM': '0.984016'}
        ]
    
    def _get_tmt_specifications(self) -> List[Dict[str, Any]]:
        """Get detailed TMT specifications."""
        tmt_variants = [
            {'name': 'TMT6plex', 'ac': 'UNIMOD:737', 'mm': '229.162932'},
            {'name': 'TMT10plex', 'ac': 'UNIMOD:737', 'mm': '229.162932'},
            {'name': 'TMT11plex', 'ac': 'UNIMOD:737', 'mm': '229.162932'}
        ]
        
        specs = []
        for tmt in tmt_variants:
            specs.append({
                'NT': tmt['name'],
                'AC': tmt['ac'],
                'MT': 'Fixed',
                'TA': 'K',
                'PP': 'Any N-term',
                'MM': tmt['mm']
            })
        
        return specs
    
    def _extract_unimod_specs(self, unimod_obj, name: str, mod_type: str) -> List[Dict[str, Any]]:
        """Extract amino acid specific specifications from UniMod additional_data."""
        specs = []
        aa_data = {}
        
        # Parse additional_data for amino acid specific information
        for data in unimod_obj.additional_data:
            if 'id' in data and 'description' in data:
                if data['id'].endswith('_aa'):
                    aa = data['id'].replace('_aa', '')
                    if aa not in aa_data:
                        aa_data[aa] = {}
                    aa_data[aa]['aa_code'] = data['description']
                elif data['id'].endswith('_mono_mass'):
                    aa = data['id'].replace('_mono_mass', '')
                    if aa not in aa_data:
                        aa_data[aa] = {}
                    aa_data[aa]['mono_mass'] = float(data['description'])
        
        # Create spec for each amino acid
        for aa_key, aa_info in aa_data.items():
            if 'aa_code' in aa_info and 'mono_mass' in aa_info:
                spec = {
                    'NT': name,
                    'AC': unimod_obj.accession,
                    'MT': mod_type,
                    'TA': aa_info['aa_code'],
                    'MM': str(aa_info['mono_mass']),
                    'unimod_specs': aa_info
                }
                specs.append(spec)
        
        return specs
    
    def _extract_unimod_specs_grouped(self, unimod_obj, name: str, mod_type: str) -> List[Dict[str, Any]]:
        """Extract amino acid specifications from UniMod additional_data, grouping amino acids with same specs."""
        aa_data = {}
        
        # Parse additional_data for amino acid specific information
        for data in unimod_obj.additional_data:
            if 'id' in data and 'description' in data:
                if data['id'].endswith('_aa'):
                    aa = data['id'].replace('_aa', '')
                    if aa not in aa_data:
                        aa_data[aa] = {}
                    aa_data[aa]['aa_code'] = data['description']
                elif data['id'].endswith('_mono_mass'):
                    aa = data['id'].replace('_mono_mass', '')
                    if aa not in aa_data:
                        aa_data[aa] = {}
                    aa_data[aa]['mono_mass'] = float(data['description'])
        
        # Group amino acids by their monoisotopic mass and other specs
        mass_groups = {}
        for aa_key, aa_info in aa_data.items():
            if 'aa_code' in aa_info and 'mono_mass' in aa_info:
                mass_key = str(aa_info['mono_mass'])
                if mass_key not in mass_groups:
                    mass_groups[mass_key] = {
                        'amino_acids': [],
                        'mono_mass': aa_info['mono_mass'],
                        'specs': aa_info
                    }
                mass_groups[mass_key]['amino_acids'].append(aa_info['aa_code'])
        
        # Create grouped specifications
        specs = []
        for mass_key, group_info in mass_groups.items():
            # Join amino acids with commas for same mass
            target_aa = ','.join(sorted(group_info['amino_acids']))
            
            spec = {
                'NT': name,
                'AC': unimod_obj.accession,
                'MT': mod_type,
                'TA': target_aa,
                'MM': str(group_info['mono_mass']),
                'unimod_specs': group_info['specs']
            }
            specs.append(spec)
        
        return specs
    
    def get_sdrf_cleavage_suggestions(self, text: str) -> List[Dict[str, str]]:
        """
        Get SDRF-compliant cleavage agent suggestions with key-value format.
        
        Args:
            text: Protocol step text to analyze
            
        Returns:
            List of cleavage agent dictionaries with SDRF key-value format
        """
        text_lower = text.lower()
        cleavage_agents = []
        
        # Common cleavage agents with SDRF format
        enzyme_mappings = {
            'trypsin': {'NT': 'Trypsin', 'AC': 'MS:1001251', 'CS': '(?<=[KR])(?!P)'},
            'chymotrypsin': {'NT': 'Chymotrypsin', 'AC': 'MS:1001306'},
            'pepsin': {'NT': 'Pepsin', 'AC': 'MS:1001313'},
            'lys-c': {'NT': 'Lys-C', 'AC': 'MS:1001309', 'CS': '(?<=K)(?!P)'},
            'arg-c': {'NT': 'Arg-C', 'AC': 'MS:1001303', 'CS': '(?<=R)(?!P)'}
        }
        
        for enzyme_name, enzyme_data in enzyme_mappings.items():
            if enzyme_name in text_lower or enzyme_name.replace('-', '') in text_lower:
                cleavage_agents.append(enzyme_data)
        
        return cleavage_agents
    
    def get_sdrf_cell_type_suggestions(self, text: str) -> List[str]:
        """
        Get SDRF-compliant cell type suggestions based on text analysis.
        Note: Since cell type is not in the database, this provides text-based suggestions.
        
        Args:
            text: Protocol step text to analyze
            
        Returns:
            List of suggested cell type values
        """
        text_lower = text.lower()
        cell_types = []
        
        # Common cell lines
        cell_line_patterns = {
            'hek293': 'HEK293',
            'hek 293': 'HEK293',
            'hela': 'HeLa',
            'mcf-7': 'MCF-7',
            'mcf7': 'MCF-7',
            'jurkat': 'Jurkat',
            'a549': 'A549',
            'u2os': 'U2OS',
            'cos-7': 'COS-7',
            'cos7': 'COS-7',
            'cho': 'CHO',
            'nih3t3': 'NIH3T3',
            'nih 3t3': 'NIH3T3'
        }
        
        for pattern, cell_type in cell_line_patterns.items():
            if pattern in text_lower:
                cell_types.append(cell_type)
        
        # General cell type terms
        cell_type_terms = {
            'epithelial': 'epithelial cell',
            'fibroblast': 'fibroblast',
            'macrophage': 'macrophage',
            'lymphocyte': 'lymphocyte',
            'neuron': 'neuron',
            'astrocyte': 'astrocyte',
            'hepatocyte': 'hepatocyte',
            'keratinocyte': 'keratinocyte',
            'endothelial': 'endothelial cell',
            'stem cell': 'stem cell',
            'cancer cell': 'cancer cell',
            'tumor cell': 'tumor cell'
        }
        
        for term, cell_type in cell_type_terms.items():
            if term in text_lower:
                cell_types.append(cell_type)
        
        # If no specific cell type found but we detect "cell" context
        if not cell_types and any(term in text_lower for term in ['cell', 'culture', 'cultured']):
            cell_types.append('not available')  # SDRF standard for unknown values
        
        return list(set(cell_types))  # Remove duplicates
    
    def get_sdrf_demographic_suggestions(self, text: str, column_type: str) -> List[Dict[str, Any]]:
        """
        Get SDRF-compliant demographic and experimental metadata suggestions.
        
        Args:
            text: Protocol step text to analyze
            column_type: Type of demographic data ('age', 'sex', 'biological_replicate', etc.)
            
        Returns:
            List of suggestion dictionaries
        """
        text_lower = text.lower()
        suggestions = []
        
        if column_type == 'age':
            # Age-related patterns following SDRF format: {X}Y{X}M{X}D
            age_patterns = [
                (r'\b(\d+)\s*year', lambda m: f'{m.group(1)}Y'),
                (r'\b(\d+)\s*-\s*(\d+)\s*year', lambda m: f'{m.group(1)}Y-{m.group(2)}Y'),
                (r'\b(\d+)\s*month', lambda m: f'{m.group(1)}M'),
                (r'\b(\d+)\s*week', lambda m: f'{m.group(1)}W'),
                (r'\b(\d+)\s*day', lambda m: f'{m.group(1)}D'),
                (r'\badult\b', lambda m: '25Y-65Y'),  # Standard adult age range
                (r'\belderly\b', lambda m: '65Y+'),
                (r'\bold\b', lambda m: '65Y+'),
                (r'\byoung\b', lambda m: '18Y-30Y'),
                (r'\bchild\b', lambda m: '2Y-12Y'),
                (r'\binfant\b', lambda m: '0Y-2Y'),
                (r'\bnewborn\b', lambda m: '0Y'),
                (r'\bembryo\b', lambda m: 'embryonic'),
                (r'\bfetal\b', lambda m: 'fetal')
            ]
            
            for pattern, formatter in age_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    try:
                        suggestion = formatter(match)
                        suggestions.append({
                            'suggested_value': suggestion,
                            'confidence': 0.8,
                            'source': 'text_pattern_analysis',
                            'ontology_source': 'standard'
                        })
                    except:
                        continue
            
            # Default SDRF-compliant age suggestions if none found
            if not suggestions:
                default_ages = ['not available', '25Y-65Y', '18Y-30Y', '30Y-50Y', '50Y-70Y', '70Y+']
                suggestions.extend([{
                    'suggested_value': age,
                    'confidence': 0.3,
                    'source': 'default_suggestion',
                    'ontology_source': 'standard'
                } for age in default_ages])
        
        elif column_type == 'sex':
            # Sex/gender patterns  
            sex_patterns = {
                r'\bmale\b': 'male',
                r'\bfemale\b': 'female', 
                r'\bmen\b': 'male',
                r'\bwomen\b': 'female',
                r'\bgender\b': 'not available'
            }
            
            for pattern, suggestion in sex_patterns.items():
                if re.search(pattern, text_lower):
                    suggestions.append({
                        'suggested_value': suggestion,
                        'confidence': 0.8,
                        'source': 'text_pattern_analysis',
                        'ontology_source': 'standard'
                    })
            
            # Default sex suggestions
            if not suggestions:
                default_sex = ['not available', 'male', 'female', 'mixed']
                suggestions.extend([{
                    'suggested_value': sex,
                    'confidence': 0.3,
                    'source': 'default_suggestion', 
                    'ontology_source': 'standard'
                } for sex in default_sex])
        
        elif column_type == 'biological_replicate':
            # Biological replicate patterns - SDRF: characteristics[biological replicate] with numeric values
            replicate_patterns = [
                (r'\bbio.*rep.*(\d+)', lambda m: m.group(1)),
                (r'\brep.*(\d+)', lambda m: m.group(1)), 
                (r'\bduplicate\b', lambda m: '2'),
                (r'\btriplicate\b', lambda m: '3'),
                (r'\bbiological.*(\d+)', lambda m: m.group(1))
            ]
            
            for pattern, formatter in replicate_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    try:
                        suggestion = formatter(match)
                        suggestions.append({
                            'suggested_value': suggestion,
                            'confidence': 0.8,
                            'source': 'text_pattern_analysis',
                            'ontology_source': 'standard'
                        })
                    except:
                        continue
            
            # Default biological replicate suggestions - SDRF requires numeric values, default 1
            if not suggestions:
                default_reps = ['1', '2', '3', '4', '5']  # SDRF: numeric values only
                suggestions.extend([{
                    'suggested_value': rep,
                    'confidence': 0.3,
                    'source': 'default_suggestion',
                    'ontology_source': 'standard'
                } for rep in default_reps])
        
        elif column_type == 'technical_replicate':
            # Technical replicate patterns - SDRF: comment[technical replicate] with numeric values
            tech_patterns = [
                (r'\btech.*rep.*(\d+)', lambda m: m.group(1)),
                (r'\brun.*(\d+)', lambda m: m.group(1)),
                (r'\binjection.*(\d+)', lambda m: m.group(1)),
                (r'\btechnical.*(\d+)', lambda m: m.group(1)),
                (r'\bduplicate\b', lambda m: '2'),
                (r'\btriplicate\b', lambda m: '3')
            ]
            
            for pattern, formatter in tech_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    try:
                        suggestion = formatter(match)
                        suggestions.append({
                            'suggested_value': suggestion,
                            'confidence': 0.8,
                            'source': 'text_pattern_analysis',
                            'ontology_source': 'standard'
                        })
                    except:
                        continue
            
            # Default technical replicate suggestions - SDRF requires numeric values, default 1
            if not suggestions:
                default_tech = ['1', '2', '3', '4', '5']  # SDRF: numeric values only
                suggestions.extend([{
                    'suggested_value': tech,
                    'confidence': 0.3,
                    'source': 'default_suggestion',
                    'ontology_source': 'standard'
                } for tech in default_tech])
        
        elif column_type == 'fraction_identifier':
            # Fraction patterns - SDRF: comment[fraction identifier] starting from 1
            fraction_patterns = [
                (r'\bfraction.*(\d+)', lambda m: m.group(1)),
                (r'\bfrac.*(\d+)', lambda m: m.group(1)),
                (r'\bf(\d+)', lambda m: m.group(1)),
                (r'\bno.*fraction', lambda m: '1'),  # SDRF: 1 for non-fractionated
                (r'\bnot.*fraction', lambda m: '1'),
                (r'\bwhole.*sample', lambda m: '1')
            ]
            
            for pattern, formatter in fraction_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    try:
                        suggestion = formatter(match)
                        suggestions.append({
                            'suggested_value': suggestion,
                            'confidence': 0.8,
                            'source': 'text_pattern_analysis',
                            'ontology_source': 'standard'
                        })
                    except:
                        continue
            
            # Default fraction suggestions - SDRF: must start from 1, use 1 for non-fractionated
            if not suggestions:
                default_fractions = ['1', '2', '3', '4', '5']  # SDRF: numeric values starting from 1
                suggestions.extend([{
                    'suggested_value': frac,
                    'confidence': 0.3,
                    'source': 'default_suggestion',
                    'ontology_source': 'standard'
                } for frac in default_fractions])
        
        return suggestions