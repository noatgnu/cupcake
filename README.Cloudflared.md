# Project Name

This project uses Docker Compose to set up a multi-container environment for a web application. The services include a frontend, backend, database, and various workers.

## Prerequisites

- Docker
- Docker Compose
- Cloudflare account

## Environment Variables
Create a `.env.cloudflared` file with the following environment variables:
```shell
POSTGRES_NAME=postgres
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=ccdb
POSTGRES_PORT=5432
REDIS_HOST=ccredis
REDIS_PORT=6379
SECRET_KEY=testth!_q_0)r9_8n0gkey62u!(xwr-u0ys2z*hntinsecure
CORS_ORIGIN_WHITELIST=http://localhost,http://localhost:4200
CSRF_TRUSTED_ORIGINS=http://localhost,http://localhost:4200
PROTOCOLS_IO_ACCESS_TOKEN=
ALLOWED_HOSTS=localhost,localhost:4200,localhost:8001
DEBUG=False
USE_COTURN=False
USE_LLM=False
USE_WHISPER=False
USE_OCR=False
ALLOW_OVERLAP_BOOKINGS=True
FRONTEND_URL=http://localhost:4200
```
The above variables are the default values, please change them according to your needs.
- Add the `TUNNEL_TOKEN` for the supposed cloudflare tunnel in the `.env.cloudflared` file.
- Replace the `CORS_ORIGIN_WHITELIST` and `CSRF_TRUSTED_ORIGINS` with the hostname and homepage urls of your tunnel.
- Replace the `ALLOWED_HOSTS` with the hostnames of your tunnel.
- Replace the `FRONTEND_URL` with the homepage url of your tunnel.
- Replace the `USE_COTURN` (webRTC experimental), `USE_LLM` (protocol summary), `USE_WHISPER` (transcription), and `USE_OCR` (text recognition) with `True` or `False` depending on your needs.
- Replace the `ALLOW_OVERLAP_BOOKINGS` with `True` or `False` if you would like to allow overlapping booking of instrument.

## Services

- **ccfrontend**: The frontend service built from `Dockerfile-frontend`.
- **cccloudflared**: The Cloudflare tunnel service.
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

## Volumes

- **ssl**: Stores SSL certificates.
- **./media**: Mounted to `/app/media/` in various services.
- **./staticfiles**: Mounted to `/static/` in the `ccnginx` service.
- **./data2**: Mounted to `/var/lib/postgresql/data` in the `ccdb` service.

## Networks

- **cc-net**: The custom network for all services.

## Usage

1. Clone the repository.
2. Ensure you have Docker and Docker Compose installed.
3. Create a `.env.cloudflared` file with the necessary environment variables (refer to `.env` file and please add `TUNNEL_TOKEN` for the supposed cloudflare tunnel).
4. Build and start the services:

    ```sh
    docker-compose -f docker-compose.cloudflared.demo.yml up --build
    ```

5. Access the application via cloudflare tunnel.

## Configuration

### Environment Variables

- **.env.cloudflared**: Contains environment variables for the Cloudflare tunnel and other services.

### Ports

- **ccnginx**: Exposes ports `80` and `443`.
- **cc**: Exposes port `8001`.
- **ccdb**: Exposes port `5433`.
- **ccredis**: Exposes port `6380`.

## Notes

- Ensure that the paths in the `volumes` section of the `docker-compose.cloudflared.demo.yml` file are correct and accessible.
- The `ccnginx` service uses SSL certificates stored in the `ssl` volume.

## License

This project is licensed under the MIT License.