#!/bin/bash

set -e

TARBALL_FILE="${TARBALL_FILE:-configuration-export.tar.gz}"
CURRENT_DIR=$(pwd)

echo "Creating tarball from current directory including .git..."
echo "Exporting to: $TARBALL_FILE"

tar -czf "$TARBALL_FILE" -C "$CURRENT_DIR" --exclude="$TARBALL_FILE" .

echo "Configuration export completed successfully"
echo "Archive saved as: $TARBALL_FILE"
