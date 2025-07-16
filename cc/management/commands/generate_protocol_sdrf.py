"""
Django management command to generate SDRF suggestions for all steps in a protocol.

Usage:
    python manage.py generate_protocol_sdrf <protocol_id> [options]

Options:
    --use-ai: Enable AI-powered term extraction and analysis
    --output-format: json|csv|table (default: table)
    --min-confidence: Minimum confidence threshold (default: 0.4)
    --save-to-file: Save results to file
    --step-ids: Comma-separated list of specific step IDs to process
"""

import json
import csv
import os
import sys
from typing import Dict, List, Any, Optional
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from cc.models import ProtocolModel, ProtocolStep
from mcp_server.tools.protocol_analyzer import ProtocolAnalyzer


class Command(BaseCommand):
    help = 'Generate SDRF suggestions for all steps in a protocol'

    def add_arguments(self, parser):
        parser.add_argument(
            'protocol_id',
            type=int,
            help='Protocol ID to process'
        )
        parser.add_argument(
            '--use-ai',
            action='store_true',
            help='Enable AI-powered term extraction and analysis'
        )
        parser.add_argument(
            '--output-format',
            choices=['json', 'csv', 'table'],
            default='table',
            help='Output format (default: table)'
        )
        parser.add_argument(
            '--min-confidence',
            type=float,
            default=0.4,
            help='Minimum confidence threshold for suggestions (default: 0.4)'
        )
        parser.add_argument(
            '--save-to-file',
            type=str,
            help='Save results to specified file'
        )
        parser.add_argument(
            '--step-ids',
            type=str,
            help='Comma-separated list of specific step IDs to process'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose output with detailed extraction information'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=3,
            help='Number of steps to process in parallel batches (default: 3)'
        )
        parser.add_argument(
            '--use-batch',
            action='store_true',
            help='Use batch processing for better performance with AI analysis'
        )

    def handle(self, *args, **options):
        protocol_id = options['protocol_id']
        use_ai = options['use_ai']
        output_format = options['output_format']
        min_confidence = options['min_confidence']
        save_to_file = options['save_to_file']
        step_ids = options['step_ids']
        verbose = options['verbose']
        batch_size = options['batch_size']
        use_batch = options['use_batch']

        try:
            # Get protocol
            protocol = ProtocolModel.objects.get(id=protocol_id)
            self.stdout.write(f"Processing protocol: {protocol.protocol_title}")
            
            steps = protocol.get_step_in_order()
            
            self.stdout.write(f"Found {len(steps)} steps to process")
            
            # Initialize analyzer
            analyzer_type = "AI-enhanced" if use_ai else "Standard"
            self.stdout.write(f"Using {analyzer_type} analysis")
            
            # Get API key for AI analysis
            api_key = None
            if use_ai:
                api_key = os.getenv('ANTHROPIC_API_KEY')
                if not api_key:
                    self.stdout.write(
                        self.style.WARNING(
                            "ANTHROPIC_API_KEY not found. Falling back to standard analysis."
                        )
                    )
                    use_ai = False
            
            # Initialize protocol analyzer
            analyzer = ProtocolAnalyzer(
                use_anthropic=use_ai,
                anthropic_api_key=api_key
            )
            
            # Process steps - use batch processing if requested and AI is enabled
            results = []
            if use_batch and use_ai and len(steps) > 1:
                self.stdout.write(f"Using batch processing with batch size: {batch_size}")
                
                # Get step IDs for batch processing
                step_ids_list = [step.id for step in steps]
                batch_results = analyzer.analyze_protocol_steps_batch(step_ids_list, batch_size=batch_size)
                
                # Process batch results
                for step_index, (step, batch_result) in enumerate(zip(steps, batch_results), 1):
                    if batch_result.get('success'):
                        step_result = self._process_step_suggestions(
                            step, batch_result, min_confidence, verbose, step_index
                        )
                        results.append(step_result)
                        
                        if verbose:
                            self._print_step_details(step_result)
                        else:
                            self.stdout.write(f"Step {step_index}: Found {len(step_result.get('sdrf_suggestions', {}))} SDRF columns")
                    else:
                        error_msg = batch_result.get('error', 'Unknown error')
                        self.stdout.write(self.style.ERROR(f"Step {step_index}: {error_msg}"))
                        
                        results.append({
                            'step_id': step.id,
                            'step_order': step_index,
                            'step_description': step.step_description,
                            'success': False,
                            'error': error_msg
                        })
            else:
                # Individual processing
                for step_index, step in enumerate(steps, 1):
                    self.stdout.write(f"\nProcessing Step {step_index}: {step.step_description[:80]}...")
                    
                    try:
                        # Get SDRF suggestions for this step
                        suggestions = analyzer.get_step_sdrf_suggestions(step.id)
                        
                        if suggestions.get('success'):
                            step_result = self._process_step_suggestions(
                                step, suggestions, min_confidence, verbose, step_index
                            )
                            results.append(step_result)
                            
                            if verbose:
                                self._print_step_details(step_result)
                            else:
                                self.stdout.write(f"  → Found {len(step_result.get('sdrf_suggestions', {}))} SDRF columns")
                        else:
                            error_msg = suggestions.get('error', 'Unknown error')
                            self.stdout.write(
                                self.style.ERROR(f"  → Failed: {error_msg}")
                            )
                            
                            # Add error result
                            results.append({
                                'step_id': step.id,
                                'step_order': step_index,
                                'step_description': step.step_description,
                                'success': False,
                                'error': error_msg
                            })
                    
                    except Exception as e:
                        error_msg = f"Step processing failed: {str(e)}"
                        self.stdout.write(self.style.ERROR(f"  → {error_msg}"))
                        
                        results.append({
                            'step_id': step.id,
                            'step_order': step_index,
                            'step_description': step.step_description,
                            'success': False,
                            'error': error_msg
                        })
            
            # Generate output
            self._generate_output(
                results, protocol, output_format, save_to_file, analyzer_type
            )
            
        except ProtocolModel.DoesNotExist:
            raise CommandError(f"Protocol with ID {protocol_id} does not exist")
        except Exception as e:
            raise CommandError(f"Command failed: {str(e)}")

    def _process_step_suggestions(self, step: ProtocolStep, suggestions: Dict, 
                                 min_confidence: float, verbose: bool, step_order: int) -> Dict:
        """Process SDRF suggestions for a single step."""
        
        step_result = {
            'step_id': step.id,
            'step_order': step_order,
            'step_description': step.step_description,
            'success': True,
            'analyzer_type': suggestions.get('analysis_metadata', {}).get('analyzer_type', 'unknown'),
            'sdrf_suggestions': {},
            'extracted_terms': [],
            'statistics': {
                'total_terms': 0,
                'total_suggestions': 0,
                'high_confidence_suggestions': 0,
                'sdrf_columns_covered': 0
            }
        }
        
        # Process SDRF suggestions
        sdrf_suggestions = suggestions.get('sdrf_suggestions', {})
        for column, suggestions_list in sdrf_suggestions.items():
            # Filter by confidence
            filtered_suggestions = [
                s for s in suggestions_list 
                if s.get('confidence', 0) >= min_confidence
            ]
            
            if filtered_suggestions:
                step_result['sdrf_suggestions'][column] = filtered_suggestions
                step_result['statistics']['total_suggestions'] += len(filtered_suggestions)
                step_result['statistics']['high_confidence_suggestions'] += len([
                    s for s in filtered_suggestions if s.get('confidence', 0) >= 0.7
                ])
        
        # Process extracted terms
        extracted_terms = suggestions.get('extracted_terms', [])
        for term in extracted_terms:
            if hasattr(term, 'to_dict'):
                step_result['extracted_terms'].append(term.to_dict())
            else:
                step_result['extracted_terms'].append(term)
        
        # Update statistics
        step_result['statistics']['total_terms'] = len(extracted_terms)
        step_result['statistics']['sdrf_columns_covered'] = len(step_result['sdrf_suggestions'])
        
        return step_result

    def _print_step_details(self, step_result: Dict):
        """Print detailed information about a step's results."""
        self.stdout.write(f"  Step Details:")
        self.stdout.write(f"    Analyzer: {step_result['analyzer_type']}")
        self.stdout.write(f"    Extracted terms: {step_result['statistics']['total_terms']}")
        self.stdout.write(f"    SDRF columns: {step_result['statistics']['sdrf_columns_covered']}")
        self.stdout.write(f"    Total suggestions: {step_result['statistics']['total_suggestions']}")
        self.stdout.write(f"    High confidence: {step_result['statistics']['high_confidence_suggestions']}")
        
        # Show SDRF suggestions
        for column, suggestions in step_result['sdrf_suggestions'].items():
            self.stdout.write(f"    {column}:")
            for suggestion in suggestions[:3]:  # Show top 3
                conf = suggestion.get('confidence', 0)
                name = suggestion.get('ontology_name', suggestion.get('term', 'Unknown'))
                accession = suggestion.get('accession', '')
                self.stdout.write(f"      - {name} ({accession}) [{conf:.3f}]")

    def _generate_output(self, results: List[Dict], protocol: ProtocolModel, 
                        output_format: str, save_to_file: Optional[str], 
                        analyzer_type: str):
        """Generate output in the specified format."""
        
        if output_format == 'json':
            self._output_json(results, protocol, save_to_file, analyzer_type)
        elif output_format == 'csv':
            self._output_csv(results, protocol, save_to_file, analyzer_type)
        else:  # table
            self._output_table(results, protocol, save_to_file, analyzer_type)

    def _output_json(self, results: List[Dict], protocol: ProtocolModel, 
                    save_to_file: Optional[str], analyzer_type: str):
        """Output results as JSON."""
        output_data = {
            'protocol_id': protocol.id,
            'protocol_title': protocol.protocol_title,
            'analyzer_type': analyzer_type,
            'total_steps': len(results),
            'successful_steps': len([r for r in results if r.get('success')]),
            'steps': results
        }
        
        json_output = json.dumps(output_data, indent=2)
        
        if save_to_file:
            with open(save_to_file, 'w') as f:
                f.write(json_output)
            self.stdout.write(f"\nResults saved to: {save_to_file}")
        else:
            self.stdout.write("\n" + json_output)

    def _output_csv(self, results: List[Dict], protocol: ProtocolModel, 
                   save_to_file: Optional[str], analyzer_type: str):
        """Output results as CSV."""
        output_file = save_to_file or f'protocol_{protocol.id}_sdrf_suggestions.csv'
        
        with open(output_file, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow([
                'Step ID', 'Step Description', 'Success',
                'Analyzer Type', 'SDRF Columns', 'Total Suggestions', 
                'High Confidence Suggestions', 'Extracted Terms'
            ])
            
            # Write data rows
            for result in results:
                writer.writerow([
                    result['step_id'],
                    result['step_description'][:100],  # Truncate for CSV
                    result['success'],
                    result.get('analyzer_type', 'unknown'),
                    result.get('statistics', {}).get('sdrf_columns_covered', 0),
                    result.get('statistics', {}).get('total_suggestions', 0),
                    result.get('statistics', {}).get('high_confidence_suggestions', 0),
                    result.get('statistics', {}).get('total_terms', 0)
                ])
        
        self.stdout.write(f"\nCSV results saved to: {output_file}")

    def _output_table(self, results: List[Dict], protocol: ProtocolModel, 
                     save_to_file: Optional[str], analyzer_type: str):
        """Output results as formatted table."""
        
        # Summary
        successful_steps = [r for r in results if r.get('success')]
        total_columns = sum(r.get('statistics', {}).get('sdrf_columns_covered', 0) 
                           for r in successful_steps)
        total_suggestions = sum(r.get('statistics', {}).get('total_suggestions', 0) 
                               for r in successful_steps)
        
        table_output = []
        table_output.append(f"\n{'='*80}")
        table_output.append(f"SDRF SUGGESTIONS REPORT")
        table_output.append(f"{'='*80}")
        table_output.append(f"Protocol: {protocol.protocol_title} (ID: {protocol.id})")
        table_output.append(f"Analyzer: {analyzer_type}")
        table_output.append(f"Total Steps: {len(results)}")
        table_output.append(f"Successful Steps: {len(successful_steps)}")
        table_output.append(f"Total SDRF Columns: {total_columns}")
        table_output.append(f"Total Suggestions: {total_suggestions}")
        table_output.append(f"{'='*80}")
        
        # Step details
        for result in results:
            table_output.append(f"\nSTEP {result['step_order']} (ID: {result['step_id']})")
            table_output.append(f"Description: {result['step_description'][:100]}...")
            
            if result['success']:
                stats = result.get('statistics', {})
                table_output.append(f"Analyzer: {result.get('analyzer_type', 'unknown')}")
                table_output.append(f"Extracted Terms: {stats.get('total_terms', 0)}")
                table_output.append(f"SDRF Columns: {stats.get('sdrf_columns_covered', 0)}")
                table_output.append(f"Suggestions: {stats.get('total_suggestions', 0)} ({stats.get('high_confidence_suggestions', 0)} high confidence)")
                
                # Show SDRF suggestions
                for column, suggestions in result.get('sdrf_suggestions', {}).items():
                    table_output.append(f"  {column}:")
                    for i, suggestion in enumerate(suggestions[:3]):  # Top 3
                        conf = suggestion.get('confidence', 0)
                        name = suggestion.get('ontology_name', suggestion.get('term', 'Unknown'))
                        accession = suggestion.get('accession', '')
                        table_output.append(f"    {i+1}. {name} ({accession}) [{conf:.3f}]")
                    if len(suggestions) > 3:
                        table_output.append(f"    ... and {len(suggestions) - 3} more")
            else:
                table_output.append(f"ERROR: {result.get('error', 'Unknown error')}")
            
            table_output.append("-" * 80)
        
        output_text = "\n".join(table_output)
        
        if save_to_file:
            with open(save_to_file, 'w') as f:
                f.write(output_text)
            self.stdout.write(f"\nTable results saved to: {save_to_file}")
        else:
            self.stdout.write(output_text)