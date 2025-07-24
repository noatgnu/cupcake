#!/bin/bash

# CUPCAKE Pi Build - Logging Functions
# Provides consistent logging across all build scripts

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Generic logging functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

# Specialized logging functions for different components
log_cupcake() {
    echo -e "${GREEN}[CUPCAKE] $1${NC}"
}

log_config() {
    echo -e "${BLUE}[CONFIG] $1${NC}"
}

log_ssl() {
    echo -e "${YELLOW}[SSL] $1${NC}"
}