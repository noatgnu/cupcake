# CUPCAKE Raspberry Pi Docker Image Builder

This directory contains scripts to build custom Raspberry Pi OS images with CUPCAKE pre-installed using Docker for better isolation and consistency.

## 🐳 Docker-Based Build

The Docker-based build provides:
- **Consistent environment** across different host systems
- **Isolated build process** that doesn't affect your host system
- **Pre-installed dependencies** in the Docker image
- **Easy cleanup** when build is complete

### Quick Start

```bash
# Build Pi 5 image with defaults
./build-pi-image-docker.sh

# Build Pi 4 image
./build-pi-image-docker.sh pi4

# Build with specific version
./build-pi-image-docker.sh pi5 v1.0.0

# Build with SSH disabled
./build-pi-image-docker.sh pi4 v1.0.0 0
```

### Usage

```bash
./build-pi-image-docker.sh [pi_model] [version] [enable_ssh]
```

**Arguments:**
- `pi_model` - Raspberry Pi model: `pi4` or `pi5` (default: `pi5`)
- `version` - Image version tag (default: current date)
- `enable_ssh` - Enable SSH: `1` or `0` (default: `1`)

## 📋 Prerequisites

### System Requirements
- **Docker** installed and running
- **10GB+ free disk space** for build process
- **Privileged Docker access** (required for pi-gen chroot operations)
- **Internet connection** for downloading packages and frontend source

### Minimum Hardware
- **4GB RAM** (8GB+ recommended)
- **4 CPU cores** (for reasonable build times)
- **x86_64 or ARM64** host system

## 🔧 Build Process

The Docker build process:

1. **Builds Docker image** with all pi-gen dependencies (first run only)
2. **Creates build container** with privileged access
3. **Mounts CUPCAKE source** from host into container
4. **Runs pi-gen** with custom CUPCAKE stage
5. **Builds Angular frontend** during image creation
6. **Compresses final image** with xz compression
7. **Generates checksums** for verification

### Build Stages

The custom CUPCAKE stage includes:

- **System packages**: PostgreSQL, Redis, Nginx, Python 3, Node.js
- **Frontend build**: Angular application from cupcake-ng repository
- **User setup**: Creates `cupcake` user with sudo access
- **Service configuration**: Enables all required services
- **Pi optimizations**: Hardware-specific boot configurations

## 📁 Output Files

After successful build, you'll find:

```
raspberry-pi/output/
├── cupcake-pi5-2024-01-15.img.xz          # Compressed Pi image
└── cupcake-pi5-2024-01-15.img.xz.sha256   # Checksum file
```

## 🚀 Flashing and Deployment

### 1. Flash Image to SD Card

**Using Raspberry Pi Imager (Recommended):**
```bash
# Install Raspberry Pi Imager if needed
# Then select "Use custom image" and choose the .img.xz file
```

**Using dd (Linux/macOS):**
```bash
# Extract first (optional, imager can handle .xz)
xz -d cupcake-pi5-2024-01-15.img.xz

# Flash to SD card
sudo dd if=cupcake-pi5-2024-01-15.img of=/dev/sdX bs=4M status=progress
```

### 2. Initial Boot and Access

1. **Insert SD card** into Raspberry Pi
2. **Connect ethernet** cable (recommended for first boot)
3. **Power on** the Pi
4. **Wait 5-10 minutes** for initial setup to complete

### 3. SSH Access

```bash
# Default credentials
ssh cupcake@cupcake-pi5.local
# Password: cupcake123 (change immediately!)
```

### 4. Web Interface

Once booted and configured:
- **Frontend**: http://cupcake-pi5.local
- **Admin**: http://cupcake-pi5.local/admin

## 🐛 Troubleshooting

### Docker Issues

**Docker not running:**
```bash
sudo systemctl start docker
sudo systemctl enable docker
```

**Permission denied:**
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

**Insufficient disk space:**
```bash
# Check available space
df -h

# Clean Docker images/containers
docker system prune -a
```

### Build Issues

**Build fails with chroot errors:**
- Ensure Docker has privileged access
- Try building on a Linux host system
- Check available RAM (need 4GB+)

**Frontend build fails:**
- Check internet connection
- Verify GitHub access to cupcake-ng repository

**Pi-gen stage errors:**
```bash
# Check container logs
docker logs cupcake-pi-build-XXXXXX

# Build with more verbose output
docker run -it --privileged cupcake-pi-builder:latest /bin/bash
```

### Runtime Issues

**Can't connect to Pi:**
- Check network connectivity
- Try IP address instead of hostname
- Verify Pi has booted completely (LED activity stopped)

**Services not starting:**
```bash
# SSH into Pi and check services
sudo systemctl status postgresql redis-server nginx
sudo journalctl -u cupcake-setup.service
```

## 🔄 Comparison with Native Build

| Feature | Docker Build | Native Build |
|---------|-------------|--------------|
| **Host Impact** | Isolated | Installs packages on host |
| **Consistency** | Same environment every time | Varies by host system |
| **Setup Time** | ~15 min first run | ~5 min |
| **Build Time** | 1-3 hours | 1-3 hours |
| **Disk Usage** | ~8GB (container + image) | ~6GB (image only) |
| **Cleanup** | Automatic | Manual |
| **Prerequisites** | Docker only | Many packages |

## 🧹 Cleanup

The Docker build automatically cleans up temporary files, but you can also:

```bash
# Remove build Docker image (saves ~2GB)
docker rmi cupcake-pi-builder:latest

# Clean all Docker build cache
docker system prune -a

# Remove output files
rm -rf raspberry-pi/output/
```

## 🔧 Advanced Usage

### Custom Docker Image

To modify the build environment:

```bash
# Edit Dockerfile.pi-builder
vim Dockerfile.pi-builder

# Rebuild Docker image
docker build -f Dockerfile.pi-builder -t cupcake-pi-builder:latest .
```

### Build with Custom Source

```bash
# Mount different CUPCAKE source
docker run --privileged \
  -v /path/to/custom/cupcake:/build/cupcake-src:ro \
  -v ./output:/build/output:rw \
  cupcake-pi-builder:latest \
  /build/container-build.sh pi5 custom-v1.0.0 1
```

### Debugging Build Process

```bash
# Run interactive container
docker run -it --privileged \
  -v $(pwd)/..:/build/cupcake-src:ro \
  cupcake-pi-builder:latest /bin/bash

# Then inside container:
cd /build/pi-gen
# Run build steps manually
```

## 📚 Additional Resources

- [Pi-gen Documentation](https://github.com/RPi-Distro/pi-gen)
- [Docker Documentation](https://docs.docker.com/)
- [Raspberry Pi OS Documentation](https://www.raspberrypi.org/documentation/)
- [CUPCAKE Documentation](https://github.com/noatgnu/cupcake)