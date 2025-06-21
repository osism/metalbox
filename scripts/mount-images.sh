#!/bin/bash

# Default directory is current directory
DIR="${1:-.}"

# Check if directory exists
if [ ! -d "$DIR" ]; then
    echo "Error: Directory '$DIR' does not exist"
    exit 1
fi

echo "Looking for *.img, *-export.img, and *-export-*.img files in: $DIR"

# Function to extract prefix from filename
get_prefix() {
    local filename="$1"
    # Extract basename without path
    local basename=$(basename "$filename")

    # For *-export-*.img files, extract prefix before "-export-"
    if [[ "$basename" =~ ^(.+)-export-.*\.img$ ]]; then
        echo "${BASH_REMATCH[1]}"
    # For *-export.img files, extract prefix before "-export"
    elif [[ "$basename" =~ ^(.+)-export\.img$ ]]; then
        echo "${BASH_REMATCH[1]}"
    # For regular *.img files, extract prefix before ".img"
    elif [[ "$basename" =~ ^(.+)\.img$ ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "$basename"
    fi
}

# Find all image files and group by prefix
declare -A GROUPED_FILES
ALL_IMAGE_FILES=()

# Find all *.img files
if compgen -G "$DIR/*.img" > /dev/null; then
    mapfile -t IMG_FILES < <(find "$DIR" -name "*.img")
    ALL_IMAGE_FILES+=("${IMG_FILES[@]}")
fi

# Find all *-export.img files
if compgen -G "$DIR/*-export.img" > /dev/null; then
    mapfile -t EXPORT_IMG_FILES < <(find "$DIR" -name "*-export.img")
    ALL_IMAGE_FILES+=("${EXPORT_IMG_FILES[@]}")
fi

# Find all *-export-*.img files
if compgen -G "$DIR/*-export-*.img" > /dev/null; then
    mapfile -t EXPORT_VERSIONED_FILES < <(find "$DIR" -name "*-export-*.img")
    ALL_IMAGE_FILES+=("${EXPORT_VERSIONED_FILES[@]}")
fi

# Group files by prefix and keep only the newest version for each group
for file in "${ALL_IMAGE_FILES[@]}"; do
    if [ -f "$file" ]; then
        prefix=$(get_prefix "$file")
        basename_file=$(basename "$file")

        # If this is the first file for this prefix, or if it's newer than the current one
        if [ -z "${GROUPED_FILES[$prefix]}" ]; then
            GROUPED_FILES[$prefix]="$file"
        else
            current_basename=$(basename "${GROUPED_FILES[$prefix]}")
            # Use version sort to determine which is newer
            if [[ $(printf '%s\n%s\n' "$current_basename" "$basename_file" | sort -V -r | head -1) == "$basename_file" ]]; then
                GROUPED_FILES[$prefix]="$file"
            fi
        fi
    fi
done

# Create final file list from grouped files
ALL_FILES=()
for prefix in "${!GROUPED_FILES[@]}"; do
    ALL_FILES+=("${GROUPED_FILES[$prefix]}")
done

# Check if any files were found
if [ ${#ALL_FILES[@]} -eq 0 ]; then
    echo "No *.img, *-export.img, or *-export-*.img files found in $DIR"
    exit 0
fi

echo "Selected files (newest version per prefix):"
for file in "${ALL_FILES[@]}"; do
    echo "  $(basename "$file")"
done
echo ""

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
