#!/bin/bash

# Configuration variables
REGISTRY_URL="${REGISTRY_URL:-https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/metalbox/registry.tar.bz2}"
REGISTRY_FILE="${REGISTRY_FILE:-registry.tar.bz2}"
DOWNLOAD_PATH="${DOWNLOAD_PATH:-/opt}"
CONTAINER_NAME="${CONTAINER_NAME:-registry}"
VOLUME_NAME="${VOLUME_NAME:-registry}"

set -e

echo "Downloading registry archive from: $REGISTRY_URL"
echo "Saving to: $DOWNLOAD_PATH/$REGISTRY_FILE"

# Remove existing file if it exists
if [ -f "$DOWNLOAD_PATH/$REGISTRY_FILE" ]; then
    echo "Removing existing file: $DOWNLOAD_PATH/$REGISTRY_FILE"
    rm -f "$DOWNLOAD_PATH/$REGISTRY_FILE"
fi

# Download the registry archive
curl -L -o "$DOWNLOAD_PATH/$REGISTRY_FILE" "$REGISTRY_URL"

echo "Stopping existing registry container if running..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

echo "Removing existing registry volume if it exists..."
docker volume rm "$VOLUME_NAME" 2>/dev/null || true

echo "Creating new registry volume..."
docker volume create "$VOLUME_NAME"

echo "Extracting registry data to volume..."
docker run --rm -v "$VOLUME_NAME":/volume -v "$DOWNLOAD_PATH":/import library/alpine:3 sh -c "cd /volume && tar xjf /import/$REGISTRY_FILE"

echo "Starting new registry container..."
docker run -d -p 127.0.0.1:5000:5000 -v "$VOLUME_NAME":/var/lib/registry --name "$CONTAINER_NAME" --restart always library/registry:3

echo "Registry update completed successfully!"
