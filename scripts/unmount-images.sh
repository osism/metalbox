#!/bin/bash

# Show current loop devices
echo "Current loop devices:"
sudo losetup -a
echo ""

# Get all loop devices that are in use
LOOP_DEVICES=$(sudo losetup -a | grep -E "^/dev/loop[0-9]+" | cut -d: -f1)

if [ -z "$LOOP_DEVICES" ]; then
    echo "No loop devices found to unmount"
    exit 0
fi

# Counter for unmounted devices
UNMOUNTED=0

# Process each loop device
for LOOP_DEVICE in $LOOP_DEVICES; do
    # Get the backing file for this loop device
    BACKING_FILE=$(sudo losetup -l | grep "^$LOOP_DEVICE" | awk '{print $6}')
    
    # Check if it's an .img file (including *-export.img and *-export-*.img)
    if [[ "$BACKING_FILE" == *.img ]]; then
        echo "Unmounting $LOOP_DEVICE (backing file: $BACKING_FILE)"
        if sudo losetup -d "$LOOP_DEVICE"; then
            echo "  Success: $LOOP_DEVICE unmounted"
            ((UNMOUNTED++))
        else
            echo "  Error: Failed to unmount $LOOP_DEVICE"
        fi
    else
        echo "Skipping $LOOP_DEVICE (not an .img file: $BACKING_FILE)"
    fi
done

echo ""
echo "Unmounted $UNMOUNTED loop device(s)"

# Show remaining loop devices
if [ $(sudo losetup -a | wc -l) -gt 0 ]; then
    echo ""
    echo "Remaining loop devices:"
    sudo losetup -a
fi
