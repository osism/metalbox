#!/usr/bin/env bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Searching for netbox-export.tar.gz on ext4 filesystems...${NC}"

# Get the root filesystem device
ROOT_DEVICE=$(df / | tail -1 | awk '{print $1}')
# Get the base device name without partition number
ROOT_DEVICE_BASE=$(lsblk -no PKNAME "$ROOT_DEVICE" 2>/dev/null || echo "$ROOT_DEVICE" | sed 's/[0-9]*$//')

# Create temporary mount point
TEMP_MOUNT_DIR=$(mktemp -d /tmp/netbox-search.XXXXXX)
trap "rmdir '$TEMP_MOUNT_DIR' 2>/dev/null || true" EXIT

# Function to check if a device is on the root disk
is_root_disk() {
    local device="$1"
    local device_base=$(lsblk -no PKNAME "$device" 2>/dev/null || echo "$device" | sed 's/[0-9]*$//')

    # Check if it's the root device itself
    if [[ "$device" == "$ROOT_DEVICE" ]]; then
        return 0
    fi

    # Check if it's on the same physical disk as root
    if [[ -n "$device_base" && "$device_base" == "$ROOT_DEVICE_BASE" ]]; then
        return 0
    fi

    # Check if the device base matches the root device
    if [[ "$device" == "${ROOT_DEVICE_BASE}"* ]]; then
        return 0
    fi

    return 1
}

# Function to search for the file on a device
search_on_device() {
    local device="$1"
    local mount_point="$2"
    local was_mounted="$3"

    # Check if the file exists
    if [[ -f "${mount_point}/netbox-export.tar.gz" ]]; then
        echo -e "${GREEN}Found file: ${mount_point}/netbox-export.tar.gz${NC}"
        FOUND_FILE="${mount_point}/netbox-export.tar.gz"

        # If we mounted it temporarily, copy the file before unmounting
        if [[ "$was_mounted" == "no" ]]; then
            cp "${mount_point}/netbox-export.tar.gz" "/tmp/netbox-export.tar.gz"
            sudo umount "$mount_point" 2>/dev/null || true
            FOUND_FILE="/tmp/netbox-export.tar.gz"
        fi

        return 0
    fi

    # Unmount if we mounted it temporarily
    if [[ "$was_mounted" == "no" ]]; then
        sudo umount "$mount_point" 2>/dev/null || true
    fi

    return 1
}

FOUND_FILE=""

# First, check all currently mounted ext4 filesystems
echo -e "${YELLOW}Checking mounted ext4 filesystems...${NC}"
while read -r device mount_point; do
    # Skip if it's on the root disk
    if is_root_disk "$device"; then
        continue
    fi

    echo -e "Checking mounted filesystem: $device at $mount_point"
    if search_on_device "$device" "$mount_point" "yes"; then
        break
    fi
done < <(findmnt -t ext4 -n -o SOURCE,TARGET)

# If not found, check all ext4 partitions (mounted and unmounted)
if [[ -z "$FOUND_FILE" ]]; then
    echo -e "${YELLOW}Checking all ext4 partitions (including unmounted)...${NC}"

    # Get all block devices with ext4 filesystem
    while read -r device; do
        # Skip if it's on the root disk
        if is_root_disk "$device"; then
            continue
        fi

        # Check if already mounted
        mount_point=$(findmnt -n -o TARGET "$device" 2>/dev/null || true)

        if [[ -n "$mount_point" ]]; then
            # Already checked in the first pass
            continue
        else
            # Not mounted, try to mount temporarily
            echo -e "Checking unmounted partition: $device"

            # Check if it's really ext4
            fs_type=$(blkid -o value -s TYPE "$device" 2>/dev/null)
            if [[ "$fs_type" != "ext4" ]]; then
                continue
            fi

            # Try to mount it
            if sudo mount -t ext4 -o ro "$device" "$TEMP_MOUNT_DIR" 2>/dev/null; then
                if search_on_device "$device" "$TEMP_MOUNT_DIR" "no"; then
                    break
                fi
            else
                echo -e "  Could not mount $device"
            fi
        fi
    done < <(lsblk -rno NAME,TYPE | awk '$2 == "part" {print "/dev/"$1}')
fi

# If still not found, check all block devices without partitions
if [[ -z "$FOUND_FILE" ]]; then
    echo -e "${YELLOW}Checking block devices without partitions...${NC}"

    # Get all block devices that have no partitions
    while read -r device; do
        # Skip if it's on the root disk
        if is_root_disk "$device"; then
            continue
        fi

        # Check if already mounted
        mount_point=$(findmnt -n -o TARGET "$device" 2>/dev/null || true)

        if [[ -n "$mount_point" ]]; then
            # Already checked in the first pass
            continue
        else
            # Not mounted, try to mount temporarily
            echo -e "Checking block device without partitions: $device"

            # Check if it's ext4 using lsblk -f
            fs_type=$(lsblk -f -n -o FSTYPE "$device" 2>/dev/null | head -n1)
            if [[ "$fs_type" != "ext4" ]]; then
                continue
            fi

            # Try to mount it
            if sudo mount -t ext4 -o ro "$device" "$TEMP_MOUNT_DIR" 2>/dev/null; then
                if search_on_device "$device" "$TEMP_MOUNT_DIR" "no"; then
                    break
                fi
            else
                echo -e "  Could not mount $device"
            fi
        fi
    done < <(lsblk -rno NAME,TYPE | awk '$2 == "disk" {print "/dev/"$1}' | while read -r dev; do
        # Check if the disk has no partitions
        if [[ -z "$(lsblk -rno NAME "$dev" | tail -n +2)" ]]; then
            echo "$dev"
        fi
    done)
fi

# Clean up temp directory
rmdir "$TEMP_MOUNT_DIR" 2>/dev/null || true

if [[ -z "$FOUND_FILE" ]]; then
    echo -e "${RED}Error: netbox-export.tar.gz not found on any non-root ext4 filesystem${NC}"
    exit 1
fi

echo -e "${YELLOW}Importing file: $FOUND_FILE${NC}"

# Import the file using netbox-manager
if command -v netbox-manager &> /dev/null; then
    netbox-manager import-archive --input "$FOUND_FILE"
    echo -e "${GREEN}Import completed successfully${NC}"

    # Clean up temporary file if we created one
    if [[ "$FOUND_FILE" == "/tmp/netbox-export.tar.gz" ]]; then
        rm -f "$FOUND_FILE"
    fi
else
    echo -e "${RED}Error: netbox-manager command not found${NC}"
    exit 1
fi
