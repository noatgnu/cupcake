# CUPCAKE on Raspberry Pi 5 - Low Power Deployment

This directory contains configuration files and scripts to create a custom Raspberry Pi 5 image optimized for running the CUPCAKE stack in low-power scenarios.

## Overview

The custom image includes:
- **Optimized OS**: Minimal Raspberry Pi OS Lite with only essential services
- **Native Python**: Direct Python deployment without Docker for reduced resource usage
- **PostgreSQL**: Lightweight database configuration
- **Redis**: Memory-optimized caching
- **Nginx**: Efficient web server with static file serving
- **Auto-deployment**: Scripts for automated CUPCAKE setup

## Hardware Requirements

### Minimum Requirements
- Raspberry Pi 5 (4GB RAM minimum, 8GB recommended)
- 64GB+ microSD card (Class 10 or better) - for initial setup only
- M.2 NVMe SSD (128GB+ recommended for production)
- Ethernet connection (WiFi optional)
- 5V 5A USB-C power supply

### Recommended Production Setup
- Raspberry Pi 5 with 8GB RAM
- **NVMe SSD 256GB+ (Samsung 980, WD SN570, or similar)**
- M.2 HAT or NVMe Base for Pi 5
- Active cooling (heatsink + fan)
- Ethernet connection for stability
- UPS/battery backup for power reliability

### Storage Options (in order of preference)

1. **NVMe SSD (RECOMMENDED)**: 
   - 10-20x faster than SD cards
   - Better reliability for database operations
   - Suitable for production laboratory use
   - Examples: Samsung 980, WD SN570, Crucial P3

2. **High-Speed SD Card**: 
   - Minimum for testing/development only
   - Not recommended for production use
   - Use only Samsung EVO Select or SanDisk Extreme Pro

3. **USB 3.0 SSD**: 
   - Alternative if NVMe not available
   - Better than SD cards but not as fast as NVMe

## Quick Start

### Option 1: NVMe SSD Boot (Recommended for Production)

1. **Build the custom image**:
   ```bash
   ./build-pi-image.sh
   ```

2. **Flash to SD card (temporary)**:
   ```bash
   sudo dd if=cupcake-pi5.img of=/dev/sdX bs=4M status=progress
   ```

3. **Setup NVMe boot**:
   - Insert SD card and boot Pi 5
   - Connect NVMe SSD via M.2 HAT
   - SSH to cupcake@cupcake-pi.local
   - Run: `sudo /opt/cupcake/scripts/setup-nvme.sh`
   - System will clone to NVMe and configure boot

4. **Production deployment**:
   - Remove SD card after NVMe setup
   - Pi will boot from NVMe SSD
   - Run: `sudo /opt/cupcake/setup.sh`

### Option 2: SD Card Boot (Development Only)

1. **Build and flash**:
   ```bash
   ./build-pi-image.sh
   sudo dd if=cupcake-pi5.img of=/dev/sdX bs=4M status=progress
   ```

2. **Boot and configure**:
   - Insert SD card into Pi 5
   - Connect ethernet and power
   - SSH to cupcake@cupcake-pi.local
   - Run: `sudo /opt/cupcake/setup.sh`

## Files Structure

```
raspberry-pi/
├── README.md                 # This file
├── build-pi-image.sh        # Main image builder script
├── config/
│   ├── pi-gen-config/       # Custom pi-gen configuration
│   ├── system/              # System configuration files
│   ├── nginx/               # Nginx configuration
│   ├── postgresql/          # Database configuration
│   └── systemd/             # Service definitions
├── scripts/
│   ├── setup.sh            # Initial system setup
│   ├── deploy-cupcake.sh   # CUPCAKE deployment
│   ├── optimize-pi.sh      # Performance optimizations
│   └── monitoring.sh       # System monitoring
└── assets/
    ├── cupcake-logo.png    # Boot splash
    └── motd.txt            # Login message
```

## Performance Optimizations

### Memory Management
- Reduced GPU memory split (16MB)
- Optimized swap configuration
- Memory-mapped database settings
- Efficient caching strategies

### CPU Optimization
- CPU governor set to ondemand
- Process priorities optimized
- Background service limitations
- Thermal throttling prevention

### Storage Optimization
- Log rotation configured
- Temporary file cleanup
- Database vacuum scheduling
- Efficient backup strategies

## Network Configuration

### Default Settings
- Static IP: 192.168.1.100 (configurable)
- Hostname: cupcake-pi
- SSH enabled with key authentication
- Firewall configured for CUPCAKE ports

### Access Points
- Web Interface: http://cupcake-pi.local
- SSH Access: ssh cupcake@cupcake-pi.local
- Database: localhost:5432 (internal only)
- Redis: localhost:6379 (internal only)

## Monitoring and Maintenance

### Built-in Monitoring
- System resource monitoring
- Service health checks
- Log aggregation
- Automated alerts

### Maintenance Scripts
- Automatic updates (security only)
- Database maintenance
- Log cleanup
- Backup procedures

## Troubleshooting

### Common Issues
1. **Low memory**: Reduce worker processes in config
2. **Storage full**: Run cleanup script
3. **Network issues**: Check static IP configuration
4. **Service failures**: Check systemd logs

### Performance Tuning
- Adjust worker processes based on available RAM
- Optimize PostgreSQL shared_buffers
- Configure Redis maxmemory settings
- Tune Nginx worker connections

## Security Considerations

### Default Security
- SSH key authentication only
- Firewall enabled and configured
- Regular security updates
- Non-root service execution

### Additional Hardening
- Change default passwords
- Configure VPN access
- Enable fail2ban
- Regular security audits

## Backup and Recovery

### Automated Backups
- Daily database backups
- Weekly full system backup
- Configuration file versioning
- Remote backup options

### Recovery Procedures
- System restore from backup
- Database recovery
- Configuration rollback
- Emergency procedures

## Support and Documentation

- See individual config files for detailed settings
- Check logs in `/var/log/cupcake/`
- System status: `sudo systemctl status cupcake-*`
- Resource usage: `htop` or monitoring dashboard