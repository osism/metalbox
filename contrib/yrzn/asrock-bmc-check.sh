#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# ASRock BMC Redfish Connectivity & Authentication Check
# =============================================================================
#
# Tests basic Redfish API connectivity and authentication against an ASRock BMC.
# No configuration changes are made — this is a read-only check.
#
# Usage (CLI arguments):
#   ./asrock-bmc-check.sh --bmc-host <BMC_IP> \
#       [--bmc-user admin] [--bmc-password admin]
#
# Usage (environment variables):
#   BMC_HOST=10.0.1.100 BMC_USER=admin BMC_PASSWORD=secret ./asrock-bmc-check.sh
#
# CLI arguments take precedence over environment variables.
#
# =============================================================================

# -- Defaults (environment variables override defaults, CLI args override both)
BMC_HOST="${BMC_HOST:-}"
BMC_USER="${BMC_USER:-admin}"
BMC_PASSWORD="${BMC_PASSWORD:-admin}"

# -- Parse arguments ----------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Required:
  --bmc-host HOST          BMC IP address or FQDN (env: BMC_HOST)

Optional:
  --bmc-user USER          BMC username (env: BMC_USER, default: admin)
  --bmc-password PASS      BMC password (env: BMC_PASSWORD, default: admin)
  -h, --help               Show this help message

Environment variables:
  BMC_HOST                 BMC IP address or FQDN
  BMC_USER                 BMC username (default: admin)
  BMC_PASSWORD             BMC password (default: admin)

CLI arguments take precedence over environment variables.
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bmc-host)       BMC_HOST="$2"; shift 2 ;;
        --bmc-user)       BMC_USER="$2"; shift 2 ;;
        --bmc-password)   BMC_PASSWORD="$2"; shift 2 ;;
        -h|--help)        usage ;;
        *)                echo "ERROR: Unknown option: $1" >&2; usage ;;
    esac
done

if [[ -z "$BMC_HOST" ]]; then
    echo "ERROR: --bmc-host is required" >&2
    usage
fi

# -- Helper functions ---------------------------------------------------------
REDFISH_BASE="https://${BMC_HOST}/redfish/v1"

# =============================================================================
echo "============================================================="
echo " ASRock BMC Connectivity & Authentication Check"
echo " BMC Host: ${BMC_HOST}"
echo "============================================================="
echo ""

# -- Step 1: Check network reachability ---------------------------------------
echo "[1/3] Checking network reachability..."
if ! curl -sk --connect-timeout 5 -o /dev/null -w "" "${REDFISH_BASE}" 2>/dev/null; then
    echo "ERROR: Cannot reach BMC at ${BMC_HOST} (connection timeout)" >&2
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: Cannot reach BMC at ${BMC_HOST} (connection timeout) (BMC_HOST=${BMC_HOST})" >> asrock-bmc-check.log
    exit 1
fi
echo "INFO: BMC is reachable"
echo ""

# -- Step 2: Check Redfish service root (unauthenticated) --------------------
echo "[2/3] Checking Redfish service root..."
http_code=$(curl -sk --connect-timeout 5 -o /dev/null -w "%{http_code}" "${REDFISH_BASE}")
if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
    echo "INFO: Redfish service root accessible (HTTP ${http_code})"
else
    echo "ERROR: Redfish service root returned HTTP ${http_code}" >&2
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: Redfish service root returned HTTP ${http_code} (BMC_HOST=${BMC_HOST})" >> asrock-bmc-check.log
    exit 1
fi
echo ""

# -- Step 3: Check authenticated access ---------------------------------------
echo "[3/3] Checking authentication (GET /Systems/Self)..."
http_code=$(curl -sk --connect-timeout 5 \
    -u "${BMC_USER}:${BMC_PASSWORD}" \
    -H "Content-Type: application/json" \
    -o /dev/null \
    -w "%{http_code}" \
    "${REDFISH_BASE}/Systems/Self")

if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
    echo "INFO: Authentication successful (HTTP ${http_code})"
elif [[ "$http_code" == "401" ]]; then
    echo "ERROR: Authentication failed — invalid credentials (HTTP 401)" >&2
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: Authentication failed — invalid credentials (HTTP 401) (BMC_HOST=${BMC_HOST})" >> asrock-bmc-check.log
    exit 1
else
    echo "ERROR: Unexpected response (HTTP ${http_code})" >&2
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: Unexpected response (HTTP ${http_code}) (BMC_HOST=${BMC_HOST})" >> asrock-bmc-check.log
    exit 1
fi
echo ""

# =============================================================================
echo "============================================================="
echo " All checks passed"
echo "============================================================="
