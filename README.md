# CUPCAKE

This project uses Docker Compose to set up a multi-container environment for a web application. The services include a frontend, backend, database, and various workers for a proteomics laboratory information management system (LIMS). The project is designed to be run locally or in a cloud environment, with optional features for transcription, OCR, and LLM integration.

## Prerequisites
- Docker
- Docker Compose
- Linux/AMD64 Hardware

## Environment Variables
Create a `.env` file with the following environment variables:
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

## Services

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

## Initial Setup

After deployment of the docker compose for the first time, you need to run the following commands to create the database and superuser:
```bash
docker-compose exec cc python manage.py migrate
docker-compose exec -it cc python manage.py createsuperuser
```

## Maintenance

Everyweek, the `ccbackup` service will perform a backup of the database and media files. The backup will be stored in the `backups` directory. You can also manually run the backup command by running:
```bash
docker-compose exec ccbackup python manage.py dbbackup
docker-compose exec ccbackup python manage.py mediabackup
```

Each backup will be stored with the current date and time in the `backups` directory. `*.tar` files are media backups while `*.psql.bin` files are database backups.