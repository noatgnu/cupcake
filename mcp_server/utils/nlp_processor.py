"""
Natural Language Processing utilities for protocol step analysis.

This module provides functions to extract biological and analytical terms
from protocol step descriptions for ontology matching.
"""

import re
from typing import List, Dict, Set, Tuple
from dataclasses import dataclass
from enum import Enum


class TermType(Enum):
    """Types of terms that can be extracted from protocol steps."""
    ORGANISM = "organism"
    TISSUE = "tissue"
    DISEASE = "disease"
    INSTRUMENT = "instrument"
    CHEMICAL = "chemical"
    MODIFICATION = "modification"
    PROCEDURE = "procedure"
    CELLULAR_COMPONENT = "cellular_component"


@dataclass
class ExtractedTerm:
    """Represents a term extracted from protocol text."""
    text: str
    term_type: TermType
    context: str
    confidence: float
    start_pos: int
    end_pos: int
    
    def to_dict(self):
        """Convert to JSON-serializable dictionary."""
        return {
            'text': self.text,
            'term_type': self.term_type.value,  # Convert enum to string
            'context': self.context,
            'confidence': self.confidence,
            'start_pos': self.start_pos,
            'end_pos': self.end_pos
        }


class ProtocolStepAnalyzer:
    """
    Analyzes protocol step text to extract relevant biological and analytical terms.
    """
    
    def __init__(self):
        """Initialize the analyzer with predefined patterns and keywords."""
        self._setup_patterns()
        self._setup_keywords()
    
    def _setup_patterns(self):
        """Setup regex patterns for term extraction."""
        # Common organism patterns
        self.organism_patterns = [
            r'\b(human|mouse|rat|bovine|chicken|porcine|rabbit)\b',
            r'\b(Homo sapiens|Mus musculus|Rattus norvegicus)\b',
            r'\b(E\.?\s*coli|Escherichia coli)\b',
            r'\b(HEK\s*293|HeLa|MCF-?7|A549|Jurkat)\b',  # Cell lines
        ]
        
        # Tissue/organism part patterns
        self.tissue_patterns = [
            r'\b(brain|liver|kidney|heart|lung|muscle|blood|plasma|serum)\b',
            r'\b(cortex|hippocampus|cerebellum|striatum)\b',
            r'\b(skin|bone|cartilage|tendon|ligament)\b',
            r'\b(stomach|intestine|colon|pancreas|spleen)\b',
        ]
        
        # Instrument patterns
        self.instrument_patterns = [
            r'\b(mass spectrometer|LC-?MS|HPLC|UPLC|Orbitrap|Q-?TOF)\b',
            r'\b(centrifuge|thermocycler|incubator|shaker)\b',
            r'\b(microscope|flow cytometer|plate reader)\b',
            r'\b(Thermo|Agilent|Waters|Bruker|Applied Biosystems)\b',
        ]
        
        # Chemical/reagent patterns (SDRF-enhanced)
        self.chemical_patterns = [
            r'\b(trypsin|chymotrypsin|pepsin|Lys-?C|Arg-?C|endoproteinase)\b',
            r'\b(DTT|TCEP|iodoacetamide|IAA|BME|chloroacetamide)\b',
            r'\b(formic acid|acetonitrile|methanol|water|TFA|HFIP)\b',
            r'\b(buffer|PBS|HEPES|Tris|bicarbonate|ammonium bicarbonate)\b',
        ]
        
        # SDRF-specific patterns
        self.sdrf_label_patterns = [
            r'\b(label.?free|TMT\d+[CN]?|SILAC|iTRAQ|dimethyl)\b',
            r'\b(heavy|light|medium)\s*(label|isotope)?\b',
        ]
        
        # SDRF enrichment patterns
        self.enrichment_patterns = [
            r'\b(phospho|glyco|ubiquitin|acetyl).?(enrichment|purification|pulldown)\b',
            r'\b(TiO2|IMAC|HILIC|SCX|SAX)\b',
            r'\b(immunoprecipitation|IP|pull.?down)\b',
        ]
        
        # Modification patterns
        self.modification_patterns = [
            r'\b(phosphor\w+|acetyl\w+|methyl\w+|ubiquitin\w+)\b',
            r'\b(oxidation|deamidation|carbamylation)\b',
            r'\b(TMT|iTRAQ|SILAC|label\w*)\b',
        ]
        
        # Disease patterns
        self.disease_patterns = [
            r'\b(cancer|tumor|carcinoma|sarcoma|lymphoma|leukemia)\b',
            r'\b(diabetes|hypertension|alzheimer|parkinson)\b',
            r'\b(infection|inflammatory|autoimmune)\b',
        ]
        
        # Cellular component patterns
        self.cellular_patterns = [
            r'\b(nucleus|cytoplasm|mitochondria|membrane|ribosome)\b',
            r'\b(endoplasmic reticulum|golgi|lysosome|peroxisome)\b',
            r'\b(cytoskeleton|chromatin|nucleolus)\b',
        ]
    
    def _setup_keywords(self):
        """Setup keyword dictionaries for fast lookup."""
        self.procedure_keywords = {
            'digestion', 'cleavage', 'reduction', 'alkylation',
            'desalting', 'cleanup', 'fractionation', 'separation',
            'enrichment', 'precipitation', 'extraction', 'purification',
            'incubation', 'heating', 'cooling', 'centrifugation',
            'washing', 'elution', 'concentration', 'dilution'
        }
        
        self.quantity_patterns = [
            r'\b\d+\s*(μ?[lgm]|mM|μM|nM|pM|ng|μg|mg|g|ml|μl|ul)\b',
            r'\b\d+\s*(minutes?|mins?|hours?|hrs?|seconds?|secs?)\b',
            r'\b\d+\s*(°C|degrees?|rpm|g-force|x\s*g)\b',
        ]
    
    def analyze_step_text(self, step_text: str) -> List[ExtractedTerm]:
        """
        Analyze protocol step text and extract relevant terms.
        
        Args:
            step_text (str): Protocol step description
            
        Returns:
            List[ExtractedTerm]: List of extracted terms with metadata
        """
        if not step_text:
            return []
        
        # Clean and normalize text
        text = self._normalize_text(step_text)
        
        extracted_terms = []
        
        # Extract different types of terms
        extracted_terms.extend(self._extract_organisms(text))
        extracted_terms.extend(self._extract_tissues(text))
        extracted_terms.extend(self._extract_instruments(text))
        extracted_terms.extend(self._extract_chemicals(text))
        extracted_terms.extend(self._extract_modifications(text))
        extracted_terms.extend(self._extract_diseases(text))
        extracted_terms.extend(self._extract_cellular_components(text))
        extracted_terms.extend(self._extract_procedures(text))
        
        # SDRF-specific extractions
        extracted_terms.extend(self._extract_sdrf_labels(text))
        extracted_terms.extend(self._extract_enrichment_processes(text))
        
        # Sort by confidence and position
        extracted_terms.sort(key=lambda x: (-x.confidence, x.start_pos))
        
        return self._deduplicate_terms(extracted_terms)
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for consistent processing."""
        # Convert to lowercase for pattern matching
        return text.lower().strip()
    
    def _extract_organisms(self, text: str) -> List[ExtractedTerm]:
        """Extract organism-related terms."""
        terms = []
        for pattern in self.organism_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.ORGANISM,
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.9,
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _extract_tissues(self, text: str) -> List[ExtractedTerm]:
        """Extract tissue/organism part terms."""
        terms = []
        for pattern in self.tissue_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.TISSUE,
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.8,
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _extract_instruments(self, text: str) -> List[ExtractedTerm]:
        """Extract instrument-related terms."""
        terms = []
        for pattern in self.instrument_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.INSTRUMENT,
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.85,
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _extract_chemicals(self, text: str) -> List[ExtractedTerm]:
        """Extract chemical/reagent terms."""
        terms = []
        for pattern in self.chemical_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.CHEMICAL,
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.8,
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _extract_modifications(self, text: str) -> List[ExtractedTerm]:
        """Extract protein modification terms."""
        terms = []
        for pattern in self.modification_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.MODIFICATION,
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.85,
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _extract_diseases(self, text: str) -> List[ExtractedTerm]:
        """Extract disease-related terms."""
        terms = []
        for pattern in self.disease_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.DISEASE,
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.75,
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _extract_cellular_components(self, text: str) -> List[ExtractedTerm]:
        """Extract cellular component terms."""
        terms = []
        for pattern in self.cellular_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.CELLULAR_COMPONENT,
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.8,
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _extract_procedures(self, text: str) -> List[ExtractedTerm]:
        """Extract procedure-related terms."""
        terms = []
        words = re.findall(r'\b\w+\b', text.lower())
        
        for i, word in enumerate(words):
            if word in self.procedure_keywords:
                start_pos = text.lower().find(word)
                end_pos = start_pos + len(word)
                terms.append(ExtractedTerm(
                    text=word,
                    term_type=TermType.PROCEDURE,
                    context=self._get_context(text, start_pos, end_pos),
                    confidence=0.7,
                    start_pos=start_pos,
                    end_pos=end_pos
                ))
        return terms
    
    def _extract_sdrf_labels(self, text: str) -> List[ExtractedTerm]:
        """Extract SDRF-specific labeling terms."""
        terms = []
        for pattern in self.sdrf_label_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.PROCEDURE,  # Labels are procedural metadata
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.9,  # High confidence for SDRF-specific patterns
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _extract_enrichment_processes(self, text: str) -> List[ExtractedTerm]:
        """Extract enrichment and purification process terms."""
        terms = []
        for pattern in self.enrichment_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                terms.append(ExtractedTerm(
                    text=match.group(),
                    term_type=TermType.PROCEDURE,
                    context=self._get_context(text, match.start(), match.end()),
                    confidence=0.85,
                    start_pos=match.start(),
                    end_pos=match.end()
                ))
        return terms
    
    def _get_context(self, text: str, start: int, end: int, context_window: int = 50) -> str:
        """Get surrounding context for a matched term."""
        context_start = max(0, start - context_window)
        context_end = min(len(text), end + context_window)
        return text[context_start:context_end].strip()
    
    def _deduplicate_terms(self, terms: List[ExtractedTerm]) -> List[ExtractedTerm]:
        """Remove duplicate terms based on text and position overlap."""
        if not terms:
            return []
        
        deduplicated = []
        seen_positions = set()
        
        for term in terms:
            # Create a position range key
            pos_key = (term.start_pos, term.end_pos, term.text.lower())
            
            if pos_key not in seen_positions:
                deduplicated.append(term)
                seen_positions.add(pos_key)
        
        return deduplicated
    
    def get_term_summary(self, terms: List[ExtractedTerm]) -> Dict[str, List[str]]:
        """
        Get a summary of extracted terms by type.
        
        Args:
            terms (List[ExtractedTerm]): List of extracted terms
            
        Returns:
            Dict[str, List[str]]: Dictionary mapping term types to unique term texts
        """
        summary = {}
        
        for term_type in TermType:
            type_terms = [term.text for term in terms if term.term_type == term_type]
            summary[term_type.value] = list(set(type_terms))  # Remove duplicates
        
        return summary