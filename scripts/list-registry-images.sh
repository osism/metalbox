#!/usr/bin/env bash
#
# List all container images available on the local registry.
#
# The metalbox ships with a local Docker Registry v2 (started by
# scripts/update-registry.sh, listening on localhost:5001) that mirrors all
# container images required for offline/air-gapped deployments (OSISM manager
# images, Kolla service images, DockerHub dependencies, ...).
#
# This script queries the registry's HTTP API to enumerate every repository
# (and, by default, every tag per repository) that is currently stored in the
# local mirror. Use it to verify that an expected image is present before a
# deployment, to audit the mirror's contents after an update, or to produce an
# inventory for documentation.
#
# Usage: list-registry-images.sh [-t] [-d] [-h]
#
#   -t    Show only repository names (without tags)
#   -d    Also show the content digest for each tag (one HEAD request per tag,
#         slower on large registries). Ignored together with -t.
#   -h    Show this help text and exit
#
# Environment variables:
#   REGISTRY  - Registry to query (default: localhost:5001)

set -euo pipefail

# Print the leading comment block (everything between the shebang and the first
# non-comment line) as the help text.
show_help() {
    awk '
        NR == 1 && /^#!/ { next }
        /^#/ { sub(/^# ?/, ""); print; next }
        { exit }
    ' "$0"
}

REGISTRY="${REGISTRY:-localhost:5001}"
SHOW_TAGS=true
SHOW_DIGEST=false

while getopts ":tdh" opt; do
    case "${opt}" in
        t)
            SHOW_TAGS=false
            ;;
        d)
            SHOW_DIGEST=true
            ;;
        h)
            show_help
            exit 0
            ;;
        *)
            echo "Usage: $(basename "$0") [-t] [-d] [-h]" >&2
            exit 1
            ;;
    esac
done

MANIFEST_ACCEPT="application/vnd.docker.distribution.manifest.v2+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.manifest.v1+json,application/vnd.oci.image.index.v1+json"

# Return the Docker-Content-Digest for <repo>:<tag>, or an empty string.
fetch_digest() {
    local repo="$1" tag="$2"
    curl -fsSI -H "Accept: ${MANIFEST_ACCEPT}" \
        "http://${REGISTRY}/v2/${repo}/manifests/${tag}" 2>/dev/null \
        | awk 'BEGIN { IGNORECASE = 1 } /^docker-content-digest:/ { print $2 }' \
        | tr -d '\r\n'
}

for cmd in curl jq; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "ERROR: required command not found: ${cmd}" >&2
        exit 1
    fi
done

if ! curl -fsS "http://${REGISTRY}/v2/" >/dev/null 2>&1; then
    echo "ERROR: registry not reachable at http://${REGISTRY}/v2/" >&2
    exit 1
fi

# Fetch the full catalog, following the Link header for pagination.
fetch_catalog() {
    local url="http://${REGISTRY}/v2/_catalog?n=1000"
    local headers body link next

    while [[ -n "${url}" ]]; do
        headers="$(mktemp)"
        body="$(curl -fsS -D "${headers}" "${url}")"
        jq -r '.repositories[]?' <<<"${body}"

        link="$(awk 'tolower($1) == "link:" { sub(/^[Ll]ink:[[:space:]]*/, ""); print }' "${headers}" | tr -d '\r')"
        rm -f "${headers}"

        if [[ -n "${link}" ]]; then
            next="$(sed -n 's/.*<\([^>]*\)>;[[:space:]]*rel="next".*/\1/p' <<<"${link}")"
            if [[ -n "${next}" ]]; then
                url="http://${REGISTRY}${next}"
                continue
            fi
        fi
        url=""
    done
}

repos="$(fetch_catalog | sort -u)"

if [[ -z "${repos}" ]]; then
    echo "No images found on ${REGISTRY}."
    exit 0
fi

if ! ${SHOW_TAGS}; then
    printf '%s\n' "${repos}"
    exit 0
fi

while IFS= read -r repo; do
    tags="$(curl -fsS "http://${REGISTRY}/v2/${repo}/tags/list" \
        | jq -r '.tags[]? // empty' \
        | sort)"

    if [[ -z "${tags}" ]]; then
        echo "${repo} (no tags)"
        continue
    fi

    while IFS= read -r tag; do
        if ${SHOW_DIGEST}; then
            digest="$(fetch_digest "${repo}" "${tag}")"
            if [[ -n "${digest}" ]]; then
                echo "${repo}:${tag}@${digest}"
            else
                echo "${repo}:${tag} (digest unavailable)"
            fi
        else
            echo "${repo}:${tag}"
        fi
    done <<<"${tags}"
done <<<"${repos}"
