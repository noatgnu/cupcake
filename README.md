# CUPCAKE - Collaborative Laboratory Protocol Management System

CUPCAKE is a comprehensive web-based Laboratory Information Management System (LIMS) designed for collaborative protocol development, execution tracking, and data management in proteomics and other scientific laboratories.

## Key Features

- Real-time Collaboration: Synchronous editing and viewing of protocols with WebRTC-based audio/video conferencing
- Protocol Management: Create, import, organize and share laboratory protocols
- Session Tracking: Record and monitor protocol execution with timestamped annotations
- Instrument Integration: Schedule, track, and manage laboratory instruments
- Data Processing: Import, process, and analyze scientific data
- Media Support: Support for annotations, images, and files
- AI Features (optional):
  - Transcription of audio to text (Whisper)
  - OCR for text recognition in images
  - Protocol summarization with LLM

## Technology Stack
- Backend: Django, Django REST Framework, Django Channels
- Frontend: Angular (served via NGINX)
- WebSockets: For real-time communication and collaboration
- WebRTC: For peer-to-peer audio/video/text/file transfer connections
- Database: PostgreSQL
- Cache/Message Broker: Redis
- Containerization: Docker & Docker Compose
- Optional AI Services:
  - Whisper for transcription
  - OCR for text recognition
  - LLaMA for text summarization

## Prerequisites
- Docker and Docker Compose
- Linux/AMD64 Hardware (for full functionality)
- Internet connection for optional external services

## Setup Instructions
1. Environment Configuration

Create a `.env` file with the following variables:
```shell
POSTGRES_NAME=postgres
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=ccdb
POSTGRES_PORT=5432
REDIS_HOST=ccredis
REDIS_PORT=6379
SECRET_KEY='testth!_q_0)r9_8n0gkey62u!(xwr-u0ys2z*hntinsecure'
CORS_ORIGIN_WHITELIST='http://localhost,http://localhost:4200'
CSRF_TRUSTED_ORIGINS='http://localhost,http://localhost:4200'
PROTOCOLS_IO_ACCESS_TOKEN=
ALLOWED_HOSTS='localhost,localhost:4200,localhost:8001'
DEBUG=False
USE_COTURN=False
USE_LLM=False
USE_WHISPER=False
USE_OCR=False
ALLOW_OVERLAP_BOOKINGS=True
FRONTEND_URL='http://localhost:4200'
BACKUP_DIR='/app/backup'
```
The above variables are the default values, please change them according to your needs.
- Replace the `CORS_ORIGIN_WHITELIST` and `CSRF_TRUSTED_ORIGINS` with the hostname and homepage urls of your tunnel.
- Replace the `ALLOWED_HOSTS` with the hostnames of your tunnel.
- Replace the `FRONTEND_URL` with the homepage url of your tunnel.
- Replace the `USE_COTURN` (webRTC experimental), `USE_LLM` (protocol summary), `USE_WHISPER` (transcription), and `USE_OCR` (text recognition) with `True` or `False` depending on your needs.
- Replace the `ALLOW_OVERLAP_BOOKINGS` with `True` or `False` if you would like to allow overlapping booking of instrument.
- Replace the `SECRET_KEY` with a random string for security purposes.

2. Deployment

```shell
# Clone the repository
git clone <repository-url>
cd cupcake

# Start the services
docker-compose up -d

# Initialize the database
docker-compose exec cc python manage.py migrate

# Create an admin user
docker-compose exec -it cc python manage.py createsuperuser
```

3. Access the Application

- Frontend: http://localhost:4200
- Admin interface: http://localhost:8000/admin/

## Service Architecture

- **ccfrontend**: The frontend service built from `Dockerfile-frontend`.
- **ccnginx**: The Nginx service built from `Dockerfile-nginx-demo` which use the nginx config file `nginx-cupcake-demo.conf`.
  - The `nginx-cupcake-demo.conf` is found in the `nginx-conf` directory, please change the hostname `cupcake.proteo.info` to the hostname of your tunnel.
- **ssl**: The SSL service built from `Dockerfile-ssl`. This is mostly for local testing since the ssl will mostly be from cloudflare.
- **cc**: The main backend service built from `Dockerfile`.
- **ccdocx**: The document export worker service built from `Dockerfile-export-worker`.
- **ccimport**: The data import worker service built from `Dockerfile-import-data-worker`.
- **ccworker**: The transcription worker service built from `Dockerfile-transcribe-worker`. Optional service if you are not using transcription.
- **ccocr**: The OCR worker service built from `Dockerfile-ocr`. Optional service if you are not using OCR.
- **ccdb**: The PostgreSQL database service. 
- **ccredis**: The Redis service built from `Dockerfile-redis`.
- **ccllama**: The Llama worker service built from `Dockerfile-llama-worker`. Optional service if you are not using Llama.
- **ccbackup**: A service using cron to perform weekly backup of the database and media files. The backup will be stored in the `backups` directory.

## Production Deployment
For production deployment:

- Update the .env file with appropriate values for your environment
- Generate a strong SECRET_KEY
- Configure appropriate domain names in ALLOWED_HOSTS and CORS settings
- Set up proper SSL certificates for secure communication

