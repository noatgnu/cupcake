# MCP SDRF Protocol Annotator

An Model Context Protocol (MCP) server that automatically analyzes protocol steps and generates SDRF (Sample and Data Relationship Format) metadata using built-in ontology models.

## Overview

This MCP server provides tools for:
- Analyzing protocol step text to extract biological and analytical terms
- Matching extracted terms to curated ontology vocabularies 
- Generating SDRF-compliant metadata columns
- Validating SDRF compliance
- Exporting protocols as SDRF files

## Features

### Ontology Integration
- **Species**: NCBI Taxonomy and organism information
- **Tissue**: Tissue and organism part annotations
- **Human Disease**: Disease and condition vocabularies
- **Subcellular Location**: Cellular component ontologies
- **MS Vocabularies**: Mass spectrometry instruments and methods
- **UniMod**: Protein modification databases

### SDRF Compliance
- Automatic metadata column generation
- SDRF structure validation
- Standard format export (tab-separated)
- Ontology term formatting (NT=name;AC=accession)

### Natural Language Processing
- Regex-based term extraction
- Context-aware analysis
- Confidence scoring for matches
- Fuzzy string matching algorithms

## Installation

1. Ensure you have the Cupcake Django project set up
2. Install MCP dependencies:
   ```bash
   pip install mcp>=1.0.0
   ```

## Usage

### Running the Server

#### Command Line
```bash
cd /mnt/d/PycharmProjects/cupcake/mcp_server
python run_server.py
```

#### With Options
```bash
python run_server.py --verbose --transport stdio
```

### MCP Client Configuration

Add this to your MCP client configuration:

```json
{
  "mcpServers": {
    "sdrf-protocol-annotator": {
      "command": "python",
      "args": [
        "/mnt/d/PycharmProjects/cupcake/mcp_server/run_server.py"
      ],
      "env": {
        "DJANGO_SETTINGS_MODULE": "cupcake.settings",
        "PYTHONPATH": "/mnt/d/PycharmProjects/cupcake"
      }
    }
  }
}
```

## Available Tools

### 1. analyze_protocol_step
Analyzes a single protocol step to extract terms and generate SDRF suggestions.

**Parameters:**
- `step_id` (integer): Protocol step ID to analyze
- `user_token` (string, optional): Authentication token

**Returns:**
- Extracted terms with confidence scores
- Ontology matches by category
- SDRF metadata suggestions
- Analysis metadata

### 2. match_ontology_terms
Matches terms directly to ontology vocabularies.

**Parameters:**
- `terms` (array): List of terms to match
- `ontology_types` (array, optional): Specific ontologies to search
- `min_confidence` (number, optional): Minimum confidence threshold

**Returns:**
- Matched ontology terms with confidence scores
- Match types (exact, partial, fuzzy)
- Accession numbers and metadata

### 3. generate_sdrf_metadata
Generates SDRF metadata columns from analysis results.

**Parameters:**
- `step_id` (integer): Protocol step ID
- `auto_create` (boolean, optional): Create MetadataColumn objects
- `user_token` (string, optional): Authentication token

**Returns:**
- Metadata column specifications
- SDRF-formatted values
- Creation status and details

### 4. validate_sdrf_compliance
Validates existing protocol metadata for SDRF compliance.

**Parameters:**
- `step_id` (integer): Protocol step ID
- `user_token` (string, optional): Authentication token

**Returns:**
- Compliance status
- Missing required columns
- Invalid column types
- Suggestions for improvement

### 5. export_sdrf_file
Exports protocol metadata as SDRF file format.

**Parameters:**
- `protocol_id` (integer): Protocol ID to export
- `user_token` (string, optional): Authentication token

**Returns:**
- SDRF file content (headers and data)
- Export metadata
- Tab-separated format ready for download

### 6. analyze_full_protocol
Analyzes all steps in a protocol comprehensively.

**Parameters:**
- `protocol_id` (integer): Protocol ID to analyze
- `user_token` (string, optional): Authentication token

**Returns:**
- Per-step analysis results
- Protocol-level term summary
- Aggregated SDRF suggestions
- Comprehensive metadata overview

## Examples

### Basic Step Analysis
```python
# Analyze a protocol step
result = await call_tool("analyze_protocol_step", {
    "step_id": 123
})

# Check results
if result["success"]:
    sdrf_suggestions = result["sdrf_suggestions"]
    analysis_summary = result["analysis_summary"]
```

### Generate Metadata Columns
```python
# Generate and create metadata columns
result = await call_tool("generate_sdrf_metadata", {
    "step_id": 123,
    "auto_create": True,
    "user_token": "your_token_here"
})

# Check creation status
if result["success"]:
    created_count = result["created_columns"]
    column_details = result["column_details"]
```

### Full Protocol Analysis
```python
# Analyze entire protocol
result = await call_tool("analyze_full_protocol", {
    "protocol_id": 456
})

# Access aggregated suggestions
protocol_suggestions = result["protocol_sdrf_suggestions"]
step_suggestions = result["step_sdrf_suggestions"]
```

## Configuration

Key configuration options in `config.py`:

- `DEFAULT_MIN_CONFIDENCE`: Minimum confidence for term matching (0.5)
- `HIGH_CONFIDENCE_THRESHOLD`: Threshold for high-confidence matches (0.8)
- `REQUIRED_SDRF_COLUMNS`: Required SDRF columns for compliance
- `REQUIRE_AUTH_TOKEN`: Whether authentication is required

## Architecture

### Components

1. **Django Integration** (`utils/django_setup.py`)
   - Environment setup
   - Model access
   - Authentication handling

2. **NLP Processing** (`utils/nlp_processor.py`)
   - Term extraction using regex patterns
   - Context analysis
   - Confidence scoring

3. **Term Matching** (`utils/term_matcher.py`)
   - Ontology term caching
   - Fuzzy string matching
   - Multi-level matching strategies

4. **Protocol Analysis** (`tools/protocol_analyzer.py`)
   - Step and protocol analysis
   - Term categorization
   - SDRF suggestion generation

5. **SDRF Generation** (`tools/sdrf_generator.py`)
   - Metadata column creation
   - SDRF compliance validation
   - File export functionality

6. **MCP Server** (`server.py`)
   - Tool registration and handling
   - Request/response management
   - Error handling and logging

### Data Flow

1. **Input**: Protocol step text or ID
2. **Analysis**: NLP processing extracts terms
3. **Matching**: Terms matched to ontology vocabularies
4. **Classification**: Matches categorized by SDRF column types
5. **Generation**: SDRF metadata columns created
6. **Output**: Structured metadata with confidence scores

## Troubleshooting

### Common Issues

1. **Django Setup Errors**
   - Ensure `DJANGO_SETTINGS_MODULE` is set correctly
   - Verify database connectivity
   - Check ontology model availability

2. **Authentication Errors**
   - Provide valid user tokens for protected resources
   - Ensure user has appropriate permissions

3. **Low Match Confidence**
   - Adjust `min_confidence` parameter
   - Check term extraction patterns
   - Verify ontology data completeness

### Debugging

Enable verbose logging:
```bash
python run_server.py --verbose
```

Check Django models directly:
```python
from mcp_server.utils.django_setup import get_ontology_models
models = get_ontology_models()
```

## Contributing

1. Follow existing code patterns and documentation
2. Add tests for new functionality
3. Update this README for new features
4. Ensure SDRF compliance for any metadata changes

## License

This MCP server is part of the Cupcake project and follows the same licensing terms.