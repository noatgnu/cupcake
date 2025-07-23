# CUPCAKE Pi Image Build Methods Comparison

## Quick Reference

| Feature | Docker Build | Native Build | GitHub Actions |
|---------|-------------|-------------|----------------|
| **Command** | `./build-pi-image-docker.sh` | `./build-pi-image.sh` | Workflow dispatch |
| **Host Impact** | ✅ Isolated | ⚠️ Installs packages | ✅ Isolated |
| **Prerequisites** | Docker only | Many packages | Automatic |
| **Setup Time** | ~15 min (first run) | ~5 min | ~10 min |
| **Build Time** | 1-3 hours | 1-3 hours | 1-3 hours |
| **Consistency** | ✅ Always same | ⚠️ Varies by host | ✅ Always same |
| **Cleanup** | ✅ Automatic | ⚠️ Manual | ✅ Automatic |
| **Disk Usage** | ~8GB | ~6GB | N/A |
| **Debugging** | ✅ Easy | ✅ Direct | ⚠️ Limited |

## Detailed Comparison

### 🐳 Docker Build (`build-pi-image-docker.sh`)

**Best for:**
- Production image builds
- Development environments
- Systems where you don't want to install dependencies
- Consistent builds across different machines
- CI/CD pipelines (local)

**Pros:**
- ✅ Complete isolation from host system
- ✅ Reproducible builds
- ✅ Automatic cleanup
- ✅ No dependency conflicts
- ✅ Works on any Docker-capable system
- ✅ Easy to debug (interactive containers)

**Cons:**
- ❌ Requires Docker installation
- ❌ Larger disk usage (~8GB total)
- ❌ Slower first run (Docker image build)
- ❌ Needs privileged Docker access

**System Requirements:**
- Docker installed and running
- 10GB+ free disk space
- 4GB+ RAM (8GB+ recommended)
- Privileged container support

### 🔧 Native Build (`build-pi-image.sh`)

**Best for:**
- Quick one-off builds
- Systems where Docker isn't available
- Development and testing
- When you need direct access to build process

**Pros:**
- ✅ Direct access to all build components
- ✅ Slightly faster (no container overhead)
- ✅ Lower disk usage (~6GB)
- ✅ No Docker dependency
- ✅ Easier to modify pi-gen process

**Cons:**
- ❌ Installs many packages on host system
- ❌ Build environment varies by host
- ❌ Manual cleanup required
- ❌ Potential dependency conflicts
- ❌ Requires Ubuntu/Debian host

**System Requirements:**
- Ubuntu/Debian system with apt
- 8GB+ free disk space
- 4GB+ RAM (8GB+ recommended)
- sudo access for package installation

### 🚀 GitHub Actions Build (Workflow)

**Best for:**
- Automated builds on code changes
- Release management
- Team collaboration
- Official image distribution

**Pros:**
- ✅ Fully automated
- ✅ No local resources used
- ✅ Consistent cloud environment
- ✅ Built-in artifact management
- ✅ Version tagging and releases
- ✅ Parallel Pi 4 & Pi 5 builds

**Cons:**
- ❌ Limited debugging capabilities
- ❌ Depends on GitHub runners
- ❌ Build time limits (6 hours max)
- ❌ Internet connection required

## Usage Recommendations

### For Development
```bash
# Quick testing - native build
./build-pi-image.sh pi5 test-$(date +%s)

# Consistent testing - docker build  
./build-pi-image-docker.sh pi5 dev-v1.0
```

### For Production
```bash
# Local production build - docker (recommended)
./build-pi-image-docker.sh pi5 v1.0.0

# Team/release builds - GitHub Actions
# Use workflow dispatch via GitHub web interface
```

### For CI/CD Integration
```bash
# In CI pipeline with Docker
docker run --privileged \
  -v $(pwd):/workspace \
  -w /workspace/raspberry-pi \
  ubuntu:22.04 \
  ./build-pi-image-docker.sh pi5 ci-$(git rev-parse --short HEAD)
```

## Output Comparison

All methods produce identical output files:

```
output/
├── cupcake-pi5-YYYY-MM-DD.img.xz          # Compressed image
└── cupcake-pi5-YYYY-MM-DD.img.xz.sha256   # Checksum
```

The images are functionally identical regardless of build method.

## Troubleshooting by Method

### Docker Build Issues
- **Container won't start**: Check privileged mode
- **Build fails**: Check Docker daemon and disk space
- **Permission errors**: Ensure Docker group membership

### Native Build Issues  
- **Package conflicts**: Use clean Ubuntu/Debian system
- **Permission errors**: Ensure sudo access
- **Space issues**: Clean apt cache and old builds

### GitHub Actions Issues
- **Workflow fails**: Check runner resources and logs
- **Timeout**: Build may exceed 6-hour limit
- **Artifact missing**: Check build completion

## Performance Tips

### Speed Up Docker Builds
```bash
# Reuse existing Docker image
docker images | grep cupcake-pi-builder

# Use build cache
docker build --cache-from cupcake-pi-builder:latest
```

### Speed Up Native Builds
```bash
# Skip package updates if recent
export SKIP_APT_UPDATE=1

# Use local pi-gen repo
export PI_GEN_REPO=/path/to/existing/pi-gen
```

### Optimize Disk Usage
```bash
# Clean Docker after build  
docker system prune -a

# Clean native build artifacts
rm -rf pi-gen/work pi-gen/deploy
```