#!/bin/bash

# Configuration variables
REPOSITORY_URL="${REPOSITORY_URL:-https://nbg1.your-objectstorage.com/osism/metalbox/ubuntu-noble.tar.bz2}"
REPOSITORY_FILE="${REPOSITORY_FILE:-ubuntu-noble.tar.bz2}"
DOWNLOAD_PATH="${DOWNLOAD_PATH:-/opt}"
CONTAINER_REGISTRY="${CONTAINER_REGISTRY:-localhost:5001}"
REPOSITORY_IMAGE="${REPOSITORY_IMAGE:-osism/packages/ubuntu-noble}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-false}"
SKIP_PUSH="${SKIP_PUSH:-true}"
SKIP_SYNC="${SKIP_SYNC:-false}"
DATA_DIRECTORY="${DATA_DIRECTORY:-/opt/httpd/data}"

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

# Load the container image from the tarball and capture the image name
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

if [ "$SKIP_PUSH" = "true" ]; then
    echo "SKIP_PUSH is set to true, skipping push to registry..."
else
    echo "Pushing image to container registry..."
    docker push "$TARGET_IMAGE"
fi

echo "Repository update completed successfully!"
echo "Image available at: $TARGET_IMAGE"

# Sync repository data from the container image to the httpd data directory.
# This replicates what the Ansible httpd role does via the httpd-data container:
# the rsync base image's CMD is "rsync -avz /data/ /export/root/"
if [ "$SKIP_SYNC" = "true" ]; then
    echo "SKIP_SYNC is set to true, skipping repository data sync..."
    exit 0
fi

if [ ! -d "/opt/httpd/data/root" ]; then
    if grep -qE "^httpd_data_enable:[[:space:]]*false[[:space:]]*$" /opt/configuration/environments/infrastructure/configuration.yml 2>/dev/null; then
        echo "Creating /opt/httpd/data/root (httpd_data_enable: false)..."
        sudo mkdir -p /opt/httpd/data/root
        sudo chown dragon:dragon /opt/httpd /opt/httpd/data /opt/httpd/data/root
        sudo chmod 0750 /opt/httpd
        sudo chmod 0755 /opt/httpd/data
        sudo chmod 0755 /opt/httpd/data/root
    fi
fi

if [ -d "/opt/httpd/data/root" ]; then
    echo "Syncing repository data to $DATA_DIRECTORY/root/ubuntu-noble..."
    docker run --rm \
        -e USER_ID="$(stat -c %u "$DATA_DIRECTORY")" \
        -e GROUP_ID="$(stat -c %g "$DATA_DIRECTORY")" \
        -v "$DATA_DIRECTORY:/export" \
        "$TARGET_IMAGE"
    echo "Repository data sync completed successfully!"
else
    echo "Skipping repository data sync: /opt/httpd/data/root does not exist."
    echo "Note: On initial Metalbox deployment, the initial import runs automatically afterwards."
fi
