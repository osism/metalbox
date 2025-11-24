#!/usr/bin/env bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values or use environment variables
IRONIC_BASE_URL="${IRONIC_BASE_URL:-https://nbg1.your-objectstorage.com/osism/openstack-ironic-images}"
IRONIC_EXPORT_SIZE="${IRONIC_EXPORT_SIZE:-2G}"
IRONIC_EXPORT_IMAGE="${IRONIC_EXPORT_IMAGE:-ironic-export.img}"

# List of Ironic image files to download
IRONIC_FILES=(
    "osism-ipa.initramfs"
    "osism-ipa.kernel"
    "osism-node.qcow2"
    "osism-node.qcow2.CHECKSUM"
    "osism-esp.raw"
)

echo -e "${GREEN}Creating Ironic export image...${NC}"
echo -e "Base URL: ${IRONIC_BASE_URL}"
echo -e "Target image: ${IRONIC_EXPORT_IMAGE}"
echo -e "Image size: ${IRONIC_EXPORT_SIZE}"
echo -e "Files to download: ${#IRONIC_FILES[@]}"

# Create temporary working directory
TEMP_WORK_DIR=$(mktemp -d /tmp/ironic-export.XXXXXX)
trap "rm -rf '$TEMP_WORK_DIR' 2>/dev/null || true" EXIT

# Download all Ironic image files
echo -e "${YELLOW}Downloading Ironic image files...${NC}"
for FILE in "${IRONIC_FILES[@]}"; do
    echo -e "  Downloading ${FILE}..."
    FILE_URL="${IRONIC_BASE_URL}/${FILE}"
    FILE_PATH="${TEMP_WORK_DIR}/${FILE}"

    if ! wget -q -O "$FILE_PATH" "$FILE_URL"; then
        echo -e "${RED}Error: Failed to download ${FILE} from ${FILE_URL}${NC}"
        exit 1
    fi

    # Verify file was downloaded
    if [[ ! -f "$FILE_PATH" ]]; then
        echo -e "${RED}Error: Downloaded file not found at ${FILE_PATH}${NC}"
        exit 1
    fi

    echo -e "${GREEN}  ${FILE} downloaded successfully${NC}"
done

echo -e "${GREEN}All files downloaded successfully${NC}"

echo -e "${YELLOW}Creating disk image of size ${IRONIC_EXPORT_SIZE}...${NC}"
if ! dd if=/dev/zero of="$IRONIC_EXPORT_IMAGE" bs=1 count=0 seek="$IRONIC_EXPORT_SIZE" 2>/dev/null; then
    echo -e "${RED}Error: Failed to create disk image${NC}"
    exit 1
fi

echo -e "${YELLOW}Creating ext4 filesystem on image...${NC}"
if ! mkfs.ext4 -F "$IRONIC_EXPORT_IMAGE" >/dev/null 2>&1; then
    echo -e "${RED}Error: Failed to create ext4 filesystem${NC}"
    rm -f "$IRONIC_EXPORT_IMAGE"
    exit 1
fi

# Create temporary mount point
TEMP_MOUNT_DIR=$(mktemp -d /tmp/ironic-export-mount.XXXXXX)
trap "sudo umount '$TEMP_MOUNT_DIR' 2>/dev/null || true; rmdir '$TEMP_MOUNT_DIR' 2>/dev/null || true; rm -rf '$TEMP_WORK_DIR' 2>/dev/null || true" EXIT

echo -e "${YELLOW}Mounting image...${NC}"
if ! sudo mount -o loop "$IRONIC_EXPORT_IMAGE" "$TEMP_MOUNT_DIR"; then
    echo -e "${RED}Error: Failed to mount image${NC}"
    rm -f "$IRONIC_EXPORT_IMAGE"
    exit 1
fi

echo -e "${YELLOW}Copying files to image...${NC}"

# Copy all downloaded files
for FILE in "${IRONIC_FILES[@]}"; do
    echo -e "  Copying ${FILE}..."
    FILE_PATH="${TEMP_WORK_DIR}/${FILE}"

    if ! sudo cp "$FILE_PATH" "$TEMP_MOUNT_DIR/$FILE"; then
        echo -e "${RED}Error: Failed to copy ${FILE} to image${NC}"
        sudo umount "$TEMP_MOUNT_DIR"
        rm -f "$IRONIC_EXPORT_IMAGE"
        exit 1
    fi
done

echo -e "${YELLOW}Unmounting image...${NC}"
sudo umount "$TEMP_MOUNT_DIR"

echo -e "${GREEN}Ironic export image created successfully: ${IRONIC_EXPORT_IMAGE}${NC}"
echo -e "${GREEN}Contains ${#IRONIC_FILES[@]} files:${NC}"
for FILE in "${IRONIC_FILES[@]}"; do
    echo -e "${GREEN}  - ${FILE}${NC}"
done
