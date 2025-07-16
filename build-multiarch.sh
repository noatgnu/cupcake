#!/bin/bash

# Multi-architecture Docker build script for cupcake base image
# Supports: linux/amd64, linux/arm64 (includes Apple Silicon compatibility)

set -e

IMAGE_NAME="cupcake-base"
TAG="${1:-latest}"
DOCKERFILE_PATH="./dockerfiles/Dockerfile-base"
PUSH_FLAG="${2:-false}"

echo "Building multi-architecture Docker image: ${IMAGE_NAME}:${TAG}"

# Check if buildx is available
if ! docker buildx version > /dev/null 2>&1; then
    echo "Error: Docker buildx is required for multi-architecture builds"
    echo "Please install Docker Desktop or enable buildx in your Docker installation"
    exit 1
fi

# Create a new builder instance if it doesn't exist
BUILDER_NAME="cupcake-multiarch-builder"
if ! docker buildx ls | grep -q "${BUILDER_NAME}"; then
    echo "Creating new buildx builder: ${BUILDER_NAME}"
    docker buildx create --name "${BUILDER_NAME}" --driver docker-container --bootstrap
fi

# Use the builder
docker buildx use "${BUILDER_NAME}"

# Determine build command based on push flag
if [ "$PUSH_FLAG" = "push" ]; then
    echo "Building and pushing for platforms: linux/amd64,linux/arm64"
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --file "${DOCKERFILE_PATH}" \
        --tag "${IMAGE_NAME}:${TAG}" \
        --push \
        .
    echo "Multi-architecture build and push completed successfully!"
else
    echo "Building locally for platforms: linux/amd64,linux/arm64"
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --file "${DOCKERFILE_PATH}" \
        --tag "${IMAGE_NAME}:${TAG}" \
        --load \
        .
    echo "Multi-architecture build completed successfully!"
    echo "Note: --load only loads one architecture (your host architecture) to local Docker"
    echo "To push to registry, run: ./build-multiarch.sh ${TAG} push"
fi

echo "Image: ${IMAGE_NAME}:${TAG}"
echo "Platforms: linux/amd64, linux/arm64"
echo ""
echo "To test the image on different architectures:"
echo "  docker run --platform linux/amd64 ${IMAGE_NAME}:${TAG}"
echo "  docker run --platform linux/arm64 ${IMAGE_NAME}:${TAG}"
