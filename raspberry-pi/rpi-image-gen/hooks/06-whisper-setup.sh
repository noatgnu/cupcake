#!/bin/bash

# Hook script to setup Whisper.cpp for CUPCAKE Pi 5 deployment
# This script runs during the rpi-image-gen build process
# Based on CUPCAKE's transcribe worker Dockerfile implementation

set -e

echo "=== Setting up Whisper.cpp for CUPCAKE Pi 5 ==="

# Create whisper directory in /opt for system-wide installation
WHISPER_DIR="/opt/whisper.cpp"
mkdir -p "$WHISPER_DIR"
cd "$WHISPER_DIR"

# Clone Whisper.cpp repository (matching transcribe worker)
echo "Cloning Whisper.cpp repository..."
git clone https://github.com/ggerganov/whisper.cpp.git .

# Detect system capabilities for model selection
echo "Detecting system capabilities..."
TOTAL_RAM=$(free -m | awk 'NR==2{printf "%d", $2}')
CPU_CORES=$(nproc)
PI_MODEL=$(cat /proc/cpuinfo | grep "Revision" | awk '{print $3}' | head -1)

echo "System specs: ${TOTAL_RAM}MB RAM, ${CPU_CORES} CPU cores, Pi model revision: ${PI_MODEL}"

# Download models first (like transcribe worker does)
echo "Downloading Whisper models..."

# Always download tiny as fallback
./models/download-ggml-model.sh tiny.en

# Download appropriate models based on system capabilities
if [ "$TOTAL_RAM" -lt 2048 ]; then
    # Low memory systems (< 2GB) - tiny model only
    echo "Low memory system detected - using tiny model"
    DEFAULT_MODEL="/opt/whisper.cpp/models/ggml-tiny.en.bin"
    THREAD_COUNT="2"
elif [ "$TOTAL_RAM" -lt 4096 ]; then
    # Medium memory systems (2-4GB) - base model
    echo "Medium memory system detected - downloading base model"
    ./models/download-ggml-model.sh base.en
    DEFAULT_MODEL="/opt/whisper.cpp/models/ggml-base.en.bin"
    THREAD_COUNT="4"
else
    # High memory systems (4GB+) - small model (not medium like Docker to save space)
    echo "High memory system detected - downloading small model"
    ./models/download-ggml-model.sh small.en
    ./models/download-ggml-model.sh base.en   # backup
    DEFAULT_MODEL="/opt/whisper.cpp/models/ggml-small.en.bin"
    THREAD_COUNT="6"
fi

# Build Whisper.cpp (matching transcribe worker build commands exactly)
echo "Building Whisper.cpp..."
cmake -B build
cmake --build build --config Release -j $(nproc)

# Verify the binary was built correctly
if [ ! -f "build/bin/whisper-cli" ]; then
    echo "ERROR: whisper-cli binary not found after build!"
    exit 1
fi

echo "Build completed successfully. Binary location: $(pwd)/build/bin/whisper-cli"

# Set appropriate permissions
chown -R root:root "$WHISPER_DIR"
chmod +x "$WHISPER_DIR/build/bin/whisper-cli"

# Create environment configuration matching CUPCAKE settings.py format
echo "Creating Whisper.cpp environment configuration..."
cat > /etc/environment.d/50-whisper.conf << EOF
# Whisper.cpp configuration for CUPCAKE (matches settings.py)
WHISPERCPP_PATH=/opt/whisper.cpp/build/bin/whisper-cli
WHISPERCPP_DEFAULT_MODEL=${DEFAULT_MODEL}
WHISPERCPP_THREAD_COUNT=${THREAD_COUNT}
EOF

# Create systemd environment file for services
mkdir -p /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/whisper.conf << EOF
[Manager]
DefaultEnvironment=WHISPERCPP_PATH=/opt/whisper.cpp/build/bin/whisper-cli
DefaultEnvironment=WHISPERCPP_DEFAULT_MODEL=${DEFAULT_MODEL}
DefaultEnvironment=WHISPERCPP_THREAD_COUNT=${THREAD_COUNT}
EOF

# Test the installation
echo "Testing Whisper.cpp installation..."
if $WHISPER_DIR/build/bin/whisper-cli --help > /dev/null 2>&1; then
    echo "Whisper.cpp installation test passed"
else
    echo "WARNING: Whisper.cpp installation test failed"
fi

echo "=== Whisper.cpp setup completed ==="
echo "Binary path: /opt/whisper.cpp/build/bin/whisper-cli"
echo "Default model: ${DEFAULT_MODEL}"
echo "Thread count: ${THREAD_COUNT}"
echo "Model files available:"
ls -la "$WHISPER_DIR/models/" | grep "\.bin$" || echo "No model files found"