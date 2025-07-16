"""
MCP Server for SDRF Protocol Annotation

This module implements a Model Context Protocol (MCP) server that provides Claude
with direct access to ontology databases and SDRF annotation tools.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from mcp import server
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource

# Django setup
import os
import sys
import django
from pathlib import Path

# Add Django project to Python path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Configure Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cupcake.settings')
django.setup()

from cc.models import (
    Species, Tissue, HumanDisease, SubcellularLocation, 
    MSUniqueVocabularies, Unimod, CellType, MondoDisease,
    UberonAnatomy, NCBITaxonomy, ChEBICompound, PSIMSOntology
)
from mcp_server.utils.term_matcher import OntologyTermMatcher
from mcp_server.utils.nlp_processor import ProtocolStepAnalyzer

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MCPSDRFServer:
    """MCP Server that provides Claude with SDRF annotation tools."""
    
    def __init__(self):
        self.server = Server("sdrf-annotation-server")
        self.term_matcher = OntologyTermMatcher()
        self.step_analyzer = ProtocolStepAnalyzer()
        self._setup_tools()
    
    def _setup_tools(self):
        """Setup MCP tools that Claude can use."""
        
        # Tool: Search ontology databases
        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            return [
                Tool(
                    name="search_ontology",
                    description="Search for terms in ontology databases (Species, Tissue, Disease, etc.)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Term to search for"},
                            "ontology_types": {
                                "type": "array", 
                                "items": {"type": "string"},
                                "description": "Ontology types to search: species, tissue, human_disease, subcellular_location, ms_vocabularies, unimod, mondo_disease, uberon_anatomy, ncbi_taxonomy, chebi_compound, psims_ontology"
                            },
                            "min_confidence": {"type": "number", "default": 0.5, "description": "Minimum confidence threshold"}
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="get_ontology_details",
                    description="Get detailed information about a specific ontology term",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "ontology_type": {"type": "string", "description": "Type of ontology"},
                            "term_id": {"type": "string", "description": "ID of the term"},
                        },
                        "required": ["ontology_type", "term_id"]
                    }
                ),
                Tool(
                    name="search_unimod_modifications",
                    description="Search for protein modifications in UniMod database with rich metadata",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Modification name to search for"},
                            "include_metadata": {"type": "boolean", "default": True, "description": "Include rich metadata like mass, formula, target amino acids"}
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="extract_protocol_terms",
                    description="Extract biological and analytical terms from protocol text using NLP",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Protocol step text to analyze"},
                            "extract_all": {"type": "boolean", "default": True, "description": "Extract all term types"}
                        },
                        "required": ["text"]
                    }
                ),
                Tool(
                    name="validate_sdrf_format",
                    description="Validate that a term follows SDRF-Proteomics format specifications",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "sdrf_column": {"type": "string", "description": "SDRF column type"},
                            "value": {"type": "string", "description": "Value to validate"},
                            "format_type": {"type": "string", "description": "Expected format (key_value, simple, age_format, etc.)"}
                        },
                        "required": ["sdrf_column", "value"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Handle tool calls from Claude."""
            
            try:
                if name == "search_ontology":
                    return await self._search_ontology_tool(arguments)
                elif name == "get_ontology_details":
                    return await self._get_ontology_details_tool(arguments)
                elif name == "search_unimod_modifications":
                    return await self._search_unimod_tool(arguments)
                elif name == "extract_protocol_terms":
                    return await self._extract_protocol_terms_tool(arguments)
                elif name == "validate_sdrf_format":
                    return await self._validate_sdrf_format_tool(arguments)
                else:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]
                    
            except Exception as e:
                logger.error(f"Error in tool {name}: {e}")
                return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]
    
    async def _search_ontology_tool(self, args: Dict[str, Any]) -> List[TextContent]:
        """Search ontology databases for terms."""
        query = args["query"]
        ontology_types = args.get("ontology_types", None)
        min_confidence = args.get("min_confidence", 0.5)
        
        # Use the term matcher to search
        matches = self.term_matcher.match_terms([query], ontology_types, min_confidence)
        
        if not matches:
            return [TextContent(type="text", text=f"No matches found for '{query}' in specified ontologies")]
        
        # Format results
        results = []
        for match in matches:
            result = {
                "ontology_type": match.ontology_type,
                "ontology_name": match.ontology_name,
                "accession": match.accession,
                "confidence": match.confidence,
                "match_type": match.match_type,
                "extracted_term": match.extracted_term
            }
            
            # Add rich metadata if available
            if match.definition:
                result["definition"] = match.definition
            if match.synonyms:
                result["synonyms"] = match.synonyms
            if match.chemical_formula:
                result["chemical_formula"] = match.chemical_formula
            if match.mass_info:
                result["mass_info"] = match.mass_info
            if match.target_info:
                result["target_info"] = match.target_info
                
            results.append(result)
        
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    async def _get_ontology_details_tool(self, args: Dict[str, Any]) -> List[TextContent]:
        """Get detailed information about a specific ontology term."""
        ontology_type = args["ontology_type"]
        term_id = args["term_id"]
        
        # Map ontology types to Django models
        model_mapping = {
            "species": Species,
            "tissue": Tissue,
            "human_disease": HumanDisease,
            "subcellular_location": SubcellularLocation,
            "ms_vocabularies": MSUniqueVocabularies,
            "unimod": Unimod,
            "mondo_disease": MondoDisease,
            "uberon_anatomy": UberonAnatomy,
            "ncbi_taxonomy": NCBITaxonomy,
            "chebi_compound": ChEBICompound,
            "psims_ontology": PSIMSOntology
        }
        
        if ontology_type not in model_mapping:
            return [TextContent(type="text", text=f"Unknown ontology type: {ontology_type}")]
        
        model_class = model_mapping[ontology_type]
        
        try:
            # Try to find the term by ID or primary key
            if term_id.isdigit():
                term = model_class.objects.get(pk=int(term_id))
            else:
                # Try to find by identifier field
                if hasattr(model_class, 'identifier'):
                    term = model_class.objects.get(identifier=term_id)
                else:
                    term = model_class.objects.get(accession=term_id)
            
            # Extract all available fields
            details = {}
            for field in term._meta.fields:
                value = getattr(term, field.name)
                if value is not None:
                    details[field.name] = str(value)
            
            return [TextContent(type="text", text=json.dumps(details, indent=2))]
            
        except model_class.DoesNotExist:
            return [TextContent(type="text", text=f"Term {term_id} not found in {ontology_type}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error retrieving term: {str(e)}")]
    
    async def _search_unimod_tool(self, args: Dict[str, Any]) -> List[TextContent]:
        """Search UniMod database with rich metadata."""
        query = args["query"]
        include_metadata = args.get("include_metadata", True)
        
        # Search UniMod specifically
        matches = self.term_matcher.match_terms([query], ["unimod"], 0.4)
        
        if not matches:
            return [TextContent(type="text", text=f"No UniMod modifications found for '{query}'")]
        
        results = []
        for match in matches:
            result = {
                "name": match.ontology_name,
                "accession": match.accession,
                "confidence": match.confidence,
                "match_type": match.match_type
            }
            
            if include_metadata:
                # Get the actual UniMod record for rich metadata
                try:
                    unimod_record = Unimod.objects.get(accession=match.accession)
                    
                    if unimod_record.additional_data:
                        additional_data = json.loads(unimod_record.additional_data)
                        result.update({
                            "monoisotopic_mass": additional_data.get("monoisotopic_mass"),
                            "chemical_formula": additional_data.get("chemical_formula"),
                            "target_amino_acids": additional_data.get("target_amino_acids"),
                            "modification_type": additional_data.get("modification_type"),
                            "position": additional_data.get("position")
                        })
                    
                    # Create SDRF key-value format
                    key_value_parts = [f"NT={result['name']}", f"AC={result['accession']}"]
                    if result.get("target_amino_acids"):
                        key_value_parts.append(f"TA={result['target_amino_acids']}")
                    if result.get("monoisotopic_mass"):
                        key_value_parts.append(f"MM={result['monoisotopic_mass']}")
                    if result.get("modification_type"):
                        key_value_parts.append(f"MT={result['modification_type']}")
                    
                    result["sdrf_format"] = ";".join(key_value_parts)
                    
                except Unimod.DoesNotExist:
                    pass
            
            results.append(result)
        
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    async def _extract_protocol_terms_tool(self, args: Dict[str, Any]) -> List[TextContent]:
        """Extract terms from protocol text using NLP."""
        text = args["text"]
        extract_all = args.get("extract_all", True)
        
        # Use the NLP analyzer to extract terms
        extracted_terms = self.step_analyzer.analyze_step_text(text)
        
        results = []
        for term in extracted_terms:
            result = {
                "text": term.text,
                "term_type": term.term_type.value,
                "confidence": term.confidence,
                "context": term.context,
                "start_pos": term.start_pos,
                "end_pos": term.end_pos
            }
            results.append(result)
        
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    async def _validate_sdrf_format_tool(self, args: Dict[str, Any]) -> List[TextContent]:
        """Validate SDRF format compliance."""
        sdrf_column = args["sdrf_column"]
        value = args["value"]
        format_type = args.get("format_type", "auto")
        
        validation_result = {
            "valid": True,
            "issues": [],
            "suggestions": []
        }
        
        # Add validation logic based on SDRF specification
        if sdrf_column == "modification parameters":
            if "NT=" not in value or "AC=" not in value:
                validation_result["valid"] = False
                validation_result["issues"].append("Missing required NT= or AC= in modification parameters")
                validation_result["suggestions"].append("Use format: NT=Name;AC=Accession;MT=Type;TA=Target_AA")
        
        elif sdrf_column == "age":
            import re
            age_pattern = r'^\d+Y(\d+M)?(\d+D)?$|^\d+Y-\d+Y$'
            if not re.match(age_pattern, value):
                validation_result["valid"] = False
                validation_result["issues"].append("Age must follow SDRF format: {X}Y{X}M{X}D or range like 25Y-65Y")
        
        return [TextContent(type="text", text=json.dumps(validation_result, indent=2))]
    
    async def run(self, transport_type: str = "stdio"):
        """Run the MCP server."""
        if transport_type == "stdio":
            from mcp.server.stdio import stdio_server
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="sdrf-annotation-server",
                        server_version="1.0.0",
                        capabilities=self.server.get_capabilities(
                            notification_options=None,
                            experimental_capabilities=None,
                        ),
                    ),
                )
        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")

async def main():
    """Main entry point for the MCP server."""
    server = MCPSDRFServer()
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())