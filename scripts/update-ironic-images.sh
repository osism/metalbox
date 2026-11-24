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
  STAGING         Stage the images before replacing the served ones:
                  auto, always or never (default: auto, see below)

The images are first fetched into a staging directory in TARGET_PATH and
moved into place only once all of them are complete and verified, so a
failed run leaves the images Ironic serves untouched. Staging needs free
space for one more copy of the images (about 2.6 GB for all of them) plus
1 GiB to spare. STAGING=auto stages when that space is available and
otherwise falls back to writing the images in place, where a failed run
leaves damaged images behind. STAGING=never always writes in place.
STAGING=always exits before writing anything if the space is not there.

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
STAGING="${STAGING:-auto}"

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

case "$STAGING" in
    "auto"|"always"|"never") ;;
    *)
        echo "ERROR: Invalid STAGING '$STAGING'. Valid options: auto, always, never"
        exit 1
        ;;
esac

if [[ -n "$IMAGE_FILTER" ]]; then
    SELECTED_GROUPS=("$IMAGE_FILTER")
else
    SELECTED_GROUPS=("${ALL_GROUPS[@]}")
fi

# Staging keeps this much free space on top of the staged images, so that it
# does not fill the filesystem to the last byte.
STAGING_RESERVE=$((1024 * 1024 * 1024))
STAGING_PREFIX=".update-ironic-images."

# Where the files are written: TARGET_PATH itself, or the staging directory.
DEST="$TARGET_PATH"
STAGED=false
# Every file written to DEST, in the order it is to be moved into place
WRITTEN_FILES=()

# What a failure leaves behind, for the error messages
failure_note() {
    if [ "$STAGED" = "true" ]; then
        echo "       No image has been replaced."
    else
        echo "       ${1}; run the update again."
    fi
}

# Print the size in bytes of the files the run will write. Fails if a size
# cannot be determined.
required_bytes() {
    local total=0 group file size headers
    local files

    for group in "${SELECTED_GROUPS[@]}"; do
        read -ra files <<< "${GROUP_IMAGES[$group]} ${GROUP_CHECKSUM[$group]}"
        for file in "${files[@]}"; do
            if [ "$SKIP_DOWNLOAD" = "true" ]; then
                size=0
                if [ -f "$SOURCE_PATH/$file" ]; then
                    size=$(stat -c %s "$SOURCE_PATH/$file")
                fi
            else
                # The last Content-Length is the one after any redirects.
                headers=$(curl -fsSIL "$BASE_URL/$file" 2>/dev/null) || return 1
                size=$(awk 'tolower($1) == "content-length:" { n = $2 + 0 } END { print n + 0 }' <<< "$headers")
                [ "$size" -gt 0 ] || return 1
            fi
            total=$((total + size))
        done
    done
    echo "$total"
}

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
            -o "$DEST/$file" "$BASE_URL/$file"; then
        echo "ERROR: Failed to download $file." >&2
        failure_note "$TARGET_PATH/$file may be incomplete" >&2
        exit 1
    fi
    WRITTEN_FILES+=("$file")
}

update_group_online() {
    local group="$1"
    local checksum="${GROUP_CHECKSUM[$group]}"
    local images image
    read -ra images <<< "${GROUP_IMAGES[$group]}"

    for image in "${images[@]}"; do
        download "$image"
    done
    # The checksum comes last. When writing in place, the previous checksum
    # stays next to a new or partial image until then, and a node deployed
    # in the meantime fails Ironic's checksum check instead of getting that
    # image. When staging, it is also moved into place after its images.
    download "$checksum"

    echo "Verifying ${images[*]} ..."
    if ! verify "$DEST" "$checksum"; then
        echo "ERROR: ${images[*]} do not match $checksum." >&2
        failure_note "The downloaded files in $TARGET_PATH are damaged" >&2
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
        echo "Copying $file to $DEST ..."
        sudo cp "$SOURCE_PATH/$file" "$DEST/$file"
        WRITTEN_FILES+=("$file")
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

# A staging directory is only left behind when a run was killed. It sits in
# the directory httpd serves and takes the space the next run needs.
for LEFTOVER in "$TARGET_PATH/$STAGING_PREFIX"*; do
    if [ -d "$LEFTOVER" ]; then
        echo "Removing $LEFTOVER left behind by an earlier run"
        sudo rm -rf "$LEFTOVER"
    fi
done

# Ironic fetches these files over HTTP whenever a node is deployed. Written
# in place, a deploy that starts mid-update can read a partial image, and a
# failed run leaves a damaged one. Staging avoids both: the files are written
# to a directory inside TARGET_PATH and moved into place at the end, which
# is a rename on the same filesystem and never exposes a partial file.
if [ "$STAGING" != "never" ]; then
    AVAILABLE=$(df --output=avail -B1 "$TARGET_PATH" | tail -n 1)
    if REQUIRED=$(required_bytes); then
        REQUIRED=$((REQUIRED + STAGING_RESERVE))
        SPACE="$(numfmt --to=iec "$REQUIRED") needed, $(numfmt --to=iec "$AVAILABLE") available"
    else
        REQUIRED=""
        SPACE="the size of the images could not be determined"
    fi

    if [ -n "$REQUIRED" ] && [ "$AVAILABLE" -ge "$REQUIRED" ]; then
        STAGED=true
    elif [ "$STAGING" = "always" ]; then
        echo "ERROR: Cannot stage the images in $TARGET_PATH: $SPACE." >&2
        echo "       STAGING=never writes them in place instead." >&2
        exit 1
    else
        echo "WARNING: Not staging the images: $SPACE."
        echo "         They are written in place: a failed run leaves damaged"
        echo "         images behind, and a node deployed during the update"
        echo "         can fail its deployment."
    fi
fi

if [ "$STAGED" = "true" ]; then
    DEST="$(sudo mktemp -d "$TARGET_PATH/${STAGING_PREFIX}XXXXXX")"
    trap 'sudo rm -rf "$DEST"' EXIT
    echo "Staging the images in $DEST"
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

if [ "$STAGED" = "true" ]; then
    for FILE in "${WRITTEN_FILES[@]}"; do
        sudo mv -f "$DEST/$FILE" "$TARGET_PATH/$FILE"
        echo "Updated $TARGET_PATH/$FILE"
    done
    sudo rm -rf "$DEST"
fi

echo "Ironic images update completed successfully!"
echo "All images are now available in: $TARGET_PATH"

# List the files in the target directory for verification
echo "Files in $TARGET_PATH:"
ls -la "$TARGET_PATH"
