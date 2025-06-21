#!/bin/bash

# Default directory is current directory
DIR="${1:-.}"

# Check if directory exists
if [ ! -d "$DIR" ]; then
    echo "Error: Directory '$DIR' does not exist"
    exit 1
fi

echo "Looking for *.img, *-export.img, and *-export-*.img files in: $DIR"

# Find all *.img files in the directory
IMG_FILES=("$DIR"/*.img)

# Find all *-export.img files
EXPORT_IMG_FILES=("$DIR"/*-export.img)

# Find all *-export-*.img files and sort them by version/date
EXPORT_VERSIONED_FILES=()
if compgen -G "$DIR/*-export-*.img" > /dev/null; then
    # Get all export files and sort by version/date (newest first)
    mapfile -t EXPORT_VERSIONED_FILES < <(find "$DIR" -name "*-export-*.img" -printf '%f\n' | sort -V -r | head -1 | xargs -I {} find "$DIR" -name "{}")
fi

# Combine all file types
ALL_FILES=()
if [ -e "${IMG_FILES[0]}" ]; then
    ALL_FILES+=("${IMG_FILES[@]}")
fi
if [ -e "${EXPORT_IMG_FILES[0]}" ]; then
    ALL_FILES+=("${EXPORT_IMG_FILES[@]}")
fi
if [ ${#EXPORT_VERSIONED_FILES[@]} -gt 0 ]; then
    ALL_FILES+=("${EXPORT_VERSIONED_FILES[@]}")
fi

# Check if any files were found
if [ ${#ALL_FILES[@]} -eq 0 ]; then
    echo "No *.img, *-export.img, or *-export-*.img files found in $DIR"
    exit 0
fi

# Counter for loop devices
LOOP_NUM=0

# Process each image file
for IMG_FILE in "${ALL_FILES[@]}"; do
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
