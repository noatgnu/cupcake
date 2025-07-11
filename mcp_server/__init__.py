"""
MCP Server for Automatic SDRF Protocol Annotation

This module provides a Model Context Protocol (MCP) server that can automatically
analyze protocol steps and generate SDRF (Sample and Data Relationship Format)
metadata annotations using the built-in ontology models.

Available Tools:
- analyze_protocol_step: Analyze protocol steps and extract biological terms
- match_ontology_terms: Match terms to ontology vocabularies  
- generate_sdrf_metadata: Generate SDRF metadata columns
- validate_sdrf_compliance: Validate SDRF structure compliance
- export_sdrf_file: Export protocols as SDRF files
- analyze_full_protocol: Comprehensive protocol analysis

Supported Ontologies:
- Species (NCBI Taxonomy)
- Tissue (Organism parts)
- Human Disease
- Subcellular Location
- MS Vocabularies (Instruments, methods, reagents)
- UniMod (Protein modifications)
"""

__version__ = "1.0.0"
__author__ = "Cupcake Protocol System"

# MCP tools are accessed directly via Django views and consumers
# No standalone server import needed for Django integration

__all__ = []