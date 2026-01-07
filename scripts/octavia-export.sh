#!/usr/bin/env bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values or use environment variables
OCTAVIA_BASE_URL="${OCTAVIA_BASE_URL:-https://nbg1.your-objectstorage.com/osism/openstack-octavia-amphora-image}"
OCTAVIA_EXPORT_SIZE="${OCTAVIA_EXPORT_SIZE:-1G}"

# Check if version parameter is provided
if [[ -z "$1" ]]; then
    echo -e "${RED}Error: OpenStack version parameter required${NC}"
    echo -e "Usage: $0 <version> (e.g., $0 2024.2)"
    exit 1
fi

OCTAVIA_VERSION="$1"
OCTAVIA_METADATA_FILE="last-${OCTAVIA_VERSION}"
OCTAVIA_EXPORT_IMAGE="octavia-export-${OCTAVIA_VERSION}.img"

echo -e "${GREEN}Creating Octavia export image for version ${OCTAVIA_VERSION}...${NC}"
echo -e "Base URL: ${OCTAVIA_BASE_URL}"
echo -e "Metadata file: ${OCTAVIA_METADATA_FILE}"
echo -e "Target image: ${OCTAVIA_EXPORT_IMAGE}"
echo -e "Image size: ${OCTAVIA_EXPORT_SIZE}"

# Create temporary working directory
TEMP_WORK_DIR=$(mktemp -d /tmp/octavia-export.XXXXXX)
trap "rm -rf '$TEMP_WORK_DIR' 2>/dev/null || true" EXIT

echo -e "${YELLOW}Downloading metadata file...${NC}"
METADATA_URL="${OCTAVIA_BASE_URL}/${OCTAVIA_METADATA_FILE}"
METADATA_PATH="${TEMP_WORK_DIR}/${OCTAVIA_METADATA_FILE}"

if ! wget -q -O "$METADATA_PATH" "$METADATA_URL"; then
    echo -e "${RED}Error: Failed to download metadata file from ${METADATA_URL}${NC}"
    exit 1
fi

echo -e "${GREEN}Metadata file downloaded successfully${NC}"

# Parse the image filename from metadata
# Expected format: "YYYY-MM-DD octavia-amphora-haproxy-VERSION.DATE.qcow2"
IMAGE_FILENAME=$(cat "$METADATA_PATH" | awk '{print $2}')

if [[ -z "$IMAGE_FILENAME" ]]; then
    echo -e "${RED}Error: Could not parse image filename from metadata file${NC}"
    echo -e "Metadata content:"
    cat "$METADATA_PATH"
    exit 1
fi

echo -e "${GREEN}Image filename from metadata: ${IMAGE_FILENAME}${NC}"

# Download the actual image file
echo -e "${YELLOW}Downloading Octavia image: ${IMAGE_FILENAME}...${NC}"
IMAGE_URL="${OCTAVIA_BASE_URL}/${IMAGE_FILENAME}"
IMAGE_PATH="${TEMP_WORK_DIR}/${IMAGE_FILENAME}"

if ! wget -q -O "$IMAGE_PATH" "$IMAGE_URL"; then
    echo -e "${RED}Error: Failed to download image file from ${IMAGE_URL}${NC}"
    exit 1
fi

echo -e "${GREEN}Image file downloaded successfully${NC}"

# Download the checksum file
CHECKSUM_FILENAME="${IMAGE_FILENAME}.CHECKSUM"
echo -e "${YELLOW}Downloading checksum file: ${CHECKSUM_FILENAME}...${NC}"
CHECKSUM_URL="${OCTAVIA_BASE_URL}/${CHECKSUM_FILENAME}"
CHECKSUM_PATH="${TEMP_WORK_DIR}/${CHECKSUM_FILENAME}"

if ! wget -q -O "$CHECKSUM_PATH" "$CHECKSUM_URL"; then
    echo -e "${RED}Error: Failed to download checksum file from ${CHECKSUM_URL}${NC}"
    exit 1
fi

echo -e "${GREEN}Checksum file downloaded successfully${NC}"

# Verify both files exist
if [[ ! -f "$METADATA_PATH" ]]; then
    echo -e "${RED}Error: Metadata file not found at ${METADATA_PATH}${NC}"
    exit 1
fi

if [[ ! -f "$IMAGE_PATH" ]]; then
    echo -e "${RED}Error: Image file not found at ${IMAGE_PATH}${NC}"
    exit 1
fi

if [[ ! -f "$CHECKSUM_PATH" ]]; then
    echo -e "${RED}Error: Checksum file not found at ${CHECKSUM_PATH}${NC}"
    exit 1
fi

echo -e "${YELLOW}Creating disk image of size ${OCTAVIA_EXPORT_SIZE}...${NC}"
if ! dd if=/dev/zero of="$OCTAVIA_EXPORT_IMAGE" bs=1 count=0 seek="$OCTAVIA_EXPORT_SIZE" 2>/dev/null; then
    echo -e "${RED}Error: Failed to create disk image${NC}"
    exit 1
fi

echo -e "${YELLOW}Creating ext4 filesystem on image...${NC}"
if ! mkfs.ext4 -F "$OCTAVIA_EXPORT_IMAGE" >/dev/null 2>&1; then
    echo -e "${RED}Error: Failed to create ext4 filesystem${NC}"
    rm -f "$OCTAVIA_EXPORT_IMAGE"
    exit 1
fi

# Create temporary mount point
TEMP_MOUNT_DIR=$(mktemp -d /tmp/octavia-export-mount.XXXXXX)
trap "sudo umount '$TEMP_MOUNT_DIR' 2>/dev/null || true; rmdir '$TEMP_MOUNT_DIR' 2>/dev/null || true; rm -rf '$TEMP_WORK_DIR' 2>/dev/null || true" EXIT

echo -e "${YELLOW}Mounting image...${NC}"
if ! sudo mount -o loop "$OCTAVIA_EXPORT_IMAGE" "$TEMP_MOUNT_DIR"; then
    echo -e "${RED}Error: Failed to mount image${NC}"
    rm -f "$OCTAVIA_EXPORT_IMAGE"
    exit 1
fi

echo -e "${YELLOW}Copying files to image...${NC}"

# Copy metadata file
echo -e "  Copying ${OCTAVIA_METADATA_FILE}..."
if ! sudo cp "$METADATA_PATH" "$TEMP_MOUNT_DIR/$OCTAVIA_METADATA_FILE"; then
    echo -e "${RED}Error: Failed to copy ${OCTAVIA_METADATA_FILE} to image${NC}"
    sudo umount "$TEMP_MOUNT_DIR"
    rm -f "$OCTAVIA_EXPORT_IMAGE"
    exit 1
fi

# Copy image file
echo -e "  Copying ${IMAGE_FILENAME}..."
if ! sudo cp "$IMAGE_PATH" "$TEMP_MOUNT_DIR/$IMAGE_FILENAME"; then
    echo -e "${RED}Error: Failed to copy ${IMAGE_FILENAME} to image${NC}"
    sudo umount "$TEMP_MOUNT_DIR"
    rm -f "$OCTAVIA_EXPORT_IMAGE"
    exit 1
fi

# Copy checksum file
echo -e "  Copying ${CHECKSUM_FILENAME}..."
if ! sudo cp "$CHECKSUM_PATH" "$TEMP_MOUNT_DIR/$CHECKSUM_FILENAME"; then
    echo -e "${RED}Error: Failed to copy ${CHECKSUM_FILENAME} to image${NC}"
    sudo umount "$TEMP_MOUNT_DIR"
    rm -f "$OCTAVIA_EXPORT_IMAGE"
    exit 1
fi

echo -e "${YELLOW}Unmounting image...${NC}"
sudo umount "$TEMP_MOUNT_DIR"

echo -e "${GREEN}Octavia export image created successfully: ${OCTAVIA_EXPORT_IMAGE}${NC}"
echo -e "${GREEN}Contains: ${OCTAVIA_METADATA_FILE}, ${IMAGE_FILENAME}, and ${CHECKSUM_FILENAME}${NC}"
