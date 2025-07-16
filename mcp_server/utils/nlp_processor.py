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
    
    def __init__(self, ai_client=None):
        """Initialize the analyzer with predefined patterns and keywords.
        
        Args:
            ai_client: Optional MCP Claude client for AI-powered term extraction
        """
        self._setup_patterns()
        self._setup_keywords()
        self.ai_client = ai_client
    
    def _setup_patterns(self):
        """Setup regex patterns for term extraction."""
        # Common organism patterns
        self.organism_patterns = [
            r'\b(human|mouse|rat|bovine|chicken|porcine|rabbit)\b',
            r'\b(Homo sapiens|Mus musculus|Rattus norvegicus)\b',
            r'\b(E\.?\s*coli|Escherichia coli)\b',
            r'\b(HEK\s*293|HeLa|MCF-?7|A549|Jurkat)\b',  # Cell lines
            r'\b(BL21|DH5α|DH10B|XL1-Blue|TOP10)\b',  # E. coli strains
            r'\b(HEK293T?|CHO|COS-?7|Vero|3T3)\b',  # Additional cell lines
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
            r'\b(DMEM|RPMI|LB|SOC|2YT|M9|MEM|EMEM)\b',  # Media abbreviations
            r'\b(FBS|BSA|EDTA|SDS|PEG|Triton|Tween)\b',  # Common biochemical reagents
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
        
        # AI-powered extraction for non-obvious terms (when available)
        if self.ai_client:
            ai_terms = self._extract_with_ai_reasoning(step_text)
            extracted_terms.extend(ai_terms)
        
        # Sort by confidence and position (re-sort after adding AI terms)
        extracted_terms.sort(key=lambda x: (-x.confidence, x.start_pos))
        
        return self._deduplicate_terms(extracted_terms)
    
    def _extract_with_ai_reasoning(self, step_text: str) -> List[ExtractedTerm]:
        """
        Use AI to extract non-obvious biological terms with reasoning.
        
        This catches terms that regex patterns might miss, like:
        - Strain names (BL21, DH5α, etc.) 
        - Abbreviations (DMEM, FBS, etc.)
        - Protocol-specific terminology
        - Implicit biological context
        
        Args:
            step_text: Original protocol step text
            
        Returns:
            List of ExtractedTerm objects identified by AI
        """
        if not self.ai_client or not step_text.strip():
            return []
            
        try:
            print(f"DEBUG: AI extraction for: {step_text[:100]}...")
            
            # Call AI with specialized prompt for term extraction with reasoning
            ai_prompt = f"""Extract ALL biological, biochemical, and analytical terms from this protocol step that may not be obvious to regex patterns. Include:

1. Strain/cell line names (e.g., BL21, DH5α, HEK293T)
2. Media/buffer abbreviations (e.g., DMEM, PBS, LB)
3. Supplier-specific product names
4. Technical abbreviations and acronyms
5. Implicit organism/tissue context
6. Non-standard chemical names
7. Procedure-specific terminology

Protocol step: "{step_text}"

For each term you identify, explain your reasoning for why it's biologically relevant and what category it belongs to. Focus on terms that standard keyword matching would miss.

Be comprehensive but precise - include terms that provide valuable metadata for scientific reproducibility."""
            
            # Use the AI client's direct tool execution with SDRF specification
            if hasattr(self.ai_client, '_execute_tool_sync'):
                # Create enhanced prompt with SDRF specification
                sdrf_specification = self._get_sdrf_specification_context()
                enhanced_text = f"""{sdrf_specification}

PROTOCOL STEP TO ANALYZE:
"{step_text}"

TASK: Extract biological terms and determine appropriate SDRF column mappings using the specification above.

FOCUS ON:
1. Non-obvious terms that regex patterns would miss (strains, abbreviations, implicit context)
2. Proper SDRF column assignment based on the specification
3. Standardized term formatting (expand abbreviations, use scientific names)
4. Multiple column mappings when appropriate (e.g., BL21 → both organism and strain)

PROVIDE REASONING: For each term, explain why you chose that SDRF column and term format."""
                
                # Call extraction with SDRF-aware context
                result = self.ai_client._execute_tool_sync('extract_protocol_terms', {'text': enhanced_text})
                
                ai_terms = []
                for term_data in result:
                    # Convert AI result to ExtractedTerm
                    term = ExtractedTerm(
                        text=term_data['text'],
                        term_type=TermType(term_data['term_type']),
                        context=term_data.get('context', ''),
                        confidence=term_data['confidence'] * 0.9,  # Slightly lower confidence for AI vs exact regex
                        start_pos=term_data.get('start_pos', 0),
                        end_pos=term_data.get('end_pos', len(term_data['text']))
                    )
                    ai_terms.append(term)
                
                print(f"DEBUG: AI extracted {len(ai_terms)} additional terms")
                return ai_terms
                
        except Exception as e:
            print(f"DEBUG: AI extraction failed: {e}")
            return []
            
        return []
    
    def _get_sdrf_specification_context(self) -> str:
        """
        Get SDRF specification context for AI-powered term extraction and column mapping.
        
        Returns:
            Complete SDRF specification content
        """
        return """# SDRF-Proteomics Specification Memory

## Official SDRF Columns and Structure

### Core Sample Metadata (Required)

#### Source Information
- **source name**: Unique sample identifier (can appear multiple times for same sample)

#### Required Characteristics
- **characteristics[organism]**: Sample organism (EFO term, values from NCBI Taxonomy)
- **characteristics[disease]**: Disease under study (EFO term, MONDO recommended)  
- **characteristics[organism part]**: Anatomy/tissue part (EFO term, Uberon ontology)
- **characteristics[cell type]**: Cell type (EFO term, Cell Ontology)

### Data File Metadata (Required)

#### Core Data Properties
- **assay name**: MS run identifier (e.g., "run 1", "run_fraction_1_2")
- **technology type**: Must be "proteomic profiling by mass spectrometry"
- **comment[fraction identifier]**: Fraction number (starts from 1, use 1 for non-fractionated)
- **comment[label]**: Sample label (label free sample, TMT126, TMT127, etc.)
- **comment[data file]**: Raw/converted file name
- **comment[instrument]**: Instrument model from PSI-MS ontology

### Additional Sample Characteristics (Optional but Recommended)

#### Sample Properties
- **characteristics[age]**: Format {X}Y{X}M{X}D (e.g., 40Y, 40Y5M2D, or ranges 40Y-85Y)
- **characteristics[sex]**: Male/female/not available
- **characteristics[individual]**: Patient/subject identifier
- **characteristics[cell line]**: Cell line name/identifier
- **characteristics[mass]**: Sample mass (for spiked samples)
- **characteristics[biological replicate]**: Biological replicate number (mandatory, use 1 if none)
- **characteristics[synthetic peptide]**: "synthetic" or "not synthetic"
- **characteristics[pooled sample]**: "not pooled", "pooled", or SN=sample1,sample2...
- **characteristics[xenograft]**: PDX description (e.g., "pancreatic cancer cells grown in nude mice")
- **characteristics[source name]**: Reference to original sample (for PDX)
- **characteristics[spiked compound]**: Key-value pairs for spiked components
- **characteristics[enrichment process]**: e.g., "enrichment of phosphorylated Protein"

### Technical MS Properties (Recommended)

#### Instrument Configuration
- **comment[MS2 analyzer type]**: Mass analyzer type for MS2 scans
- **comment[technical replicate]**: Technical replicate number (mandatory, use 1 if none)
- **comment[collision energy]**: Collision energy (eV or NCE)
- **comment[dissociation method]**: Fragmentation method (HCD, CID, etc.)
- **comment[proteomics data acquisition method]**: DDA, DIA, PRM, SRM, etc.

#### MS Scan Parameters (DIA specific)
- **comment[MS1 scan range]**: m/z range (e.g., "400m/z - 1200m/z")
- **comment[scan window lower limit]**: Lower m/z limit
- **comment[scan window upper limit]**: Upper m/z limit

#### Mass Tolerances
- **comment[precursor mass tolerance]**: Precursor tolerance (Da or ppm)
- **comment[fragment mass tolerance]**: Fragment tolerance (Da or ppm)

### Sample Preparation Details

#### Chemical Processing
- **comment[reduction reagent]**: Disulfide reduction agent (e.g., DTT)
- **comment[alkylation reagent]**: Alkylation agent (e.g., IAA)
- **comment[depletion]**: "no depletion", "depletion", "depleted fraction", "bound fraction"
- **comment[fractionation method]**: Separation method (e.g., Off-gel electrophoresis)

#### Enzymatic Digestion
- **comment[cleavage agent details]**: Key-value pairs for enzymes
  - NT=Enzyme Name (required)
  - AC=MS Ontology Accession (optional)
  - CS=Cleavage Site Regex (optional)

#### Protein Modifications
- **comment[modification parameters]**: Key-value pairs for PTMs/modifications
  - NT=Modification Name (required)
  - AC=UNIMOD/PSI-MOD Accession (optional)
  - MT=Modification Type (Fixed/Variable/Annotated)
  - PP=Position (Anywhere/Protein N-term/C-term/Any N-term/C-term)
  - TA=Target Amino Acid (required)
  - MM=Monoisotopic Mass (optional)
  - CF=Chemical Formula (optional)
  - TS=Target Site Regex (optional)

### Study Design Variables

#### Factor Values
- **factor value[...]**: Variables under study (e.g., factor value[tissue], factor value[phenotype])

### Additional Data Properties

#### File Management
- **comment[file uri]**: Public URI to data file
- **comment[proteomexchange accession number]**: Dataset identifier for multi-project files

#### Spiked Compound Properties (Key-Value Format)
- SP=Species
- CT=Compound Type (protein/peptide/mixture/other)
- QY=Quantity
- PS=Peptide Sequence
- AC=UniProt Accession
- CN=Compound Name
- CV=Compound Vendor
- CS=Compound Specification URI
- CF=Compound Formula

## Supported Ontologies/Controlled Vocabularies

### Primary Ontologies
- **PSI Mass Spectrometry CV (PSI-MS)**: Instruments, methods, technical terms
- **Experimental Factor Ontology (EFO)**: Sample characteristics, diseases
- **UNIMOD**: Protein modifications for mass spectrometry
- **PSI-MOD CV**: Protein modifications
- **MONDO Disease Ontology**: Unified disease terms
- **NCBI Organismal Classification**: Organism taxonomy
- **Cell Line Ontology**: Cell line terms
- **Cell Ontology**: Cell type terms
- **Uber-anatomy Ontology**: Anatomy terms
- **PRIDE Controlled Vocabulary**: Proteomics-specific terms

### Specialized Ontologies
- **Drosophila anatomy ontology**
- **Plant ontology**
- **Zebrafish anatomy and development ontology**
- **Zebrafish developmental stages ontology**
- **Plant Environment Ontology**
- **FlyBase Developmental Ontology**
- **Rat Strain Ontology**
- **Chemical Entities of Biological Interest Ontology (ChEBI)**
- **PATO - Phenotype and Trait Ontology**

## Value Formats and Conventions

### Value Representation Types
1. **Free Text**: Human-readable text (preferably exact EFO term names)
2. **Ontology URI**: Computer-readable URI (e.g., http://purl.obolibrary.org/obo/NCBITaxon_9606)
3. **Key=Value Pairs**: Combined human/computer readable format

### Special Values
- **"not available"**: Unknown mandatory values
- **"not applicable"**: Non-applicable mandatory values
- **"normal"**: Healthy samples (maps to PATO_0000461)

### Format Rules
- **Case sensitivity**: Case-insensitive specification, lowercase recommended
- **Spaces**: Space-sensitive (sourcename ≠ source name)
- **Extensions**: .tsv or .txt
- **Column order**: source name → characteristics → assay name → technology type → comments

### Label Values (comment[label])
- **Label-free**: "label free sample"
- **TMT**: TMT126, TMT127, TMT127C, TMT127N, TMT128, TMT128C, TMT128N, TMT129, TMT129C, TMT129N, TMT130, TMT130C, TMT130N, TMT131
- **SILAC**: Various SILAC labels from PRIDE CV
- **iTRAQ**: Various iTRAQ labels from PRIDE CV

### Technology Type Values
- **"proteomic profiling by mass spectrometry"** (only valid value)

### Data Acquisition Methods
- **data-dependent acquisition** (DDA)
- **data-independent acquisition** (DIA)
- **diaPASEF** (DIA subtype)
- **SWATH MS** (DIA subtype)
- **parallel reaction monitoring** (PRM)
- **selected reaction monitoring** (SRM)

## SDRF-Proteomics Best Practices

### File Structure
- One row per sample-to-file relationship
- One row per labeling channel in multiplex experiments
- Mandatory columns must be present for all samples
- Recommended to end with comment[data file] column

### Quality Guidelines
- Use controlled vocabulary terms when possible
- Provide ontology accessions for key terms
- Include technical and biological replicate information
- Specify instrument details and acquisition parameters
- Document sample preparation thoroughly

### Multi-sample Scenarios
- **Pooled samples**: Use characteristics[pooled sample] with SN=sample1,sample2...
- **Technical replicates**: Use comment[technical replicate] (mandatory)
- **Biological replicates**: Use characteristics[biological replicate] (mandatory)
- **PDX samples**: Reference original sample in characteristics[source name]
- **Spiked samples**: Use characteristics[spiked compound] with key-value format"""
    
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