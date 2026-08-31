#!/bin/bash

# Configuration variables
REGISTRY_URL="${REGISTRY_URL:-https://nbg1.your-objectstorage.com/osism/metalbox/registry.tar.bz2}"
REGISTRY_FILE="${REGISTRY_FILE:-registry.tar.bz2}"
DOWNLOAD_PATH="${DOWNLOAD_PATH:-/opt}"
CONTAINER_NAME="${CONTAINER_NAME:-registry}"
VOLUME_NAME="${VOLUME_NAME:-registry}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-false}"

set -e

# Check Docker access before anything else. The teardown below is guarded
# `|| true` so it tolerates a missing container or volume -- but that also
# swallows "permission denied", and a run by a user outside the docker group
# then prints three reassuring progress lines while doing nothing at all.
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: cannot talk to the Docker daemon as $(id -un)." >&2
    echo "       Run this as a user in the docker group (dragon)." >&2
    exit 1
fi

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

    # Download the registry archive. --retry/--continue-at because these
    # archives are ~10 GB: a single dropped connection would otherwise mean
    # starting over, and leave a truncated file behind for a later
    # SKIP_DOWNLOAD=true run to consume.
    sudo curl -fL --retry 10 --retry-all-errors --retry-delay 15 \
        --continue-at - -o "$DOWNLOAD_PATH/$REGISTRY_FILE" "$REGISTRY_URL"
    TARBALL_PATH="$DOWNLOAD_PATH/$REGISTRY_FILE"
fi

# Verify the archive before anything is destroyed. Everything below this line
# is irreversible: the volume is removed and recreated before the archive is
# first read, so a truncated or corrupt file would leave the registry empty --
# at an air-gapped site, with no upstream to fall back on. `tar -j` fully
# decompresses the stream, so a full-length-but-corrupt file fails here too.
echo "Verifying $TARBALL_PATH ..."
if ! tar tjf "$TARBALL_PATH" >/dev/null; then
    echo "ERROR: $TARBALL_PATH is not a readable bzip2 archive." >&2
    echo "       Refusing to continue: the import would destroy the current" >&2
    echo "       registry volume before reading it." >&2
    exit 1
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
