#!/bin/bash

# Help function
show_help() {
    cat << EOF
Usage: $0 [IMAGE_FILTER]

Download and manage Ironic images with optional filtering.

Arguments:
  IMAGE_FILTER    Filter images by type: node, ipa, esp (optional)
                  Can also be set via IMAGE_FILTER environment variable
                  Default: all images are processed

Environment Variables:
  BASE_URL        Base URL for image downloads
  TARGET_PATH     Target directory for images (default: /opt/httpd/data/root)
  SOURCE_PATH     Source directory when SKIP_DOWNLOAD=true (default: /home/dragon)
  SKIP_DOWNLOAD   Skip download and copy from SOURCE_PATH (default: false)
  IMAGE_FILTER    Filter images by type: node, ipa, esp (optional)

Examples:
  $0              # Process all images
  $0 node         # Process only osism-node images
  $0 ipa          # Process only osism-ipa images
  $0 esp          # Process only osism-esp images
  IMAGE_FILTER=node $0  # Process only osism-node images via env var

EOF
}

# Parse command line arguments
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Configuration variables
BASE_URL="${BASE_URL:-https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images}"
TARGET_PATH="${TARGET_PATH:-/opt/httpd/data/root}"
SOURCE_PATH="${SOURCE_PATH:-/home/dragon}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-false}"

# Image filtering - command line argument takes precedence over environment variable
IMAGE_FILTER="${1:-${IMAGE_FILTER:-}}"

# All available Ironic images
ALL_IRONIC_IMAGES=(
    "osism-ipa.initramfs"
    "osism-ipa.kernel"
    "osism-node.qcow2"
    "osism-node.qcow2.CHECKSUM"
    "osism-esp.raw"
)

# Function to filter images based on IMAGE_FILTER
get_filtered_images() {
    local filter="$1"
    local filtered_images=()
    
    case "$filter" in
        "node")
            for image in "${ALL_IRONIC_IMAGES[@]}"; do
                if [[ "$image" == *"osism-node"* ]]; then
                    filtered_images+=("$image")
                fi
            done
            ;;
        "ipa")
            for image in "${ALL_IRONIC_IMAGES[@]}"; do
                if [[ "$image" == *"osism-ipa"* ]]; then
                    filtered_images+=("$image")
                fi
            done
            ;;
        "esp")
            for image in "${ALL_IRONIC_IMAGES[@]}"; do
                if [[ "$image" == *"osism-esp"* ]]; then
                    filtered_images+=("$image")
                fi
            done
            ;;
        "")
            # No filter - use all images
            filtered_images=("${ALL_IRONIC_IMAGES[@]}")
            ;;
        *)
            echo "ERROR: Invalid image filter '$filter'. Valid options: node, ipa, esp"
            echo "Use '$0 --help' for more information."
            exit 1
            ;;
    esac
    
    printf '%s\n' "${filtered_images[@]}"
}

# Get the list of images to process
readarray -t IRONIC_IMAGES < <(get_filtered_images "$IMAGE_FILTER")

set -e

echo "Starting Ironic images update..."
if [[ -n "$IMAGE_FILTER" ]]; then
    echo "Image filter: $IMAGE_FILTER"
else
    echo "Processing all images (no filter applied)"
fi
echo "Images to process: ${#IRONIC_IMAGES[@]}"

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
