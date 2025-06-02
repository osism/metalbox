#!/usr/bin/env bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values or use environment variables
SONIC_FILENAME="${SONIC_FILENAME:-sonic-broadcom-enterprise-base.bin}"
SONIC_EXPORT_SIZE="${SONIC_EXPORT_SIZE:-2G}"
SONIC_EXPORT_FILENAME="${SONIC_EXPORT_FILENAME:-sonic-export.img}"

echo -e "${GREEN}Creating SONiC export image...${NC}"
echo -e "Source file: ${SONIC_FILENAME}"
echo -e "Target image: ${SONIC_EXPORT_FILENAME}"
echo -e "Image size: ${SONIC_EXPORT_SIZE}"

# Check if source file exists
if [[ ! -f "$SONIC_FILENAME" ]]; then
    echo -e "${RED}Error: Source file ${SONIC_FILENAME} not found${NC}"
    exit 1
fi

echo -e "${YELLOW}Creating disk image of size ${SONIC_EXPORT_SIZE}...${NC}"
if ! dd if=/dev/zero of="$SONIC_EXPORT_FILENAME" bs=1 count=0 seek="$SONIC_EXPORT_SIZE" 2>/dev/null; then
    echo -e "${RED}Error: Failed to create disk image${NC}"
    exit 1
fi

echo -e "${YELLOW}Creating ext4 filesystem on image...${NC}"
if ! mkfs.ext4 -F "$SONIC_EXPORT_FILENAME" >/dev/null 2>&1; then
    echo -e "${RED}Error: Failed to create ext4 filesystem${NC}"
    rm -f "$SONIC_EXPORT_FILENAME"
    exit 1
fi

# Create temporary mount point
TEMP_MOUNT_DIR=$(mktemp -d /tmp/sonic-export.XXXXXX)
trap "sudo umount '$TEMP_MOUNT_DIR' 2>/dev/null || true; rmdir '$TEMP_MOUNT_DIR' 2>/dev/null || true" EXIT

echo -e "${YELLOW}Mounting image...${NC}"
if ! sudo mount -o loop "$SONIC_EXPORT_FILENAME" "$TEMP_MOUNT_DIR"; then
    echo -e "${RED}Error: Failed to mount image${NC}"
    rm -f "$SONIC_EXPORT_FILENAME"
    exit 1
fi

echo -e "${YELLOW}Copying ${SONIC_FILENAME} to image...${NC}"
if ! sudo cp "$SONIC_FILENAME" "$TEMP_MOUNT_DIR/"; then
    echo -e "${RED}Error: Failed to copy file to image${NC}"
    sudo umount "$TEMP_MOUNT_DIR"
    rm -f "$SONIC_EXPORT_FILENAME"
    exit 1
fi

echo -e "${YELLOW}Unmounting image...${NC}"
sudo umount "$TEMP_MOUNT_DIR"

echo -e "${GREEN}SONiC export image created successfully: ${SONIC_EXPORT_FILENAME}${NC}"
