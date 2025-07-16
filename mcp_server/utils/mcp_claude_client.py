"""
MCP-enabled Claude client for SDRF analysis.

This client connects Claude to the MCP server, giving Claude direct access
to ontology databases and SDRF tools.
"""

import asyncio
import json
import logging
import time
import random
from typing import Any, Dict, List, Optional
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

class MCPClaudeClient:
    """Claude client that uses MCP tools for SDRF analysis."""
    
    def __init__(self, api_key: str, model: str = "claude-opus-4-20250514"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.anthropic.com/v1/messages"
        
        # MCP tools available to Claude
        self.mcp_tools = [
            {
                "name": "search_ontology",
                "description": "Search for terms in ontology databases to find exact matches",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Term to search for"},
                        "ontology_types": {
                            "type": "array", 
                            "items": {"type": "string"},
                            "description": "Ontology types: species, tissue, human_disease, subcellular_location, ms_vocabularies, unimod, mondo_disease, uberon_anatomy, ncbi_taxonomy, chebi_compound, psims_ontology"
                        },
                        "min_confidence": {"type": "number", "description": "Minimum confidence (0.0-1.0)"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "search_unimod_modifications",
                "description": "Search UniMod database for protein modifications with full metadata",
                "input_schema": {
                    "type": "object", 
                    "properties": {
                        "query": {"type": "string", "description": "Modification name"},
                        "include_metadata": {"type": "boolean", "description": "Include mass, formula, target AA"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "extract_protocol_terms", 
                "description": "Extract biological terms from protocol text using NLP",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Protocol text to analyze"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "validate_sdrf_format",
                "description": "Validate SDRF format compliance",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "sdrf_column": {"type": "string", "description": "SDRF column type"},
                        "value": {"type": "string", "description": "Value to validate"}
                    },
                    "required": ["sdrf_column", "value"]
                }
            }
        ]
    
    async def analyze_protocol_step_with_mcp(self, step_text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Analyze protocol step using Claude with MCP tools for database access.
        
        Args:
            step_text: Protocol step description
            context: Optional context information
            
        Returns:
            Analysis results with SDRF suggestions
        """
        if not step_text.strip():
            return {
                'success': False,
                'error': 'Empty step text provided'
            }
        
        try:
            # Build the prompt for Claude with MCP capabilities
            prompt = self._build_mcp_prompt(step_text, context)
            
            # Try multi-turn conversation approach
            messages = [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
            
            # Call Claude and get initial response
            response = await self._call_claude_with_messages(messages)
            
            # Check how many tools Claude actually called (before failsafe)
            claude_tool_count = 0
            for item in response.get('content', []):
                if item.get('type') == 'tool_use':
                    claude_tool_count += 1
            
            print(f"DEBUG: Claude called {claude_tool_count} tools initially")
            
            result = await self._process_claude_response(response, step_text)
            
            # If Claude only called extract_protocol_terms, continue the conversation
            if claude_tool_count == 1:
                print(f"DEBUG: Entering second turn - extracted {len(result.get('extracted_terms', []))} terms")
                extracted_terms = result.get('extracted_terms', [])
                
                # Add Claude's response to conversation
                assistant_content = response.get('content', [])
                messages.append({
                    "role": "assistant", 
                    "content": assistant_content
                })
                
                # For each tool_use in Claude's response, add tool_result
                tool_results = []
                for item in assistant_content:
                    if item.get('type') == 'tool_use':
                        tool_id = item.get('id')
                        tool_name = item.get('name')
                        tool_input = item.get('input', {})
                        
                        # Execute the tool and get result
                        try:
                            tool_result = await self._execute_tool(tool_name, tool_input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": str(tool_result)
                            })
                        except Exception as e:
                            tool_results.append({
                                "type": "tool_result", 
                                "tool_use_id": tool_id,
                                "content": f"Error: {str(e)}",
                                "is_error": True
                            })
                
                # Add tool results message
                if tool_results:
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })
                
                # Build specific instructions based on extracted terms
                modification_terms = [term.get('text', '') for term in extracted_terms if term.get('term_type', '') == 'modification']
                chemical_terms = [term.get('text', '') for term in extracted_terms if term.get('term_type', '') == 'chemical']
                
                continue_prompt = f"""Perfect! You extracted: {[t.get('text') for t in extracted_terms]}

Now call the database search tools for these terms:
"""
                
                if modification_terms:
                    for term in modification_terms:
                        continue_prompt += f"- search_unimod_modifications(query=\"{term}\", include_metadata=true)\n"
                if chemical_terms:
                    for term in chemical_terms:
                        continue_prompt += f"- search_ontology(query=\"{term}\", ontology_types=[\"chebi_compound\", \"ms_vocabularies\"])\n"
                
                continue_prompt += "\nCall ALL the search tools for the terms you found."
                messages.append({
                    "role": "user",
                    "content": continue_prompt
                })
                
                print(f"DEBUG: Calling Claude second turn with {len(messages)} messages")
                
                # Second turn
                second_response = await self._call_claude_with_messages(messages)
                second_result = await self._process_claude_response(second_response, step_text)
                
                print(f"DEBUG: Second turn produced {len(second_result.get('tools_used', []))} tools")
                
                # Merge results
                result['tools_used'].extend(second_result.get('tools_used', []))
                for key, value in second_result.get('sdrf_suggestions', {}).items():
                    if key in result['sdrf_suggestions']:
                        result['sdrf_suggestions'][key].extend(value)
                    else:
                        result['sdrf_suggestions'][key] = value
            
            # FAILSAFE: Only after all turns are complete, check if Claude called any database tools
            claude_only_tools = [t for t in result.get('tools_used', []) if t.get('source', 'claude_called') == 'claude_called']
            claude_db_tools = [t for t in claude_only_tools if t.get('tool') in ['search_unimod_modifications', 'search_ontology']]
            print(f"DEBUG FINAL FAILSAFE: Claude total={len(claude_only_tools)}, database={len(claude_db_tools)}, condition={len(claude_db_tools) == 0}")
            
            if len(claude_db_tools) == 0:  # Claude didn't call any database search tools across all turns
                print("DEBUG: Claude didn't call any database tools across all turns, executing failsafe searches")
                
                # Use the actual extracted terms from Claude's analysis
                extracted_terms = result.get('extracted_terms', [])
                print(f"DEBUG: Failsafe searching for {len(extracted_terms)} extracted terms")
                
                # Search for each extracted term in appropriate ontologies based on term type
                for term_data in extracted_terms:
                    term_text = term_data.get('text', '')
                    term_type = term_data.get('term_type', '')
                    
                    if not term_text.strip():
                        continue
                        
                    print(f"DEBUG: Failsafe processing term '{term_text}' (type: {term_type})")
                    
                    if term_type == 'modification':
                        # Search UniMod for this specific modification term
                        try:
                            mod_result = await self._execute_tool('search_unimod_modifications', {
                                'query': term_text, 
                                'include_metadata': True
                            })
                            result['tools_used'].append({
                                'tool': 'search_unimod_modifications',
                                'input': {'query': term_text, 'include_metadata': True},
                                'result': mod_result,
                                'source': 'failsafe_search'
                            })
                            self._process_tool_result('search_unimod_modifications', mod_result, result)
                            print(f"DEBUG: Failsafe UniMod search completed for '{term_text}'")
                        except Exception as e:
                            logger.error(f"Failsafe UniMod search failed for '{term_text}': {e}")
                    
                    elif term_type == 'chemical':
                        # Search chemical ontologies for this specific chemical
                        try:
                            chem_result = await self._execute_tool('search_ontology', {
                                'query': term_text,
                                'ontology_types': ['chebi_compound', 'ms_vocabularies']
                            })
                            result['tools_used'].append({
                                'tool': 'search_ontology', 
                                'input': {'query': term_text, 'ontology_types': ['chebi_compound', 'ms_vocabularies']},
                                'result': chem_result,
                                'source': 'failsafe_search'
                            })
                            self._process_tool_result('search_ontology', chem_result, result)
                            print(f"DEBUG: Failsafe ontology search completed for '{term_text}'")
                        except Exception as e:
                            logger.error(f"Failsafe ontology search failed for '{term_text}': {e}")
                    
                    elif term_type in ['organism', 'tissue', 'disease', 'cellular_component']:
                        # Map term types to appropriate ontology types
                        ontology_mapping = {
                            'organism': ['species', 'ncbi_taxonomy'],
                            'tissue': ['tissue', 'uberon_anatomy'],
                            'disease': ['human_disease', 'mondo_disease'],
                            'cellular_component': ['subcellular_location']
                        }
                        
                        ontology_types = ontology_mapping.get(term_type, ['ms_vocabularies'])
                        
                        try:
                            bio_result = await self._execute_tool('search_ontology', {
                                'query': term_text,
                                'ontology_types': ontology_types
                            })
                            result['tools_used'].append({
                                'tool': 'search_ontology', 
                                'input': {'query': term_text, 'ontology_types': ontology_types},
                                'result': bio_result,
                                'source': 'failsafe_search'
                            })
                            self._process_tool_result('search_ontology', bio_result, result)
                            print(f"DEBUG: Failsafe {term_type} search completed for '{term_text}'")
                        except Exception as e:
                            logger.error(f"Failsafe {term_type} search failed for '{term_text}': {e}")
            
            return {
                'success': True,
                'step_text': step_text,
                'sdrf_suggestions': result.get('sdrf_suggestions', {}),
                'extracted_terms': result.get('extracted_terms', []),
                'analysis_metadata': {
                    'analyzer_type': 'mcp_claude',
                    'model': self.model,
                    'timestamp': datetime.now().isoformat(),
                    'tools_used': result.get('tools_used', [])
                }
            }
            
        except Exception as e:
            logger.error(f"MCP Claude analysis failed: {e}")
            return {
                'success': False,
                'error': f'MCP Claude analysis failed: {str(e)}',
                'step_text': step_text
            }
    
    def _build_mcp_prompt(self, step_text: str, context: Optional[Dict] = None) -> str:
        """Build prompt for Claude with MCP tool instructions."""
        
        context_info = ""
        if context:
            if context.get('protocol_title'):
                context_info += f"Protocol: {context['protocol_title']}\n"
            if context.get('section_name'):
                context_info += f"Section: {context['section_name']}\n"
        
        prompt = f"""You are a proteomics metadata annotator with expert biological knowledge. You MUST call multiple tools.

{context_info}Protocol Step: "{step_text}"

MANDATORY SEQUENCE:
1. extract_protocol_terms(text="{step_text}")
2. Apply your biological knowledge to identify organisms:
   - BL21 = E. coli strain, extract "Escherichia coli" as organism
   - HEK293 = human cell line, extract "Homo sapiens" as organism  
   - Similar for other strains/cell lines you recognize
3. Then search databases for EVERY term you find:
   - For organisms: search_ontology(query="scientific_name", ontology_types=["species", "ncbi_taxonomy"])
   - For modifications: search_unimod_modifications(query="term", include_metadata=true)
   - For chemicals: search_ontology(query="term", ontology_types=["chebi_compound", "ms_vocabularies"])

Use your knowledge to extract the actual biological entities (E. coli for BL21), not just the laboratory identifiers.
You MUST call at least 3 tools total. Do not stop after extract_protocol_terms."""

        return prompt
    
    async def _call_claude_with_tools(self, prompt: str) -> Dict[str, Any]:
        """Call Claude API with tool use capabilities."""
        messages = [{'role': 'user', 'content': prompt}]
        return await self._call_claude_with_messages(messages)
    
    async def _call_claude_with_messages(self, messages: List[Dict[str, Any]], max_retries: int = 5) -> Dict[str, Any]:
        """Call Claude API with multi-turn conversation and exponential backoff retry."""
        
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01'
        }
        
        payload = {
            'model': self.model,
            'max_tokens': 4000,
            'tools': self.mcp_tools,
            'messages': messages,
            'temperature': 0.1
        }
        
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.base_url, headers=headers, json=payload) as response:
                        if response.status == 200:
                            return await response.json()
                        
                        # Handle retryable errors
                        elif response.status in [429, 529, 500, 502, 503, 504]:
                            error_text = await response.text()
                            if attempt < max_retries - 1:
                                # Exponential backoff with jitter
                                delay = (2 ** attempt) + random.uniform(0, 1)
                                print(f"Claude API error {response.status}, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                                await asyncio.sleep(delay)
                                continue
                            else:
                                raise Exception(f"Claude API error {response.status} (max retries exceeded): {error_text}")
                        
                        # Non-retryable errors
                        else:
                            error_text = await response.text()
                            raise Exception(f"Claude API error {response.status}: {error_text}")
                            
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    print(f"Claude API timeout, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise Exception("Claude API timeout (max retries exceeded)")
            
            except Exception as e:
                # Only retry for connection-related errors
                if "connection" in str(e).lower() and attempt < max_retries - 1:
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    print(f"Claude API connection error, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise
        
        raise Exception("Claude API call failed after all retries")
    
    async def analyze_protocol_steps_batch_async(self, step_texts: List[str], context: Optional[Dict] = None, batch_size: int = 5) -> List[Dict[str, Any]]:
        """
        Analyze multiple protocol steps in batches with concurrent processing.
        
        Args:
            step_texts: List of protocol step descriptions
            context: Optional context information
            batch_size: Number of steps to process concurrently per batch
            
        Returns:
            List of analysis results for each step
        """
        results = []
        
        # Process steps in batches to avoid overwhelming the API
        for i in range(0, len(step_texts), batch_size):
            batch = step_texts[i:i+batch_size]
            
            # Create concurrent tasks for this batch
            tasks = []
            for step_text in batch:
                task = asyncio.create_task(
                    self.analyze_protocol_step_with_mcp(step_text, context)
                )
                tasks.append(task)
            
            # Wait for all tasks in this batch to complete
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and handle exceptions
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    # Handle failed analysis
                    error_result = {
                        'success': False,
                        'error': str(result),
                        'step_text': batch[j],
                        'step_index': i + j
                    }
                    results.append(error_result)
                    print(f"Batch analysis failed for step {i + j}: {result}")
                else:
                    # Add step index for tracking
                    result['step_index'] = i + j
                    results.append(result)
            
            # Add delay between batches to respect rate limits
            if i + batch_size < len(step_texts):
                await asyncio.sleep(1.0)  # 1 second delay between batches
        
        return results
    
    async def _process_claude_response(self, claude_response: Dict[str, Any], step_text: str) -> Dict[str, Any]:
        """Process Claude's response and execute any tool calls."""
        
        result = {
            'sdrf_suggestions': {},
            'extracted_terms': [],
            'tools_used': []
        }
        
        content = claude_response.get('content', [])
        
        # Debug: log what Claude actually returned
        logger.info(f"Claude response content: {content}")
        
        for item in content:
            logger.info(f"Processing content item: {item}")
            
            if item.get('type') == 'tool_use':
                # Execute the tool call
                tool_name = item.get('name')
                tool_input = item.get('input', {})
                
                logger.info(f"Executing tool: {tool_name} with input: {tool_input}")
                
                try:
                    tool_result = await self._execute_tool(tool_name, tool_input)
                    result['tools_used'].append({
                        'tool': tool_name,
                        'input': tool_input,
                        'result': tool_result
                    })
                    
                    # Process tool results into SDRF suggestions
                    self._process_tool_result(tool_name, tool_result, result)
                    
                except Exception as e:
                    logger.error(f"Tool execution failed: {e}")
                    result['tools_used'].append({
                        'tool': tool_name,
                        'input': tool_input,
                        'error': str(e)
                    })
            
            elif item.get('type') == 'text':
                # Log text responses for debugging
                text_content = item.get('text', '')
                logger.info(f"Claude returned text content: {text_content[:200]}...")
                
                # Check if the text contains tool calls in a different format and parse them
                if 'search_unimod_modifications' in text_content or 'search_ontology' in text_content:
                    logger.warning("Claude returned tool calls in text format instead of tool_use format")
                    
                    # Try to extract and execute tool calls from text
                    import re
                    
                    # Look for search_unimod_modifications calls
                    unimod_pattern = r'search_unimod_modifications\(query="([^"]+)"'
                    unimod_matches = re.findall(unimod_pattern, text_content)
                    for query in unimod_matches:
                        try:
                            tool_result = await self._execute_tool('search_unimod_modifications', {
                                'query': query,
                                'include_metadata': True
                            })
                            result['tools_used'].append({
                                'tool': 'search_unimod_modifications',
                                'input': {'query': query, 'include_metadata': True},
                                'result': tool_result,
                                'source': 'text_parsed'
                            })
                            self._process_tool_result('search_unimod_modifications', tool_result, result)
                        except Exception as e:
                            logger.error(f"Failed to execute parsed tool call: {e}")
                    
                    # Look for search_ontology calls
                    ontology_pattern = r'search_ontology\(query="([^"]+)"'
                    ontology_matches = re.findall(ontology_pattern, text_content)
                    for query in ontology_matches:
                        try:
                            tool_result = await self._execute_tool('search_ontology', {
                                'query': query,
                                'ontology_types': ['chebi_compound', 'ms_vocabularies']
                            })
                            result['tools_used'].append({
                                'tool': 'search_ontology',
                                'input': {'query': query, 'ontology_types': ['chebi_compound', 'ms_vocabularies']},
                                'result': tool_result,
                                'source': 'text_parsed'
                            })
                            self._process_tool_result('search_ontology', tool_result, result)
                        except Exception as e:
                            logger.error(f"Failed to execute parsed tool call: {e}")
        
        # Note: Failsafe logic moved to main analyze function to run only after all turns complete
        return result
    
    def _execute_tool_sync(self, tool_name: str, tool_input: Dict[str, Any]) -> Any:
        """Execute an MCP tool synchronously."""
        
        # Import database access utilities directly
        from mcp_server.utils.term_matcher import OntologyTermMatcher
        from mcp_server.utils.nlp_processor import ProtocolStepAnalyzer
        
        try:
            if tool_name == "search_ontology":
                matcher = OntologyTermMatcher()
                query = tool_input["query"]
                ontology_types = tool_input.get("ontology_types", None)
                min_confidence = tool_input.get("min_confidence", 0.5)
                
                matches = matcher.match_terms([query], ontology_types, min_confidence)
                
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
                
                return results
                
            elif tool_name == "search_unimod_modifications":
                matcher = OntologyTermMatcher()
                query = tool_input["query"]
                include_metadata = tool_input.get("include_metadata", True)
                
                matches = matcher.match_terms([query], ["unimod"], 0.4)
                
                results = []
                for match in matches:
                    result = {
                        "name": match.ontology_name,
                        "accession": match.accession,
                        "confidence": match.confidence,
                        "match_type": match.match_type
                    }
                    
                    if include_metadata:
                        # Get the actual UniMod record for comprehensive metadata
                        try:
                            from cc.models import Unimod
                            unimod_record = Unimod.objects.get(accession=match.accession)
                            
                            # Parse additional_data for comprehensive metadata
                            if unimod_record.additional_data:
                                additional_data = unimod_record.additional_data
                                metadata_dict = {}
                                
                                # Convert list format to dictionary
                                if isinstance(additional_data, list):
                                    for item in additional_data:
                                        if isinstance(item, dict) and 'id' in item and 'description' in item:
                                            metadata_dict[item['id']] = item['description']
                                
                                # Extract key metadata fields
                                if 'delta_mono_mass' in metadata_dict:
                                    result["monoisotopic_mass"] = metadata_dict['delta_mono_mass']
                                
                                if 'delta_composition' in metadata_dict:
                                    result["chemical_formula"] = metadata_dict['delta_composition']
                                
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
                                
                                if target_sites:
                                    # Filter to commonly modified amino acids for this modification
                                    # Remove uncommon/experimental targets, keep only well-established ones
                                    valid_sites = []
                                    for site in set(target_sites):
                                        if len(site) == 1 and site.isalpha():  # Single letter amino acids only
                                            valid_sites.append(site)
                                    
                                    if valid_sites:
                                        # Sort and limit to most common targets (max 5 for readability)
                                        sorted_sites = sorted(valid_sites)
                                        if len(sorted_sites) > 5:
                                            # For modifications with many targets, keep most common ones
                                            common_targets = {
                                                'Phospho': ['S', 'T', 'Y'],
                                                'Acetyl': ['K'],
                                                'Methyl': ['K', 'R'],
                                                'Oxidation': ['M']
                                            }
                                            mod_name = result.get('name', '')
                                            if mod_name in common_targets:
                                                result["target_amino_acids"] = ",".join(common_targets[mod_name])
                                            else:
                                                result["target_amino_acids"] = ",".join(sorted_sites[:5])
                                        else:
                                            result["target_amino_acids"] = ",".join(sorted_sites)
                                
                                if positions:
                                    # Remove duplicates and use first unique position
                                    unique_positions = list(dict.fromkeys(positions))  # Preserves order, removes duplicates
                                    result["position"] = unique_positions[0]
                                
                                if classifications:
                                    # Remove duplicates from classifications and map to proper SDRF modification types
                                    unique_classifications = list(dict.fromkeys(classifications))
                                    classification = unique_classifications[0].lower()
                                    if 'post-translational' in classification or 'ptm' in classification:
                                        result["modification_type"] = "Variable"  # Most PTMs are variable
                                    elif 'chemical' in classification or 'artifact' in classification:
                                        result["modification_type"] = "Fixed"     # Chemical modifications often fixed
                                    else:
                                        result["modification_type"] = "Variable"  # Default to variable
                                
                                # Store raw metadata for debugging
                                result["raw_metadata"] = metadata_dict
                            
                        except Exception as e:
                            # Fallback to basic metadata from match
                            if match.chemical_formula:
                                result["chemical_formula"] = match.chemical_formula
                            if match.mass_info:
                                result["monoisotopic_mass"] = match.mass_info
                            if match.target_info:
                                result["target_amino_acids"] = match.target_info
                        
                        # Create comprehensive SDRF key-value format
                        key_value_parts = [f"NT={result['name']}", f"AC={result['accession']}"]
                        
                        # Add target amino acids (required for modifications)
                        if result.get("target_amino_acids"):
                            key_value_parts.append(f"TA={result['target_amino_acids']}")
                        
                        # Add modification type if available
                        if result.get("modification_type"):
                            key_value_parts.append(f"MT={result['modification_type']}")
                        
                        # Add position if available (remove duplicates)
                        if result.get("position"):
                            position_value = result['position']
                            # Remove duplicates from comma-separated positions
                            if ',' in position_value:
                                positions = [p.strip() for p in position_value.split(',')]
                                unique_positions = list(dict.fromkeys(positions))
                                position_value = ','.join(unique_positions)
                            key_value_parts.append(f"PP={position_value}")
                        elif "N-term" in result['name'] or "C-term" in result['name']:
                            # Infer position from modification name
                            if "N-term" in result['name']:
                                key_value_parts.append("PP=Any N-term")
                            else:
                                key_value_parts.append("PP=Any C-term")
                        else:
                            # Default position
                            key_value_parts.append("PP=Anywhere")
                        
                        # Add monoisotopic mass
                        if result.get("monoisotopic_mass"):
                            key_value_parts.append(f"MM={result['monoisotopic_mass']}")
                        
                        # Add chemical formula if available (not part of key-value but useful metadata)
                        if result.get("chemical_formula"):
                            result["chemical_formula"] = result["chemical_formula"]
                        
                        result["sdrf_format"] = ";".join(key_value_parts)
                    
                    results.append(result)
                
                return results
                
            elif tool_name == "extract_protocol_terms":
                analyzer = ProtocolStepAnalyzer()
                text = tool_input["text"]
                
                extracted_terms = analyzer.analyze_step_text(text)
                
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
                
                return results
                
            elif tool_name == "validate_sdrf_format":
                sdrf_column = tool_input["sdrf_column"]
                value = tool_input["value"]
                
                validation_result = {
                    "valid": True,
                    "issues": [],
                    "suggestions": []
                }
                
                # Add basic SDRF validation
                if sdrf_column == "modification parameters":
                    if "NT=" not in value or "AC=" not in value:
                        validation_result["valid"] = False
                        validation_result["issues"].append("Missing required NT= or AC= in modification parameters")
                
                return validation_result
                
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
                
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            raise
    
    async def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Any:
        """Execute an MCP tool by calling the sync version in a thread."""
        import asyncio
        import concurrent.futures
        
        # Use ThreadPoolExecutor to avoid CurrentThreadExecutor issues
        loop = asyncio.get_event_loop()
        
        # Execute the sync function in a separate thread
        def run_sync_tool():
            return self._execute_tool_sync(tool_name, tool_input)
        
        # Use run_in_executor to avoid threading conflicts
        return await loop.run_in_executor(None, run_sync_tool)
    
    def _process_tool_result(self, tool_name: str, tool_result: Any, result: Dict[str, Any]):
        """Process tool results into SDRF suggestions format."""
        
        if tool_name == "extract_protocol_terms" and tool_result:
            result['extracted_terms'] = tool_result
        
        elif tool_name == "search_ontology" and tool_result:
            for match in tool_result:
                ontology_type = match.get('ontology_type')
                
                # Map to SDRF column names
                sdrf_column_mapping = {
                    'species': 'organism',
                    'tissue': 'organism part',
                    'human_disease': 'disease',
                    'mondo_disease': 'disease',
                    'uberon_anatomy': 'organism part',
                    'ncbi_taxonomy': 'organism',
                    'subcellular_location': 'subcellular localization',
                    'ms_vocabularies': self._map_ms_vocab_to_sdrf(match),
                    'psims_ontology': self._map_psims_to_sdrf(match),
                    'chebi_compound': 'varies'
                }
                
                sdrf_column = sdrf_column_mapping.get(ontology_type, ontology_type)
                
                if sdrf_column and sdrf_column != 'varies':
                    if sdrf_column not in result['sdrf_suggestions']:
                        result['sdrf_suggestions'][sdrf_column] = []
                    
                    suggestion = {
                        'ontology_type': ontology_type,
                        'ontology_name': match.get('ontology_name'),
                        'accession': match.get('accession'),
                        'confidence': match.get('confidence'),
                        'match_type': match.get('match_type'),
                        'extracted_term': match.get('extracted_term'),
                        'source': 'mcp_database_search'
                    }
                    
                    # Add rich metadata if available
                    for field in ['definition', 'synonyms', 'chemical_formula', 'mass_info', 'target_info']:
                        if match.get(field):
                            suggestion[field] = match[field]
                    
                    result['sdrf_suggestions'][sdrf_column].append(suggestion)
        
        elif tool_name == "search_unimod_modifications" and tool_result:
            if 'modification parameters' not in result['sdrf_suggestions']:
                result['sdrf_suggestions']['modification parameters'] = []
            
            for mod in tool_result:
                suggestion = {
                    'ontology_type': 'unimod',
                    'ontology_name': mod.get('name'),
                    'accession': mod.get('accession'),
                    'confidence': mod.get('confidence'),
                    'match_type': mod.get('match_type'),
                    'source': 'mcp_unimod_search'
                }
                
                # Add comprehensive UniMod metadata
                metadata_fields = [
                    'monoisotopic_mass', 'chemical_formula', 'target_amino_acids', 
                    'modification_type', 'position'
                ]
                for field in metadata_fields:
                    if mod.get(field):
                        suggestion[field] = mod[field]
                
                # Add SDRF key-value format (comprehensive)
                if mod.get('sdrf_format'):
                    suggestion['sdrf_format'] = mod['sdrf_format']
                    suggestion['key_value_format'] = mod['sdrf_format']  # Backward compatibility
                else:
                    # Fallback: create basic format if not provided
                    basic_format = f"NT={mod.get('name', '')};AC={mod.get('accession', '')}"
                    if mod.get('target_amino_acids'):
                        basic_format += f";TA={mod['target_amino_acids']}"
                    if mod.get('monoisotopic_mass'):
                        basic_format += f";MM={mod['monoisotopic_mass']}"
                    suggestion['sdrf_format'] = basic_format
                    suggestion['key_value_format'] = basic_format
                
                # Add additional metadata for display/debugging
                suggestion['metadata_completeness'] = {
                    'has_target_aa': bool(mod.get('target_amino_acids')),
                    'has_mass': bool(mod.get('monoisotopic_mass')),
                    'has_formula': bool(mod.get('chemical_formula')),
                    'has_position': bool(mod.get('position')),
                    'has_type': bool(mod.get('modification_type'))
                }
                
                result['sdrf_suggestions']['modification parameters'].append(suggestion)
    
    def _map_ms_vocab_to_sdrf(self, match: Dict[str, Any]) -> str:
        """Map MS vocabulary terms to SDRF columns."""
        # This would need to be implemented based on the term_type field
        # For now, return a default
        return 'instrument'
    
    def _map_psims_to_sdrf(self, match: Dict[str, Any]) -> str:
        """Map PSI-MS ontology terms to SDRF columns."""
        # This would need to be implemented based on the category field
        # For now, return a default
        return 'instrument'

class SyncMCPClaudeClient:
    """Synchronous wrapper for the MCP Claude client."""
    
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.async_client = MCPClaudeClient(api_key, model)
    
    def analyze_protocol_step_enhanced(self, step_text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """Synchronous version of MCP Claude analysis."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.async_client.analyze_protocol_step_with_mcp(step_text, context)
            )
        finally:
            loop.close()
    
    def execute_tool_sync(self, tool_name: str, tool_input: Dict[str, Any]) -> Any:
        """Synchronous tool execution for testing."""
        return self.async_client._execute_tool_sync(tool_name, tool_input)
    
    def analyze_protocol_steps_batch(self, step_texts: List[str], context: Optional[Dict] = None, batch_size: int = 5) -> List[Dict[str, Any]]:
        """
        Analyze multiple protocol steps in batches for efficiency.
        
        Args:
            step_texts: List of protocol step descriptions
            context: Optional context information
            batch_size: Number of steps to process per batch
            
        Returns:
            List of analysis results for each step
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.async_client.analyze_protocol_steps_batch_async(step_texts, context, batch_size)
            )
        finally:
            loop.close()