#!/usr/bin/env bash
#
# Import a registry delta tar.gz to the running registry on localhost:5001
#
# Usage: ./single-image-import.sh <tarball>
#
# Example:
#   ./single-image-import.sh registry-delta-20250124-1430.tar.gz
#
# This script:
#   1. Extracts the tarball containing image.tar and manifest.txt
#   2. Uses skopeo to copy the image to localhost:5001
#
# Prerequisites:
#   - Registry must already be running on localhost:5001

set -euo pipefail

TARGET_REGISTRY="${TARGET_REGISTRY:-localhost:5001}"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <tarball>"
    echo ""
    echo "Example:"
    echo "  $0 registry-delta-20250124-1430.tar.gz"
    echo ""
    echo "Environment variables:"
    echo "  TARGET_REGISTRY - Target registry (default: localhost:5001)"
    exit 1
fi

TARBALL="$1"

if [[ ! -f "${TARBALL}" ]]; then
    echo "ERROR: Tarball not found: ${TARBALL}"
    exit 1
fi

TEMP_DIR=$(mktemp -d)

# Cleanup function
cleanup() {
    echo "==> Cleaning up..."
    rm -rf "${TEMP_DIR}"
}

# Set trap for cleanup on exit
trap cleanup EXIT

echo "==> Importing from: ${TARBALL}"
echo "==> Target registry: ${TARGET_REGISTRY}"

# Extract tarball
echo "==> Extracting tarball..."
tar -xzf "${TARBALL}" -C "${TEMP_DIR}"

# Read image name from manifest
if [[ ! -f "${TEMP_DIR}/manifest.txt" ]]; then
    echo "ERROR: manifest.txt not found in tarball"
    exit 1
fi

DEST_IMAGE=$(cat "${TEMP_DIR}/manifest.txt")
echo "==> Image name: ${DEST_IMAGE}"

# Copy image to target registry using skopeo
echo "==> Copying image to ${TARGET_REGISTRY}/${DEST_IMAGE}..."
skopeo copy --retry-times 2 \
    --dest-tls-verify=false \
    "docker-archive:${TEMP_DIR}/image.tar" \
    "docker://${TARGET_REGISTRY}/${DEST_IMAGE}"

echo "==> Import complete!"
