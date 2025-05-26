#!/usr/bin/env bash
#
# SPDX-License-Identifier: Apache-2.0

# Default tarball name
TARBALL="${1:-netbox-export.tar.gz}"
SCRIPT_DIR="$(dirname "$0")"
TEMP_DIR=$(mktemp -d)

# Cleanup function
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

# Check if tarball exists
if [ ! -f "/opt/$TARBALL" ]; then
    echo "Error: Tarball /opt/$TARBALL not found"
    exit 1
fi

# Extract tarball to temporary directory
echo "Extracting /opt/$TARBALL to temporary directory..."
tar -xzf "/opt/$TARBALL" -C "$TEMP_DIR"

if [ $? -ne 0 ]; then
    echo "Error: Failed to extract $TARBALL"
    exit 1
fi

# Sync files using rsync with delete option, excluding specific files
echo "Syncing files to netbox directory..."
rsync -av --delete \
    --exclude='import.sh' \
    --exclude='manage.sh' \
    --exclude='settings.toml' \
    "$TEMP_DIR/" "$SCRIPT_DIR/"

if [ $? -eq 0 ]; then
    echo "Successfully synced files from $TARBALL"
else
    echo "Error: Failed to sync files"
    exit 1
fi
