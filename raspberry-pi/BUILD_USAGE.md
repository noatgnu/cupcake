# CUPCAKE Raspberry Pi Image Builder Usage

## Overview

The CUPCAKE Raspberry Pi image builder supports two build methods:

1. **Native Build** (`build-pi-image.sh`) - Direct build on host system
2. **Docker Build** (`build-pi-image-docker.sh`) - Containerized build for better isolation

Both scripts build images for Raspberry Pi 4 and Pi 5 with full frontend support and work locally or via GitHub Actions.

## 🐳 Docker Build (Recommended)

For most users, the Docker build provides better consistency and isolation:

```bash
# Quick start - build Pi 5 image
./build-pi-image-docker.sh

# Build Pi 4 image with version
./build-pi-image-docker.sh pi4 v1.0.0
```

**Benefits:**
- ✅ Consistent build environment
- ✅ No host system changes
- ✅ Automatic cleanup
- ✅ Works on any Docker-capable system

**Requirements:**
- Docker installed and running
- 10GB+ free disk space
- Privileged Docker access

📖 **See [DOCKER_BUILD_USAGE.md](./DOCKER_BUILD_USAGE.md) for complete Docker build documentation.**

## 🔧 Native Build

The native build installs dependencies directly on your system:

### Basic Usage

```bash
./build-pi-image.sh [pi_model] [version] [enable_ssh]
```

### Parameters

- **pi_model** (optional): `pi4` or `pi5` (default: `pi5`)
- **version** (optional): Version string for the image (default: current date)
- **enable_ssh** (optional): `1` to enable SSH, `0` to disable (default: `1`)

### Examples

```bash
# Build Pi 5 image with default settings
./build-pi-image.sh

# Build Pi 4 image with custom version
./build-pi-image.sh pi4 v1.2.0

# Build Pi 5 image with SSH disabled
./build-pi-image.sh pi5 production 0

# Build Pi 4 image with all custom settings
./build-pi-image.sh pi4 lab-deployment-v2.1 1
```

## What's Included

### Frontend Build Process ✨

The script now automatically:

1. **Installs Node.js 20** during image build
2. **Clones cupcake-ng** repository (Angular frontend)
3. **Configures environment** for Pi deployment using `.local` hostnames
4. **Builds the complete frontend** with `npm install && npm run build`
5. **Deploys to `/opt/cupcake/frontend/`** ready for nginx serving
6. **Cleans up** build artifacts to save space

### Pi Model Specific Features

#### Pi 4 Configuration
- 2.0GHz ARM frequency
- 64MB GPU memory
- NVMe PCIe support
- Hostname: `cupcake-pi4.local`

#### Pi 5 Configuration  
- 2.4GHz ARM frequency
- 128MB GPU memory
- PCIe Gen 3 NVMe support
- Advanced Pi 5 optimizations
- Hostname: `cupcake-pi5.local`

## Output Files

After successful build:

```
./build/
├── cupcake-{model}-{version}.img.xz     # Compressed Pi image
├── cupcake-{model}-{version}.img.xz.sha256  # Checksum
└── cupcake-{model}-deployment-{version}.tar.gz  # Deployment package
```

## Prerequisites

The script will automatically install missing packages:
- `git`
- `qemu-user-static` 
- `binfmt-support`
- `rsync`
- Standard pi-gen dependencies

## GitHub Actions Integration

This same script is used by GitHub Actions workflow:

```yaml
# Builds both Pi 4 and Pi 5 images
# Uses exact same frontend build process
# Outputs compressed images and releases
```

## Frontend Configuration

The built frontend is automatically configured for Pi deployment:

- **Production URL**: `https://cupcake.proteo.info` → `http://cupcake-pi.local`
- **Development URL**: `http://localhost` → `http://cupcake-pi.local`
- **mDNS Support**: Uses `.local` hostnames for easy Pi discovery
- **No External Dependencies**: Complete self-contained deployment

## Deployment

1. **Flash the image**: Use Raspberry Pi Imager or `dd`
2. **Boot the Pi**: First boot takes 5-10 minutes for setup
3. **Access CUPCAKE**: Navigate to `http://cupcake-pi.local`
4. **Complete setup**: SSH in and run setup scripts if needed

## Troubleshooting

### Build Issues
- Ensure at least 8GB free disk space
- Run with `sudo` permissions for pi-gen
- Check internet connectivity for frontend build

### Frontend Issues
- Frontend build happens during chroot, check build logs
- Uses Node.js 20 for latest Angular compatibility
- Cleans up `node_modules` to save image space

### Pi Model Detection
- Script automatically configures hardware-specific optimizations
- Both models use same base image with model-specific tweaks
- Hostnames are model-specific but frontend uses generic `.local`

## Development

To modify the frontend build process, edit the chroot section in `create_custom_stage()` function around line 246.

To add new Pi models, extend the configuration logic in `configure_pi_gen()` function.