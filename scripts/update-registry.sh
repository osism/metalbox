#!/bin/bash

# Configuration variables
REGISTRY_URL="${REGISTRY_URL:-https://nbg1.your-objectstorage.com/osism/metalbox/registry.tar.bz2}"
REGISTRY_FILE="${REGISTRY_FILE:-registry.tar.bz2}"
DOWNLOAD_PATH="${DOWNLOAD_PATH:-/opt}"
CONTAINER_NAME="${CONTAINER_NAME:-registry}"
VOLUME_NAME="${VOLUME_NAME:-registry}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-false}"

set -e

# Determine tarball path
if [ "$SKIP_DOWNLOAD" = "true" ]; then
    echo "SKIP_DOWNLOAD is set to true, skipping download..."
    # Check both locations for the tarball, preferring /home/dragon
    if [ -f "/home/dragon/$REGISTRY_FILE" ]; then
        TARBALL_PATH="/home/dragon/$REGISTRY_FILE"
        echo "Using existing tarball from: $TARBALL_PATH"
    elif [ -f "$DOWNLOAD_PATH/$REGISTRY_FILE" ]; then
        TARBALL_PATH="$DOWNLOAD_PATH/$REGISTRY_FILE"
        echo "Using existing tarball from: $TARBALL_PATH"
    else
        echo "ERROR: $REGISTRY_FILE not found in /home/dragon or $DOWNLOAD_PATH and SKIP_DOWNLOAD is true!"
        exit 1
    fi
else
    echo "Downloading registry archive from: $REGISTRY_URL"
    echo "Saving to: $DOWNLOAD_PATH/$REGISTRY_FILE"

    # Remove existing file if it exists
    if [ -f "$DOWNLOAD_PATH/$REGISTRY_FILE" ]; then
        echo "Removing existing file: $DOWNLOAD_PATH/$REGISTRY_FILE"
        sudo rm -f "$DOWNLOAD_PATH/$REGISTRY_FILE"
    fi

    # Download the registry archive
    sudo curl -L -o "$DOWNLOAD_PATH/$REGISTRY_FILE" "$REGISTRY_URL"
    TARBALL_PATH="$DOWNLOAD_PATH/$REGISTRY_FILE"
fi

echo "Stopping existing registry container if running..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

echo "Removing existing registry volume if it exists..."
docker volume rm "$VOLUME_NAME" 2>/dev/null || true

echo "Creating new registry volume..."
docker volume create "$VOLUME_NAME"

echo "Extracting registry data to volume..."
# Extract the directory path and filename from TARBALL_PATH
TARBALL_DIR="$(dirname "$TARBALL_PATH")"
TARBALL_FILENAME="$(basename "$TARBALL_PATH")"
docker run --rm -v "$VOLUME_NAME":/volume -v "$TARBALL_DIR":/import:ro library/alpine:3 sh -c "cd /volume && tar xjf /import/$TARBALL_FILENAME"

echo "Starting new registry container..."
docker run -d -p 0.0.0.0:5001:5000 -v "$VOLUME_NAME":/var/lib/registry --name "$CONTAINER_NAME" --restart always library/registry:3

echo "Registry update completed successfully!"
