#!/bin/bash

# Configuration variables
REPOSITORY_URL="${REPOSITORY_URL:-https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/metalbox/ubuntu-noble.tar.bz2}"
REPOSITORY_FILE="${REPOSITORY_FILE:-ubuntu-noble.tar.bz2}"
DOWNLOAD_PATH="${DOWNLOAD_PATH:-/opt}"
CONTAINER_REGISTRY="${CONTAINER_REGISTRY:-127.0.0.1:5001}"
REPOSITORY_IMAGE="${REPOSITORY_IMAGE:-osism/ubuntu-noble}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-false}"

set -e

# Determine tarball path
if [ "$SKIP_DOWNLOAD" = "true" ]; then
    echo "SKIP_DOWNLOAD is set to true, skipping download..."
    # Check both locations for the tarball, preferring /home/dragon
    if [ -f "/home/dragon/$REPOSITORY_FILE" ]; then
        TARBALL_PATH="/home/dragon/$REPOSITORY_FILE"
        echo "Using existing tarball from: $TARBALL_PATH"
    elif [ -f "$DOWNLOAD_PATH/$REPOSITORY_FILE" ]; then
        TARBALL_PATH="$DOWNLOAD_PATH/$REPOSITORY_FILE"
        echo "Using existing tarball from: $TARBALL_PATH"
    else
        echo "ERROR: $REPOSITORY_FILE not found in /home/dragon or $DOWNLOAD_PATH and SKIP_DOWNLOAD is true!"
        exit 1
    fi
else
    echo "Downloading repository archive from: $REPOSITORY_URL"
    echo "Saving to: $DOWNLOAD_PATH/$REPOSITORY_FILE"

    # Remove existing file if it exists
    if [ -f "$DOWNLOAD_PATH/$REPOSITORY_FILE" ]; then
        echo "Removing existing file: $DOWNLOAD_PATH/$REPOSITORY_FILE"
        sudo rm -f "$DOWNLOAD_PATH/$REPOSITORY_FILE"
    fi

    # Download the repository archive
    sudo curl -L -o "$DOWNLOAD_PATH/$REPOSITORY_FILE" "$REPOSITORY_URL"
    TARBALL_PATH="$DOWNLOAD_PATH/$REPOSITORY_FILE"
fi

echo "Loading container image from tarball..."
# Extract the directory path and filename from TARBALL_PATH
TARBALL_DIR="$(dirname "$TARBALL_PATH")"
TARBALL_FILENAME="$(basename "$TARBALL_PATH")"

# Load the container image from the tarball
docker load -i "$TARBALL_PATH"

# Get the loaded image name (assuming it's the first one loaded)
LOADED_IMAGE=$(docker load -i "$TARBALL_PATH" 2>&1 | grep "Loaded image" | cut -d: -f2- | xargs)

if [ -z "$LOADED_IMAGE" ]; then
    echo "ERROR: Could not determine loaded image name!"
    exit 1
fi

echo "Loaded image: $LOADED_IMAGE"

# Tag the image for the local registry
TARGET_IMAGE="$CONTAINER_REGISTRY/$REPOSITORY_IMAGE:latest"
echo "Tagging image as: $TARGET_IMAGE"
docker tag "$LOADED_IMAGE" "$TARGET_IMAGE"

echo "Pushing image to container registry..."
docker push "$TARGET_IMAGE"

echo "Repository update completed successfully!"
echo "Image available at: $TARGET_IMAGE"

echo "Deploying httpd service to import/update repository..."
osism apply httpd
echo "httpd service deployment completed successfully!"
