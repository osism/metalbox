#!/bin/bash

set -e

TARBALL_FILE="${TARBALL_FILE:-configuration-export.tar.gz}"
CONFIGURATION_DIR="/opt/configuration"
TEMP_DIR=$(mktemp -d)

cleanup() {
    rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

cp "$TARBALL_FILE" "$TEMP_DIR/configuration-export.tar.gz"

echo "Extracting tarball..."
tar -xzf "$TEMP_DIR/configuration-export.tar.gz" -C "$TEMP_DIR" --strip-components=1

if [ ! -d "$CONFIGURATION_DIR" ]; then
    echo "Error: $CONFIGURATION_DIR does not exist"
    exit 1
fi

if [ ! -d "$CONFIGURATION_DIR/.git" ]; then
    echo "Error: $CONFIGURATION_DIR is not a git repository"
    exit 1
fi

echo "Syncing $CONFIGURATION_DIR with extracted repository..."
cd "$CONFIGURATION_DIR"

echo "Adding temporary repository as remote..."
git remote remove temp-metalbox 2>/dev/null || true
git remote add temp-metalbox "$TEMP_DIR"

echo "Fetching from temporary repository..."
git fetch temp-metalbox

echo "Merging changes from temporary repository..."
git merge temp-metalbox/main --allow-unrelated-histories

echo "Removing temporary remote..."
git remote remove temp-metalbox

echo "Configuration import completed successfully"
