"""
Django views for MCP SDRF functionality.

These views integrate the MCP SDRF tools directly into the Django REST API.
"""

import json
import os
import uuid

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_rq import get_queue

from cc.rq_tasks import analyze_protocol_step_task, generate_sdrf_metadata_task
from mcp_server.tools.protocol_analyzer import ProtocolAnalyzer
from mcp_server.tools.sdrf_generator import SDRFMetadataGenerator
from mcp_server.utils.term_matcher import OntologyTermMatcher


class MCPProtocolAnalysisView(View):
    """Base view for MCP protocol analysis functionality."""

    def __init__(self):
        super().__init__()
        # Initialize with default (regex-based) analyzer
        self.protocol_analyzer = ProtocolAnalyzer()
        self.sdrf_generator = SDRFMetadataGenerator()
        self.term_matcher = OntologyTermMatcher()

    def get_analyzer(self, request_data):
        """Get appropriate analyzer based on request parameters."""
        use_anthropic = request_data.get('use_anthropic', False)
        anthropic_api_key = request_data.get('anthropic_api_key')

        if use_anthropic:
            try:
                # Use environment variable if no key provided
                api_key = anthropic_api_key or os.getenv('ANTHROPIC_API_KEY')
                if api_key:
                    return ProtocolAnalyzer(use_anthropic=True, anthropic_api_key=api_key)
                else:
                    print("No Anthropic API key available")
                    return self.protocol_analyzer
            except Exception as e:
                # Fall back to default analyzer if Anthropic fails
                print(f"Anthropic analyzer initialization failed: {e}")
                return self.protocol_analyzer

        return self.protocol_analyzer


@method_decorator(csrf_exempt, name='dispatch')
class AnalyzeProtocolStepView(MCPProtocolAnalysisView):
    """Analyze a protocol step and extract SDRF suggestions."""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            step_id = data.get('step_id')
            use_async = data.get('use_async', True)  # Default to async
            
            if not step_id:
                return JsonResponse({
                    'success': False,
                    'error': 'step_id is required'
                }, status=400)
            
            # Check if we should use async processing
            if use_async:
                # Use RQ task for async processing
                # Generate unique task ID
                task_id = str(uuid.uuid4())
                
                # Get user ID for WebSocket updates
                user_id = request.user.id if request.user.is_authenticated else None
                
                # Get queue and enqueue task
                queue = get_queue('mcp')
                job = queue.enqueue(
                    analyze_protocol_step_task,
                    task_id=task_id,
                    step_id=step_id,
                    use_anthropic=data.get('use_anthropic', False),
                    user_id=user_id,
                    job_timeout='30m'
                )
                
                return JsonResponse({
                    'success': True,
                    'task_id': task_id,
                    'job_id': job.id,
                    'step_id': step_id,
                    'status': 'queued',
                    'message': 'Analysis task queued successfully. Use WebSocket for progress updates.'
                })
            
            # Synchronous processing (fallback)
            # Get user token from request (if authenticated)
            user_token = None
            if request.user.is_authenticated:
                user_token = str(request.user.id)  # Use user ID as token
            
            # Get appropriate analyzer based on request
            analyzer = self.get_analyzer(data)
            print(f"DEBUG: Using analyzer with use_anthropic={getattr(analyzer, 'use_anthropic', False)}")
            
            # Analyze the step once to avoid duplicate API calls
            analysis = analyzer.analyze_protocol_step(step_id, user_token)
            
            if analysis.get("success"):
                # Generate SDRF suggestions from the analysis
                sdrf_suggestions = analyzer._generate_sdrf_suggestions(analysis)
                
                # Build the main result
                result = {
                    "success": True,
                    "step_id": step_id,
                    "sdrf_suggestions": sdrf_suggestions,
                    "analysis_summary": {
                        "total_matches": len(analysis.get('ontology_matches', [])),
                        "high_confidence_matches": analysis.get('analysis_metadata', {}).get('high_confidence_matches', 0),
                        "sdrf_specific_suggestions": sum(len(suggestions) for suggestions in sdrf_suggestions.values())
                    },
                    "detailed_analysis": {
                        "extracted_terms": analysis.get("extracted_terms", []),
                        "ontology_matches": analysis.get("ontology_matches", []),
                        "categorized_matches": analysis.get("categorized_matches", {}),
                        "analysis_metadata": analysis.get("analysis_metadata", {})
                    }
                }
                
                # Extract and preserve important fields from the analysis
                analysis_metadata = analysis.get("analysis_metadata", {})
                print(f"DEBUG: analysis_metadata = {analysis_metadata}")
                if "analyzer_type" in analysis_metadata:
                    result["analyzer_type"] = analysis_metadata["analyzer_type"]
                    print(f"DEBUG: Set analyzer_type to {analysis_metadata['analyzer_type']}")
                
                # Include Claude analysis if present
                if "claude_analysis" in analysis:
                    result["claude_analysis"] = analysis["claude_analysis"]
                
                # Include enhanced SDRF suggestions if present
                if "sdrf_suggestions_enhanced" in analysis:
                    result["sdrf_suggestions_enhanced"] = analysis["sdrf_suggestions_enhanced"]
            else:
                result = analysis  # Return the error result
            
            return JsonResponse(result)
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Analysis failed: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class MatchOntologyTermsView(MCPProtocolAnalysisView):
    """Match terms to ontology vocabularies."""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            terms = data.get('terms', [])
            ontology_types = data.get('ontology_types')
            min_confidence = data.get('min_confidence', 0.5)
            
            if not terms:
                return JsonResponse({
                    'success': False,
                    'error': 'terms array is required'
                }, status=400)
            
            # Match terms
            matches = self.term_matcher.match_terms(terms, ontology_types, min_confidence)
            
            # Convert MatchResult objects to dicts
            match_dicts = []
            for match in matches:
                match_dicts.append({
                    "ontology_type": match.ontology_type,
                    "ontology_id": match.ontology_id,
                    "ontology_name": match.ontology_name,
                    "accession": match.accession,
                    "confidence": match.confidence,
                    "match_type": match.match_type,
                    "extracted_term": match.extracted_term
                })
            
            return JsonResponse({
                "success": True,
                "total_terms": len(terms),
                "total_matches": len(match_dicts),
                "matches": match_dicts,
                "min_confidence": min_confidence
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Term matching failed: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class GenerateSDRFMetadataView(MCPProtocolAnalysisView):
    """Generate SDRF metadata columns from protocol analysis."""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            step_id = data.get('step_id')
            auto_create = data.get('auto_create', False)
            use_async = data.get('use_async', True)  # Default to async
            
            if not step_id:
                return JsonResponse({
                    'success': False,
                    'error': 'step_id is required'
                }, status=400)
            
            # Check if we should use async processing
            if use_async:
                # Use RQ task for async processing
                # Generate unique task ID
                task_id = str(uuid.uuid4())
                
                # Get user ID for WebSocket updates
                user_id = request.user.id if request.user.is_authenticated else None
                
                # Get queue and enqueue task
                queue = get_queue('mcp')
                job = queue.enqueue(
                    generate_sdrf_metadata_task,
                    task_id=task_id,
                    step_id=step_id,
                    use_anthropic=data.get('use_anthropic', False),
                    user_id=user_id,
                    job_timeout='30m'
                )
                
                return JsonResponse({
                    'success': True,
                    'task_id': task_id,
                    'job_id': job.id,
                    'step_id': step_id,
                    'status': 'queued',
                    'message': 'Metadata generation task queued successfully. Use WebSocket for progress updates.'
                })
            
            # Synchronous processing (fallback)
            # Get user token from request
            user_token = None
            if request.user.is_authenticated:
                user_token = str(request.user.id)
            
            # First analyze the step to get SDRF suggestions
            suggestions = self.protocol_analyzer.get_step_sdrf_suggestions(step_id, user_token)
            
            if not suggestions.get("success"):
                return JsonResponse(suggestions)
            
            # Generate metadata columns from suggestions
            result = self.sdrf_generator.generate_metadata_columns(
                step_id, 
                suggestions.get("sdrf_suggestions", {}),
                user_token,
                auto_create
            )
            
            # Add original analysis information
            if suggestions.get("analysis_summary"):
                result["analysis_summary"] = suggestions["analysis_summary"]
            
            return JsonResponse(result)
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Metadata generation failed: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ValidateSDRFComplianceView(MCPProtocolAnalysisView):
    """Validate SDRF compliance for protocol metadata."""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            step_id = data.get('step_id')
            
            if not step_id:
                return JsonResponse({
                    'success': False,
                    'error': 'step_id is required'
                }, status=400)
            
            # Get user token from request
            user_token = None
            if request.user.is_authenticated:
                user_token = str(request.user.id)
            
            result = self.sdrf_generator.validate_sdrf_compliance(step_id, user_token)
            return JsonResponse(result)
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Validation failed: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class ExportSDRFFileView(MCPProtocolAnalysisView):
    """Export protocol metadata as SDRF file."""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            protocol_id = data.get('protocol_id')
            
            if not protocol_id:
                return JsonResponse({
                    'success': False,
                    'error': 'protocol_id is required'
                }, status=400)
            
            # Get user token from request
            user_token = None
            if request.user.is_authenticated:
                user_token = str(request.user.id)
            
            result = self.sdrf_generator.export_sdrf_file(protocol_id, user_token)
            return JsonResponse(result)
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Export failed: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class MCPTaskStatusView(View):
    """Get status of MCP async tasks."""
    
    def get(self, request):
        task_id = request.GET.get('task_id')
        job_id = request.GET.get('job_id')
        
        if not task_id and not job_id:
            return JsonResponse({
                'success': False,
                'error': 'task_id or job_id is required'
            }, status=400)
        
        try:
            from django_rq import get_queue
            from rq.job import Job

            queue = get_queue('mcp')
            
            if job_id:
                try:
                    job = Job.fetch(job_id, connection=queue.connection)
                    
                    return JsonResponse({
                        'success': True,
                        'job_id': job.id,
                        'task_id': task_id,
                        'status': job.get_status(),
                        'created_at': job.created_at.isoformat() if job.created_at else None,
                        'started_at': job.started_at.isoformat() if job.started_at else None,
                        'ended_at': job.ended_at.isoformat() if job.ended_at else None,
                        'result': job.result if job.is_finished else None,
                        'failure_reason': str(job.exc_info) if job.is_failed else None,
                        'meta': job.meta
                    })
                except Exception as e:
                    return JsonResponse({
                        'success': False,
                        'error': f'Job not found: {str(e)}'
                    }, status=404)
            
            # If only task_id is provided, return basic status
            return JsonResponse({
                'success': True,
                'task_id': task_id,
                'message': 'Use WebSocket connection for real-time progress updates'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Status check failed: {str(e)}'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class AnalyzeFullProtocolView(MCPProtocolAnalysisView):
    """Analyze all steps in a protocol comprehensively."""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            protocol_id = data.get('protocol_id')
            use_async = data.get('use_async', True)  # Default to async
            
            if not protocol_id:
                return JsonResponse({
                    'success': False,
                    'error': 'protocol_id is required'
                }, status=400)
            
            # Check if we should use async processing
            if use_async:
                # Use RQ task for async processing
                # Generate unique task ID
                task_id = str(uuid.uuid4())
                
                # Get user ID for WebSocket updates
                user_id = request.user.id if request.user.is_authenticated else None
                
                # Get queue and enqueue task
                queue = get_queue('mcp')
                job = queue.enqueue(
                    analyze_protocol_step_task,
                    task_id=task_id,
                    step_id=protocol_id,
                    use_anthropic=data.get('use_anthropic', False),
                    user_id=user_id,
                    job_timeout='60m'
                )
                
                return JsonResponse({
                    'success': True,
                    'task_id': task_id,
                    'job_id': job.id,
                    'protocol_id': protocol_id,
                    'status': 'queued',
                    'message': 'Full protocol analysis task queued successfully. Use WebSocket for progress updates.'
                })
            
            # Synchronous processing (fallback)
            # Get user token from request
            user_token = None
            if request.user.is_authenticated:
                user_token = str(request.user.id)
            
            # Analyze the protocol
            analysis = self.protocol_analyzer.analyze_protocol(protocol_id, user_token)
            
            if not analysis.get("success"):
                return JsonResponse(analysis)
            
            # Generate SDRF suggestions for each step
            step_suggestions = {}
            for step_analysis in analysis.get("step_analyses", []):
                step_id = step_analysis["step_id"]
                suggestions = self.protocol_analyzer.get_step_sdrf_suggestions(step_id, user_token)
                if suggestions.get("success"):
                    step_suggestions[step_id] = suggestions.get("sdrf_suggestions", {})
            
            # Aggregate protocol-level SDRF suggestions
            protocol_sdrf_suggestions = self._aggregate_protocol_suggestions(step_suggestions)
            
            analysis["protocol_sdrf_suggestions"] = protocol_sdrf_suggestions
            analysis["step_sdrf_suggestions"] = step_suggestions
            
            return JsonResponse(analysis)
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Protocol analysis failed: {str(e)}'
            }, status=500)
    
    def _aggregate_protocol_suggestions(self, step_suggestions):
        """Aggregate SDRF suggestions across all protocol steps."""
        aggregated = {}
        
        for step_id, suggestions in step_suggestions.items():
            for sdrf_column, matches in suggestions.items():
                if sdrf_column not in aggregated:
                    aggregated[sdrf_column] = []
                
                # Add high-confidence matches
                for match in matches:
                    if match.get("confidence", 0) >= 0.7:
                        # Check if we already have this ontology term
                        existing = False
                        for existing_match in aggregated[sdrf_column]:
                            if (existing_match.get("ontology_id") == match.get("ontology_id") and 
                                existing_match.get("ontology_type") == match.get("ontology_type")):
                                # Update confidence if this one is higher
                                if match.get("confidence", 0) > existing_match.get("confidence", 0):
                                    existing_match.update(match)
                                existing = True
                                break
                        
                        if not existing:
                            aggregated[sdrf_column].append(match)
        
        # Sort each column by confidence
        for sdrf_column in aggregated:
            aggregated[sdrf_column].sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return aggregated


# API view versions using DRF
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_protocol_step_api(request):
    """DRF API view for protocol step analysis."""
    step_id = request.data.get('step_id')

    if not step_id:
        return Response({
            'success': False,
            'error': 'step_id is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        analyzer = ProtocolAnalyzer()
        user_token = str(request.user.id)

        result = analyzer.get_step_sdrf_suggestions(step_id, user_token)

        # Add detailed analysis
        if result.get("success"):
            analysis = analyzer.analyze_protocol_step(step_id, user_token)
            if analysis.get("success"):
                result["detailed_analysis"] = {
                    "extracted_terms": analysis.get("extracted_terms", []),
                    "ontology_matches": analysis.get("ontology_matches", []),
                    "categorized_matches": analysis.get("categorized_matches", {}),
                    "analysis_metadata": analysis.get("analysis_metadata", {})
                }

        return Response(result)

    except Exception as e:
        return Response({
            'success': False,
            'error': f'Analysis failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_sdrf_metadata_api(request):
    """DRF API view for SDRF metadata generation."""
    step_id = request.data.get('step_id')
    auto_create = request.data.get('auto_create', False)

    if not step_id:
        return Response({
            'success': False,
            'error': 'step_id is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        analyzer = ProtocolAnalyzer()
        generator = SDRFMetadataGenerator()
        user_token = str(request.user.id)

        # Get SDRF suggestions
        suggestions = analyzer.get_step_sdrf_suggestions(step_id, user_token)

        if not suggestions.get("success"):
            return Response(suggestions, status=status.HTTP_400_BAD_REQUEST)

        # Generate metadata columns
        result = generator.generate_metadata_columns(
            step_id,
            suggestions.get("sdrf_suggestions", {}),
            user_token,
            auto_create
        )

        return Response(result)

    except Exception as e:
        return Response({
            'success': False,
            'error': f'Metadata generation failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_analysis_task_status(request, task_id):
    """Get the status of an analysis task."""
    try:
        # Get RQ job for this task
        queue = get_queue('mcp')

        # Find job by task_id in job meta
        jobs = queue.get_jobs()
        target_job = None

        for job in jobs:
            if job.meta.get('task_id') == task_id:
                target_job = job
                break

        if not target_job:
            return Response({
                'success': False,
                'error': 'Task not found'
            }, status=status.HTTP_404_NOT_FOUND)

        # Get job status
        job_status = target_job.get_status()

        result = {
            'success': True,
            'task_id': task_id,
            'job_id': target_job.id,
            'status': job_status,
            'created_at': target_job.created_at.isoformat() if target_job.created_at else None,
            'started_at': target_job.started_at.isoformat() if target_job.started_at else None,
            'ended_at': target_job.ended_at.isoformat() if target_job.ended_at else None,
        }

        # Add result if job is finished
        if job_status == 'finished':
            result['result'] = target_job.result
        elif job_status == 'failed':
            result['error'] = str(target_job.exc_info) if target_job.exc_info else 'Unknown error'

        # Add progress info if available
        if hasattr(target_job, 'meta') and target_job.meta:
            result['meta'] = target_job.meta

        return Response(result)

    except Exception as e:
        return Response({
            'success': False,
            'error': f'Failed to get task status: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
