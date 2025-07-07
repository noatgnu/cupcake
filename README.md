# CUPCAKE - Collaborative Laboratory Protocol Management System

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![Django](https://img.shields.io/badge/django-5.x-green.svg)](https://djangoproject.com)

CUPCAKE is a comprehensive web-based Laboratory Information Management System (LIMS) designed for collaborative protocol development, execution tracking, and data management in proteomics and other scientific laboratories.

## Key Features

### Real-time Collaboration
- Synchronous editing and viewing of protocols
- WebRTC-based audio/video conferencing
- Live chat and file sharing
- Multi-user session management

### Protocol Management
- Create, import, organize and share laboratory protocols
- Integration with protocols.io
- Version control and history tracking
- Step-by-step execution guidance

### Session Tracking
- Record and monitor protocol execution
- Timestamped annotations and media uploads
- Real-time progress tracking
- Comprehensive audit trails

### Instrument Integration
- Schedule and track laboratory instruments
- Maintenance scheduling and notifications
- Usage monitoring and reporting
- Permission-based access control

### Data Management
- Import/export with rollback capabilities
- SDRF file format support for proteomics
- SQLite archive format for data portability
- Advanced search and filtering

### AI Features (Optional)
- **Whisper Integration**: Audio transcription to text
- **OCR Support**: Text recognition from images
- **LLM Integration**: Protocol summarization and insights

## Technology Stack

### Backend
- **Django 5.x** with Django REST Framework
- **Django Channels** for WebSocket support
- **PostgreSQL** database with audit trails
- **Redis** for caching and message brokering
- **django-rq** for background task processing

### Frontend & Communication
- **Angular** single-page application
- **NGINX** reverse proxy and static file serving
- **WebRTC** for peer-to-peer connections
- **WebSockets** for real-time collaboration

### Infrastructure
- **Docker & Docker Compose** for containerization
- **Microservice architecture** with specialized workers
- **Background workers** for CPU-intensive tasks

### Optional AI Services
- **Whisper** for audio transcription
- **Tesseract OCR** for text recognition
- **LLaMA** for protocol summarization

## Prerequisites

- **Docker** and **Docker Compose** (latest versions recommended)
- **Linux/AMD64** hardware (for full AI functionality)
- **Internet connection** for optional external services
- **4GB+ RAM** for optimal performance

## Quick Start

### 1. Clone and Configure

```bash
# Clone the repository
git clone <repository-url>
cd cupcake

# Create environment configuration
cp .env.example .env  # Create from template or manually create
```

### 2. Environment Configuration

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

#### Important Configuration Notes:
- **Security**: Change `SECRET_KEY` to a random string for production
- **Domains**: Update `CORS_ORIGIN_WHITELIST`, `CSRF_TRUSTED_ORIGINS`, and `ALLOWED_HOSTS` for your domain
- **AI Features**: Enable optional services by setting `USE_*` flags to `True`
- **Instruments**: Set `ALLOW_OVERLAP_BOOKINGS` based on your laboratory policies

### 3. Deploy and Initialize

```bash
# Start all services
docker-compose up -d

# Initialize the database
docker-compose exec cc python manage.py migrate

# Create an admin user
docker-compose exec -it cc python manage.py createsuperuser

# (Optional) Load sample data
docker-compose exec cc python manage.py loaddata initial_data
```

### 4. Access the Application

- **Frontend**: http://localhost:4200
- **API**: http://localhost:8001/api/
- **Admin Interface**: http://localhost:8001/admin/
- **API Documentation**: http://localhost:8001/api/ (browsable API)

## Service Architecture

CUPCAKE uses a microservice architecture with specialized containers:

### Core Services
- **cc**: Main Django application server
- **ccnginx**: NGINX reverse proxy and static file server
- **ccdb**: PostgreSQL database with persistent storage
- **ccredis**: Redis cache and message broker

### Worker Services
- **ccdocx**: Document export worker (Word, PDF generation)
- **ccimport**: Data import/export worker with rollback support
- **ccbackup**: Automated backup service (weekly database and media backups)

### Optional AI Services
- **ccworker**: Audio transcription worker (Whisper)
- **ccocr**: OCR text recognition worker (Tesseract)
- **ccllama**: LLM worker for protocol summarization

### Additional Services
- **ssl**: SSL certificate management (for local testing)
- **ccfrontend**: Angular frontend build service

## 🧪 Development & Testing

### Running Tests
Use the comprehensive test runner:

```bash
# Run all tests
python tests/run_tests.py --test-type all

# Run specific test types  
python tests/run_tests.py --test-type unit
python tests/run_tests.py --test-type integration
python tests/run_tests.py --test-type performance --performance-users 20
```

### Development Commands
```bash
# Django management commands
docker-compose exec cc python manage.py <command>

# Database operations
docker-compose exec cc python manage.py makemigrations
docker-compose exec cc python manage.py migrate

# Background worker status
docker-compose exec cc python manage.py rqworker

# Django shell
docker-compose exec -it cc python manage.py shell
```

## API Features

### Historical Records
Access comprehensive audit trails for all models:
```
GET /api/history/?model=instrument&history_type=~
GET /api/history/summary/?model=annotation  
GET /api/history/timeline/?model=storedreagent&days=7
```

### Real-time Collaboration
- WebSocket endpoints for live protocol sessions
- WebRTC signaling for peer-to-peer connections
- Background task monitoring via RQ dashboard

## Production Deployment

### Security Checklist
- Generate a strong `SECRET_KEY`
- Configure appropriate domain names in `ALLOWED_HOSTS` and CORS settings
- Set up proper SSL certificates
- Use environment-specific database credentials
- Enable backup services and monitoring

### Performance Optimization
- Use production-grade WSGI server (Gunicorn included)
- Configure Redis for session storage and caching
- Set up CDN for static files
- Monitor background worker queues

## Documentation

- **API Documentation**: Available at `/api/` (Django REST Framework browsable API)
- **Admin Interface**: Full Django admin at `/admin/`
- **CLAUDE.md**: Development guidance for AI assistants

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run the test suite
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Links

- **Frontend Repository**: [Angular frontend](https://github.com/noatgnu/cupcake-ng)
- **Android Client Repository**: [Android Client](https://github.com/noatgnu/cupcakeAndroid)
