#!/bin/bash

# Help function
show_help() {
    cat << EOF
Usage: $0 [IMAGE_FILTER]

Download and manage Ironic images with optional filtering.

Arguments:
  IMAGE_FILTER    Filter images by type: node, ipa, esp (optional)
                  Can also be set via IMAGE_FILTER environment variable
                  Default: all images are processed

Environment Variables:
  BASE_URL        Base URL for image downloads
  TARGET_PATH     Target directory for images (default: /opt/httpd/data/root)
  SOURCE_PATH     Source directory when SKIP_DOWNLOAD=true (default: /home/dragon)
  SKIP_DOWNLOAD   Skip download and copy from SOURCE_PATH (default: false)
  IMAGE_FILTER    Filter images by type: node, ipa, esp (optional)

Every image is checked against its checksum file: osism-ipa.CHECKSUM
(covering both IPA files), osism-node.qcow2.CHECKSUM and
osism-esp.raw.CHECKSUM. With SKIP_DOWNLOAD=true the files in SOURCE_PATH are
checked before any of them is copied. osism-node.qcow2.CHECKSUM is required
there, because Ironic reads it when it deploys a node; without the other two
checksum files the IPA and ESP images are copied unverified, with a warning.

Examples:
  $0              # Process all images
  $0 node         # Process only osism-node images
  $0 ipa          # Process only osism-ipa images
  $0 esp          # Process only osism-esp images
  IMAGE_FILTER=node $0  # Process only osism-node images via env var

EOF
}

# Parse command line arguments
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Configuration variables
BASE_URL="${BASE_URL:-https://nbg1.your-objectstorage.com/osism/openstack-ironic-images}"
TARGET_PATH="${TARGET_PATH:-/opt/httpd/data/root}"
SOURCE_PATH="${SOURCE_PATH:-/home/dragon}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-false}"

# Image filtering - command line argument takes precedence over environment variable
IMAGE_FILTER="${1:-${IMAGE_FILTER:-}}"

# The Ironic images, in groups that are updated together. Each group has one
# checksum file that covers all of its images.
ALL_GROUPS=(ipa node esp)
declare -A GROUP_IMAGES=(
    [ipa]="osism-ipa.initramfs osism-ipa.kernel"
    [node]="osism-node.qcow2"
    [esp]="osism-esp.raw"
)
declare -A GROUP_CHECKSUM=(
    [ipa]="osism-ipa.CHECKSUM"
    [node]="osism-node.qcow2.CHECKSUM"
    [esp]="osism-esp.raw.CHECKSUM"
)

case "$IMAGE_FILTER" in
    ""|"node"|"ipa"|"esp") ;;
    *)
        echo "ERROR: Invalid image filter '$IMAGE_FILTER'. Valid options: node, ipa, esp"
        echo "Use '$0 --help' for more information."
        exit 1
        ;;
esac

if [[ -n "$IMAGE_FILTER" ]]; then
    SELECTED_GROUPS=("$IMAGE_FILTER")
else
    SELECTED_GROUPS=("${ALL_GROUPS[@]}")
fi

verify() {
    local dir="$1"
    local checksum="$2"
    (cd "$dir" && sha256sum -c --strict "$checksum")
}

download() {
    local file="$1"

    echo "Downloading $BASE_URL/$file ..."
    # -f: an HTTP error must fail the run, not be saved as the image.
    if ! sudo curl -fL --retry 5 --retry-all-errors --retry-delay 10 \
            -o "$TARGET_PATH/$file" "$BASE_URL/$file"; then
        echo "ERROR: Failed to download $file." >&2
        echo "       $TARGET_PATH/$file may be incomplete; run the update again." >&2
        exit 1
    fi
}

update_group_online() {
    local group="$1"
    local checksum="${GROUP_CHECKSUM[$group]}"
    local images image
    read -ra images <<< "${GROUP_IMAGES[$group]}"

    for image in "${images[@]}"; do
        download "$image"
    done
    # The checksum comes last: until it is replaced, the previous checksum
    # stays next to a new or partial image, and a node deployed in the
    # meantime fails Ironic's checksum check instead of getting that image.
    download "$checksum"

    echo "Verifying ${images[*]} ..."
    if ! verify "$TARGET_PATH" "$checksum"; then
        echo "ERROR: ${images[*]} in $TARGET_PATH do not match $checksum." >&2
        echo "       The downloaded files are damaged; run the update again." >&2
        exit 1
    fi
}

update_group_offline() {
    local group="$1"
    local checksum="${GROUP_CHECKSUM[$group]}"
    local images image file
    local missing=()
    read -ra images <<< "${GROUP_IMAGES[$group]}"

    for image in "${images[@]}"; do
        if [ ! -f "$SOURCE_PATH/$image" ]; then
            missing+=("$image")
        fi
    done
    if [ "${#missing[@]}" -eq "${#images[@]}" ]; then
        echo "WARNING: Expected image ${images[*]} not found in $SOURCE_PATH!"
        return 0
    fi
    if [ "${#missing[@]}" -gt 0 ]; then
        # The IPA kernel and initramfs only work as a pair from one build.
        echo "ERROR: ${missing[*]} not found in $SOURCE_PATH." >&2
        echo "       ${images[*]} are only updated together." >&2
        exit 1
    fi

    local files=("${images[@]}")
    if [ -f "$SOURCE_PATH/$checksum" ]; then
        echo "Verifying ${images[*]} in $SOURCE_PATH ..."
        if ! verify "$SOURCE_PATH" "$checksum"; then
            echo "ERROR: ${images[*]} in $SOURCE_PATH do not match $checksum." >&2
            echo "       Nothing has been copied." >&2
            exit 1
        fi
        files+=("$checksum")
    elif [ "$group" = "node" ]; then
        # Ironic reads osism-node.qcow2.CHECKSUM at deploy time: a new image
        # next to the old checksum would fail every deploy.
        echo "ERROR: $checksum not found in $SOURCE_PATH." >&2
        echo "       It has to be updated together with ${images[*]}." >&2
        exit 1
    else
        echo "WARNING: $checksum not found in $SOURCE_PATH;" \
             "copying ${images[*]} unverified."
    fi

    for file in "${files[@]}"; do
        echo "Copying $file to $TARGET_PATH ..."
        sudo cp "$SOURCE_PATH/$file" "$TARGET_PATH/$file"
    done
}

set -e

echo "Starting Ironic images update..."
if [[ -n "$IMAGE_FILTER" ]]; then
    echo "Image filter: $IMAGE_FILTER"
else
    echo "Processing all images (no filter applied)"
fi

# Create target directory if it doesn't exist
if [ ! -d "$TARGET_PATH" ]; then
    echo "Creating target directory: $TARGET_PATH"
    sudo mkdir -p "$TARGET_PATH"
fi

for GROUP in "${SELECTED_GROUPS[@]}"; do
    echo "Processing images: ${GROUP_IMAGES[$GROUP]}"
    if [ "$SKIP_DOWNLOAD" = "true" ]; then
        update_group_offline "$GROUP"
    else
        update_group_online "$GROUP"
    fi
    echo "---"
done

echo "Ironic images update completed successfully!"
echo "All images are now available in: $TARGET_PATH"

# List the files in the target directory for verification
echo "Files in $TARGET_PATH:"
ls -la "$TARGET_PATH"
