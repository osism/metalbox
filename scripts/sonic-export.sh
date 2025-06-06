#!/usr/bin/env bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values or use environment variables
SONIC_PATTERN="${SONIC_PATTERN:-sonic-broadcom-enterprise-base*.bin}"
SONIC_EXPORT_SIZE="${SONIC_EXPORT_SIZE:-2G}"
SONIC_EXPORT_IMAGE="${SONIC_EXPORT_IMAGE:-sonic-export.img}"

echo -e "${GREEN}Creating SONiC export image...${NC}"
echo -e "Source pattern: ${SONIC_PATTERN}"
echo -e "Target image: ${SONIC_EXPORT_IMAGE}"
echo -e "Image size: ${SONIC_EXPORT_SIZE}"

# Find files matching the pattern
FOUND_FILES=()
for file in ${SONIC_PATTERN}; do
    if [[ -f "$file" ]]; then
        FOUND_FILES+=("$file")
    fi
done

# Check if any files were found
if [[ ${#FOUND_FILES[@]} -eq 0 ]]; then
    echo -e "${RED}Error: No files matching pattern ${SONIC_PATTERN} found${NC}"
    exit 1
fi

echo -e "${GREEN}Found ${#FOUND_FILES[@]} file(s) matching pattern:${NC}"
for file in "${FOUND_FILES[@]}"; do
    echo -e "  - $file"
done

echo -e "${YELLOW}Creating disk image of size ${SONIC_EXPORT_SIZE}...${NC}"
if ! dd if=/dev/zero of="$SONIC_EXPORT_IMAGE" bs=1 count=0 seek="$SONIC_EXPORT_SIZE" 2>/dev/null; then
    echo -e "${RED}Error: Failed to create disk image${NC}"
    exit 1
fi

echo -e "${YELLOW}Creating ext4 filesystem on image...${NC}"
if ! mkfs.ext4 -F "$SONIC_EXPORT_IMAGE" >/dev/null 2>&1; then
    echo -e "${RED}Error: Failed to create ext4 filesystem${NC}"
    rm -f "$SONIC_EXPORT_IMAGE"
    exit 1
fi

# Create temporary mount point
TEMP_MOUNT_DIR=$(mktemp -d /tmp/sonic-export.XXXXXX)
trap "sudo umount '$TEMP_MOUNT_DIR' 2>/dev/null || true; rmdir '$TEMP_MOUNT_DIR' 2>/dev/null || true" EXIT

echo -e "${YELLOW}Mounting image...${NC}"
if ! sudo mount -o loop "$SONIC_EXPORT_IMAGE" "$TEMP_MOUNT_DIR"; then
    echo -e "${RED}Error: Failed to mount image${NC}"
    rm -f "$SONIC_EXPORT_IMAGE"
    exit 1
fi

echo -e "${YELLOW}Copying files to image...${NC}"
for file in "${FOUND_FILES[@]}"; do
    basename=$(basename "$file")
    echo -e "  Copying $basename..."
    if ! sudo cp "$file" "$TEMP_MOUNT_DIR/$basename"; then
        echo -e "${RED}Error: Failed to copy $basename to image${NC}"
        sudo umount "$TEMP_MOUNT_DIR"
        rm -f "$SONIC_EXPORT_IMAGE"
        exit 1
    fi
done

echo -e "${YELLOW}Unmounting image...${NC}"
sudo umount "$TEMP_MOUNT_DIR"

echo -e "${GREEN}SONiC export image created successfully: ${SONIC_EXPORT_IMAGE}${NC}"
