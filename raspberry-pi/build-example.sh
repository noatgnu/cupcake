#!/bin/bash

# Example script showing how to use the modular prebuild-frontend.sh

set -e

echo "=== CUPCAKE Pi Image Build Example ==="
echo

# Example 1: Pre-build frontend then build Pi image
echo "Example 1: Pre-build frontend on x86, then build Pi image"
echo "--------------------------------------------------------"
echo
echo "# Step 1: Pre-build the frontend (fast on x86)"
echo "./prebuild-frontend.sh --hostname cupcake-pi5.local --output-dir ./frontend-dist"
echo
echo "# Step 2: Build Pi image using pre-built frontend"
echo "export USE_PREBUILT_FRONTEND=1"
echo "export PREBUILT_FRONTEND_DIR=./frontend-dist"
echo "./build-pi-image.sh pi5 latest 1"
echo

# Example 2: Build Pi image with automatic pre-build
echo "Example 2: Build Pi image with automatic pre-build fallback"
echo "----------------------------------------------------------"
echo
echo "# If no pre-built frontend exists, the build script will automatically"
echo "# try to run prebuild-frontend.sh if USE_PREBUILT_FRONTEND=1"
echo "export USE_PREBUILT_FRONTEND=1"
echo "./build-pi-image.sh pi4 latest 1"
echo

# Example 3: Native Pi build (no pre-build needed)
echo "Example 3: Native Pi build (traditional method)"
echo "-----------------------------------------------"
echo
echo "# On native Pi hardware, you can build normally without pre-build"
echo "# (though pre-build will still be faster)"
echo "./build-pi-image.sh pi5 latest 1"
echo

# Example 4: Custom deployment
echo "Example 4: Custom deployment with different hostname"
echo "--------------------------------------------------"
echo
echo "# Pre-build for custom hostname"
echo "./prebuild-frontend.sh --hostname my-lab-pi.local --output-dir ./custom-frontend"
echo
echo "# Build image with custom frontend"
echo "export USE_PREBUILT_FRONTEND=1"
echo "export PREBUILT_FRONTEND_DIR=./custom-frontend"
echo "./build-pi-image.sh pi5 custom-v1.0 1"
echo

echo "=== Usage Tips ==="
echo
echo "1. Pre-building on x86 is 10-20x faster than building in QEMU"
echo "2. The prebuild-frontend.sh script works on any platform (x86, ARM64, ARMv7)"
echo "3. You can pre-build once and reuse for multiple Pi image builds"
echo "4. The build script automatically detects and uses pre-built frontends"
echo "5. GitHub Actions uses this approach for optimal performance"
echo

echo "=== Environment Variables ==="
echo
echo "USE_PREBUILT_FRONTEND=1     # Enable pre-built frontend usage"
echo "PREBUILT_FRONTEND_DIR=path  # Custom path to pre-built frontend"
echo "KEEP_BUILD_DIR=1           # Keep build directory after prebuild"
echo

echo "For more details:"
echo "./prebuild-frontend.sh --help"
echo "./build-pi-image.sh --help  # (when implemented)"