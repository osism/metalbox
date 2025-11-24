#!/usr/bin/env bash
#
# Export a single Docker image to a tar.gz archive for delta updates
#
# Usage: ./single-image-export.sh <image>
#
# Examples:
#   ./single-image-export.sh osism/inventory-reconciler:latest
#   ./single-image-export.sh osism/ara-server:1.7.3
#   ./single-image-export.sh kolla/nova-api:2024.2
#   ./single-image-export.sh dockerhub/library/redis:7.4.7-alpine
#
# The image parameter should include the namespace prefix:
#   - dockerhub/  for DockerHub images (e.g., dockerhub/library/redis:7.4.7-alpine)
#   - osism/      for OSISM manager images (e.g., osism/ara-server:1.7.3)
#   - kolla/      for Kolla images (e.g., kolla/nova-api:2024.2)

set -euo pipefail

DOCKER_REGISTRY="${DOCKER_REGISTRY:-registry.osism.tech}"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <image>"
    echo ""
    echo "Examples:"
    echo "  $0 osism/inventory-reconciler:latest"
    echo "  $0 osism/ara-server:1.7.3"
    echo "  $0 kolla/nova-api:2024.2"
    echo "  $0 dockerhub/library/redis:7.4.7-alpine"
    exit 1
fi

IMAGE="$1"

# Strip registry prefix if provided (e.g., registry.osism.tech/osism/foo -> osism/foo)
if [[ "${IMAGE}" == registry.osism.tech/* ]]; then
    IMAGE="${IMAGE#registry.osism.tech/}"
elif [[ "${IMAGE}" == registry.osism.cloud/* ]]; then
    IMAGE="${IMAGE#registry.osism.cloud/}"
fi

# Generate output filename with timestamp
TIMESTAMP=$(date +%Y%m%d-%H%M)
OUTPUT_FILE="registry-delta-${TIMESTAMP}.tar.gz"
TEMP_DIR=$(mktemp -d)

# Cleanup function
cleanup() {
    echo "==> Cleaning up..."
    rm -rf "${TEMP_DIR}"
}

# Set trap for cleanup on exit
trap cleanup EXIT

# Parse the image path to determine the destination path
# Input format: namespace/image:tag (e.g., dockerhub/library/redis:7.4.7-alpine)
# For dockerhub: strip the 'dockerhub/' prefix
# For osism/kolla: keep as-is
if [[ "${IMAGE}" == dockerhub/* ]]; then
    DEST_IMAGE="${IMAGE#dockerhub/}"
else
    DEST_IMAGE="${IMAGE}"
fi

echo "==> Exporting image: ${IMAGE}"
echo "==> Source registry: ${DOCKER_REGISTRY}"
echo "==> Destination name: ${DEST_IMAGE}"
echo "==> Output file: ${OUTPUT_FILE}"

# Export image using skopeo to docker-archive format
ARCHIVE_FILE="${TEMP_DIR}/image.tar"
echo "==> Copying image to docker-archive format..."
skopeo copy --retry-times 2 \
    "docker://${DOCKER_REGISTRY}/${IMAGE}" \
    "docker-archive:${ARCHIVE_FILE}:${DEST_IMAGE}"

# Create manifest file with image name for import
echo "${DEST_IMAGE}" > "${TEMP_DIR}/manifest.txt"

# Create final tar.gz with image archive and manifest
echo "==> Creating ${OUTPUT_FILE}..."
tar -czf "${OUTPUT_FILE}" -C "${TEMP_DIR}" image.tar manifest.txt

# Get and display file size
if [[ -f "${OUTPUT_FILE}" ]]; then
    SIZE=$(du -h "${OUTPUT_FILE}" | cut -f1)
    echo "==> Export complete: ${OUTPUT_FILE} (${SIZE})"

    # Generate checksum
    sha256sum "${OUTPUT_FILE}" > "${OUTPUT_FILE}.CHECKSUM"
    echo "==> Checksum file: ${OUTPUT_FILE}.CHECKSUM"
else
    echo "ERROR: Export file not created!"
    exit 1
fi

echo "==> Done!"
