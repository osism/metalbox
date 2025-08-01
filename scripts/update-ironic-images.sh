#!/bin/bash

# Configuration variables
BASE_URL="${BASE_URL:-https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images}"
TARGET_PATH="${TARGET_PATH:-/opt/httpd/data/root}"
SOURCE_PATH="${SOURCE_PATH:-/home/dragon}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-false}"

# List of Ironic images to download
IRONIC_IMAGES=(
    "osism-ipa.initramfs"
    "osism-ipa.kernel"
    "osism-node.qcow2"
    "osism-node.qcow2.CHECKSUM"
    "osism-esp.raw"
)

set -e

echo "Starting Ironic images update..."

# Create target directory if it doesn't exist
if [ ! -d "$TARGET_PATH" ]; then
    echo "Creating target directory: $TARGET_PATH"
    sudo mkdir -p "$TARGET_PATH"
fi

# Process each image
for IMAGE in "${IRONIC_IMAGES[@]}"; do
    echo "Processing image: $IMAGE"
    
    if [ "$SKIP_DOWNLOAD" = "true" ]; then
        echo "SKIP_DOWNLOAD is set to true, skipping download for $IMAGE..."
        
        # Check if image exists in source path
        if [ -f "$SOURCE_PATH/$IMAGE" ]; then
            echo "Found $IMAGE in $SOURCE_PATH"
            echo "Copying $IMAGE to $TARGET_PATH..."
            sudo cp "$SOURCE_PATH/$IMAGE" "$TARGET_PATH/"
            echo "Successfully copied $IMAGE"
        else
            echo "WARNING: Expected image $IMAGE not found in $SOURCE_PATH!"
        fi
    else
        echo "Downloading $IMAGE from: $BASE_URL/$IMAGE"
        echo "Saving to: $TARGET_PATH/$IMAGE"
        
        # Download the image directly to target path
        sudo curl -L -o "$TARGET_PATH/$IMAGE" "$BASE_URL/$IMAGE"
        
        if [ -f "$TARGET_PATH/$IMAGE" ]; then
            echo "Successfully downloaded $IMAGE"
        else
            echo "ERROR: Failed to download $IMAGE"
            exit 1
        fi
    fi
    
    echo "---"
done

echo "Ironic images update completed successfully!"
echo "All images are now available in: $TARGET_PATH"

# List the files in the target directory for verification
echo "Files in $TARGET_PATH:"
ls -la "$TARGET_PATH"
