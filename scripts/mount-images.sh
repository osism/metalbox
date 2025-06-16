#!/bin/bash

# Default directory is current directory
DIR="${1:-.}"

# Check if directory exists
if [ ! -d "$DIR" ]; then
    echo "Error: Directory '$DIR' does not exist"
    exit 1
fi

echo "Looking for *.img files in: $DIR"

# Find all *.img files in the directory
IMG_FILES=("$DIR"/*.img)

# Check if any .img files were found
if [ ! -e "${IMG_FILES[0]}" ]; then
    echo "No *.img files found in $DIR"
    exit 0
fi

# Counter for loop devices
LOOP_NUM=0

# Process each .img file
for IMG_FILE in "${IMG_FILES[@]}"; do
    if [ -f "$IMG_FILE" ]; then
        LOOP_DEVICE="/dev/loop${LOOP_NUM}"
        
        # Check if loop device already exists and is in use
        if sudo losetup "$LOOP_DEVICE" 2>/dev/null; then
            echo "Warning: $LOOP_DEVICE is already in use, skipping..."
            ((LOOP_NUM++))
            continue
        fi
        
        # Create loop device
        echo "Mounting '$IMG_FILE' as $LOOP_DEVICE"
        if sudo losetup "$LOOP_DEVICE" "$IMG_FILE"; then
            echo "  Success: $IMG_FILE -> $LOOP_DEVICE"
        else
            echo "  Error: Failed to mount $IMG_FILE"
        fi
        
        ((LOOP_NUM++))
    fi
done

echo ""
echo "Current loop devices:"
sudo losetup -a
