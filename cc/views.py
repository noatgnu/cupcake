from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.db import connection
from django.conf import settings
from drf_chunked_upload.exceptions import ChunkedUploadError
from drf_chunked_upload.views import ChunkedUploadView
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import FileUploadParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated

# Create your views here.

from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
import requests
from bs4 import BeautifulSoup
import redis
import time

from cc.serializers import ProtocolModelSerializer
from cc.models import ProtocolModel


class GetProtocolIO(APIView):
    #authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        """Get all unique tissues from TurnoverData Tissue field"""
        protocol = ProtocolModel.create_protocol_from_url(request.data['url'])
        data = ProtocolModelSerializer(protocol, many=False).data
        return Response(data, status=status.HTTP_200_OK)


class DataChunkedUploadView(ChunkedUploadView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser,)

    def _put_chunk(self, request, pk=None, whole=False, *args, **kwargs):
        try:
            chunk = request.data[self.field_name]
        except KeyError:
            raise ChunkedUploadError(status=status.HTTP_400_BAD_REQUEST,
                                     detail='No chunk file was submitted')

        if whole:
            start = 0
            total = chunk.size
            end = total - 1
        else:
            content_range = request.META.get('HTTP_CONTENT_RANGE', '')
            match = self.content_range_pattern.match(content_range)
            if not match:
                raise ChunkedUploadError(status=status.HTTP_400_BAD_REQUEST,
                                         detail='Error in request headers')

            start = int(match.group('start'))
            end = int(match.group('end'))
            total = int(match.group('total'))

        chunk_size = end - start + 1
        max_bytes = self.get_max_bytes(request)

        if end > total:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST,
                detail='End of chunk exceeds reported total (%s bytes)' % total
            )

        if max_bytes is not None and total > max_bytes:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST,
                detail='Size of file exceeds the limit (%s bytes)' % max_bytes
            )

        if chunk.size != chunk_size:
            raise ChunkedUploadError(
                status=status.HTTP_400_BAD_REQUEST,
                detail="File size doesn't match headers: file size is {} but {} reported".format(
                    chunk.size,
                    chunk_size,
                ),
            )

        if pk:
            upload_id = pk
            chunked_upload = get_object_or_404(self.get_queryset(),
                                               pk=upload_id)
            self.is_valid_chunked_upload(chunked_upload)
            if chunked_upload.offset != start:
                raise ChunkedUploadError(
                    status=status.HTTP_400_BAD_REQUEST,
                    detail='Offsets do not match',
                    expected_offset=chunked_upload.offset,
                    provided_offset=start,
                )

            chunked_upload.append_chunk(chunk, chunk_size=chunk_size)
        else:
            kwargs = {'offset': chunk.size}
            if hasattr(self.model, self.user_field_name):
                if hasattr(request, 'user') and request.user.is_authenticated:
                    kwargs[self.user_field_name] = request.user
                elif self.model._meta.get_field(self.user_field_name).null:
                    kwargs[self.user_field_name] = None
                else:
                    raise ChunkedUploadError(
                        status=status.HTTP_400_BAD_REQUEST,
                        detail="Upload requires user authentication but user cannot be determined",
                    )
            print(request.data)
            chunked_upload = self.serializer_class(data=request.data)
            if not chunked_upload.is_valid():
                raise ChunkedUploadError(status=status.HTTP_400_BAD_REQUEST,
                                         detail=chunked_upload.errors)

            # chunked_upload is currently a serializer;
            # save returns model instance
            chunked_upload = chunked_upload.save(**kwargs)

        return chunked_upload

    def on_completion(self, chunked_upload, request):
        return super().on_completion(chunked_upload, request)


@ensure_csrf_cookie
def set_csrf(request):
    return JsonResponse(data={"data": "CSRF cookie set"}, status=status.HTTP_200_OK)


def health_check(request):
    """
    Basic health check endpoint
    Returns system status and basic connectivity information
    """
    start_time = time.time()
    
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": getattr(settings, 'VERSION', '1.0.0'),
        "environment": getattr(settings, 'ENVIRONMENT', 'development'),
        "checks": {}
    }
    
    # Database connectivity check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        health_status["checks"]["database"] = {"status": "healthy", "message": "Database connection successful"}
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = {"status": "unhealthy", "message": str(e)}
    
    # Redis connectivity check (if configured)
    try:
        redis_host = getattr(settings, 'REDIS_HOST', 'localhost')
        redis_port = getattr(settings, 'REDIS_PORT', 6379)
        redis_password = getattr(settings, 'REDIS_PASSWORD', None)
        
        r = redis.Redis(host=redis_host, port=redis_port, password=redis_password, socket_timeout=2)
        r.ping()
        health_status["checks"]["redis"] = {"status": "healthy", "message": "Redis connection successful"}
    except Exception as e:
        # Redis failure is not critical for basic health
        health_status["checks"]["redis"] = {"status": "warning", "message": f"Redis unavailable: {str(e)}"}
    
    # Response time
    response_time = (time.time() - start_time) * 1000
    health_status["response_time_ms"] = round(response_time, 2)
    
    # Set HTTP status code based on health
    status_code = 200 if health_status["status"] == "healthy" else 503
    
    return JsonResponse(health_status, status=status_code)


def ready_check(request):
    """
    Readiness check endpoint
    More comprehensive check for container orchestration
    """
    ready_status = {
        "ready": True,
        "timestamp": time.time(),
        "checks": {}
    }
    
    # Database readiness
    try:
        with connection.cursor() as cursor:
            # Check if we can perform basic operations
            cursor.execute("SELECT COUNT(*) FROM django_migrations")
            migration_count = cursor.fetchone()[0]
        
        ready_status["checks"]["database"] = {
            "ready": True, 
            "migrations": migration_count,
            "message": "Database ready with migrations applied"
        }
    except Exception as e:
        ready_status["ready"] = False
        ready_status["checks"]["database"] = {"ready": False, "message": str(e)}
    
    # Check if critical tables exist
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM auth_user")
        ready_status["checks"]["auth"] = {"ready": True, "message": "Authentication system ready"}
    except Exception as e:
        ready_status["ready"] = False
        ready_status["checks"]["auth"] = {"ready": False, "message": str(e)}
    
    status_code = 200 if ready_status["ready"] else 503
    return JsonResponse(ready_status, status=status_code)


def liveness_check(request):
    """
    Liveness check endpoint
    Simple check to verify the application is running
    """
    return JsonResponse({
        "alive": True,
        "timestamp": time.time(),
        "message": "CUPCAKE LIMS is running"
    })