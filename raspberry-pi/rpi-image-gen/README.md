# CUPCAKE Raspberry Pi 5 Custom Image Generation

This directory contains configuration for building custom Raspberry Pi OS images using the official `rpi-image-gen` tool from the Raspberry Pi Foundation.

## Overview

The `rpi-image-gen` tool provides a modern, officially supported approach to creating customized Raspberry Pi OS images with pre-configured applications and settings.

## Prerequisites

- 64-bit Raspberry Pi OS (recommended) or Debian-based Linux system
- Git
- sudo access

## Quick Start

1. Clone the rpi-image-gen tool:
```bash
git clone https://github.com/raspberrypi/rpi-image-gen.git
cd rpi-image-gen
```

2. Install dependencies:
```bash
sudo ./install_deps.sh
```

3. Copy CUPCAKE configuration:
```bash
cp -r /path/to/cupcake/raspberry-pi/rpi-image-gen/* ./
```

4. Build the image:
```bash
./build.sh -c cupcake-pi5-config.ini
```

## Configuration Files

- `cupcake-pi5-config.ini` - Main configuration for Pi 5 deployment
- `collections/cupcake-packages.yaml` - Package definitions
- `overlays/cupcake/` - File system overlays
- `hooks/` - Custom installation scripts

## Output

Built images will be available in:
`work/cupcake-pi5/artefacts/cupcake-pi5.img`

## Hardware Requirements

- Raspberry Pi 5 (8GB recommended)
- NVMe SSD via M.2 HAT (for production)
- MicroSD card (64GB+ for testing)
- Ethernet connection

## Next Steps

After building the image:
1. Flash to storage device using Raspberry Pi Imager
2. Boot Pi 5 with the image
3. Complete initial setup via web interface at http://pi-ip-address
4. Configure SSL certificates for production use

## Support

For issues with image generation, consult:
- [rpi-image-gen documentation](https://github.com/raspberrypi/rpi-image-gen)
- CUPCAKE hardware guide in `../HARDWARE_GUIDE.md`