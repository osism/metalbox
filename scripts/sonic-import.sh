#!/usr/bin/env bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default pattern or use environment variable
SONIC_PATTERN="${SONIC_PATTERN:-sonic-broadcom-enterprise-base*.bin}"
# Default destination directory or use environment variable
SONIC_DEST_DIR="${SONIC_DEST_DIR:-/opt/httpd/data/sonic}"

echo -e "${GREEN}Searching for ${SONIC_PATTERN} on ext4 filesystems...${NC}"

# Get the root filesystem device
ROOT_DEVICE=$(df / | tail -1 | awk '{print $1}')
# Get the base device name without partition number
ROOT_DEVICE_BASE=$(lsblk -no PKNAME "$ROOT_DEVICE" 2>/dev/null || echo "$ROOT_DEVICE" | sed 's/[0-9]*$//')

# Create temporary mount point
TEMP_MOUNT_DIR=$(mktemp -d /tmp/sonic-search.XXXXXX)
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
    local found_any=1

    # Search for files matching the pattern
    for file in ${mount_point}/${SONIC_PATTERN}; do
        if [[ -f "$file" ]]; then
            local basename=$(basename "$file")
            echo -e "${GREEN}Found file: $file${NC}"

            # If we mounted it temporarily, copy the file before unmounting
            if [[ "$was_mounted" == "no" ]]; then
                cp "$file" "/tmp/$basename"
                FOUND_FILES["/tmp/$basename"]="$basename"
            else
                FOUND_FILES["$file"]="$basename"
            fi

            found_any=0
        fi
    done

    # Unmount if we mounted it temporarily
    if [[ "$was_mounted" == "no" ]]; then
        sudo umount "$mount_point" 2>/dev/null || true
    fi

    return $found_any
}

declare -A FOUND_FILES

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
if [[ ${#FOUND_FILES[@]} -eq 0 ]]; then
    echo -e "${YELLOW}Checking all ext4 partitions (including unmounted)...${NC}"

    # Get all block devices that are partitions
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
if [[ ${#FOUND_FILES[@]} -eq 0 ]]; then
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

# If still not found, check loopback devices
if [[ ${#FOUND_FILES[@]} -eq 0 ]]; then
    echo -e "${YELLOW}Checking loopback devices...${NC}"

    # Get all loopback devices
    while read -r loop_device; do
        # Extract just the device path from losetup output
        device=$(echo "$loop_device" | awk -F: '{print $1}')

        # Check if already mounted
        mount_point=$(findmnt -n -o TARGET "$device" 2>/dev/null || true)

        if [[ -n "$mount_point" ]]; then
            echo -e "Checking mounted loopback device: $device at $mount_point"
            search_on_device "$device" "$mount_point" "yes" || true
        else
            # Not mounted, try to mount temporarily
            echo -e "Checking unmounted loopback device: $device"

            # Check if it's ext4
            fs_type=$(sudo blkid -o value -s TYPE "$device" 2>/dev/null)
            if [[ "$fs_type" != "ext4" ]]; then
                continue
            fi

            # Try to mount it
            if sudo mount -t ext4 -o ro "$device" "$TEMP_MOUNT_DIR" 2>/dev/null; then
                search_on_device "$device" "$TEMP_MOUNT_DIR" "no" || true
            else
                echo -e "  Could not mount $device"
            fi
        fi
    done < <(sudo losetup -a 2>/dev/null || true)
fi

# Clean up temp directory
rmdir "$TEMP_MOUNT_DIR" 2>/dev/null || true

if [[ ${#FOUND_FILES[@]} -eq 0 ]]; then
    echo -e "${RED}Error: No files matching ${SONIC_PATTERN} found on any non-root ext4 filesystem${NC}"
    exit 1
fi

echo -e "${YELLOW}Found ${#FOUND_FILES[@]} file(s) to copy${NC}"

# Create destination directory if it doesn't exist
sudo mkdir -p "$SONIC_DEST_DIR"
sudo chown -R dragon: "$SONIC_DEST_DIR"

# Copy all found files to destination
for source_file in "${!FOUND_FILES[@]}"; do
    basename="${FOUND_FILES[$source_file]}"
    destination="${SONIC_DEST_DIR}/${basename}"

    echo -e "${YELLOW}Copying $basename to $destination...${NC}"

    if sudo cp "$source_file" "$destination"; then
        sudo chown dragon: "$destination"
        echo -e "${GREEN}File copied successfully to $destination${NC}"

        # Clean up temporary file if we created one
        if [[ "$source_file" == "/tmp/"* ]]; then
            rm -f "$source_file"
        fi
    else
        echo -e "${RED}Error: Failed to copy $basename to $destination${NC}"
        exit 1
    fi
done

echo -e "${GREEN}Import completed successfully${NC}"
