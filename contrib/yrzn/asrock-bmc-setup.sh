#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# ASRock BMC Redfish Configuration (COMPAL LTSv13.5 API)
# =============================================================================
#
# Configures ASRock BMC via Redfish API:
#   1. Set BIOS Fixed Boot Order: USB CD/DVD > Hard Disk > NVME (rest disabled)
#   2. Disable UEFI boot entries for PXE and EFI Shell
#   3. Enable Remote Media Support (AMI OEM)
#   4. Enable VirtualMedia protocol
#
# BIOS attributes are patched via the FutureState endpoint (Bios/SD).
# UEFI BootOptions are patched via BootOptions/{id}/SD.
#
# NOTE: No BootSourceOverride is set permanently. This ensures Ironic can
# still set one-time boot overrides (e.g. to CD for virtual media
# provisioning). After Ironic's one-time boot, the system falls back to
# the BIOS boot order: USB CD/DVD > Hard Disk > NVME.
#
# Usage (CLI arguments):
#   ./asrock-bmc-setup.sh --bmc-host <BMC_IP> \
#       [--bmc-user admin] [--bmc-password admin]
#
# Usage (environment variables):
#   BMC_HOST=10.0.1.100 BMC_USER=admin BMC_PASSWORD=secret ./asrock-bmc-setup.sh
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

redfish_get() {
    local endpoint="$1"
    curl -sk -u "${BMC_USER}:${BMC_PASSWORD}" \
        -H "Content-Type: application/json" \
        "${REDFISH_BASE}${endpoint}"
}

redfish_etag() {
    local endpoint="$1"
    curl -sk -u "${BMC_USER}:${BMC_PASSWORD}" \
        -H "Content-Type: application/json" \
        -o /dev/null \
        -D - \
        "${REDFISH_BASE}${endpoint}" | grep -i '^ETag:' | tr -d '\r' | awk '{print $2}'
}

redfish_patch() {
    local endpoint="$1"
    local data="$2"
    local etag
    etag=$(redfish_etag "$endpoint")
    local etag_header=()
    if [[ -n "$etag" ]]; then
        etag_header=(-H "If-Match: ${etag}")
    fi
    curl -sk -u "${BMC_USER}:${BMC_PASSWORD}" \
        -X PATCH \
        -H "Content-Type: application/json" \
        ${etag_header[@]+"${etag_header[@]}"} \
        -d "$data" \
        -o /dev/null \
        -w "%{http_code}" \
        "${REDFISH_BASE}${endpoint}"
}

redfish_post() {
    local endpoint="$1"
    local data="$2"
    curl -sk -u "${BMC_USER}:${BMC_PASSWORD}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d "$data" \
        -o /dev/null \
        -w "%{http_code}" \
        "${REDFISH_BASE}${endpoint}"
}

check_http() {
    local http_code="$1"
    local step="$2"
    if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
        echo "INFO: $step - OK (HTTP $http_code)"
    else
        echo "ERROR: $step - FAILED (HTTP $http_code)" >&2
        return 1
    fi
}

# =============================================================================
echo "============================================================="
echo " ASRock BMC Redfish Configuration"
echo " BMC Host: ${BMC_HOST}"
echo "============================================================="
echo ""

# -- Step 1: Verify Redfish connectivity --------------------------------------
echo "[1/5] Verifying Redfish connectivity..."
if ! redfish_get "/Systems/Self" > /dev/null 2>&1; then
    echo "ERROR: Cannot reach Redfish API at ${REDFISH_BASE}" >&2
    exit 1
fi
echo "INFO: Redfish API reachable"
echo ""

# -- Step 2: Set BIOS Fixed Boot Order ----------------------------------------
echo "[2/5] Setting BIOS Fixed Boot Order (via BIOS FutureState)..."
echo "INFO: Target order: 1=USB CD/DVD, 2=Hard Disk, 3=NVME, 4-6=Disabled"

# FBO attributes use the pattern: FBO1XX = FBO1XX<DeviceType>
# Patched via BIOS FutureState endpoint (Bios/SD)
http_code=$(redfish_patch "/Systems/Self/Bios/SD" '{
    "Attributes": {
        "FBO101": "FBO101USBCDDVD",
        "FBO102": "FBO102HardDisk",
        "FBO103": "FBO103NVME",
        "FBO104": "FBO104Disabled",
        "FBO105": "FBO105Disabled",
        "FBO106": "FBO106Disabled"
    }
}')
check_http "$http_code" "Set BIOS Fixed Boot Order"
echo ""

# -- Step 3: Disable UEFI PXE and Shell boot entries -------------------------
echo "[3/5] Disabling UEFI PXE and Shell boot entries..."

boot_options=$(redfish_get "/Systems/Self/BootOptions" | \
    python3 -c "import sys,json; data=json.load(sys.stdin); [print(m['@odata.id']) for m in data.get('Members',[])]" 2>/dev/null) || true

if [[ -n "$boot_options" ]]; then
    while IFS= read -r option_uri; do
        option_data=$(redfish_get "${option_uri#/redfish/v1}")
        alias=$(echo "$option_data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Alias',''))" 2>/dev/null) || true
        display=$(echo "$option_data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('DisplayName',''))" 2>/dev/null) || true
        option_id=$(echo "$option_data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Id',''))" 2>/dev/null) || true
        enabled=$(echo "$option_data" | python3 -c "import sys,json; print(json.load(sys.stdin).get('BootOptionEnabled',''))" 2>/dev/null) || true

        if [[ "$alias" == "Pxe" || "$alias" == "UefiShell" ]]; then
            if [[ "$enabled" == "False" ]]; then
                echo "INFO: Already disabled: ${display} (${option_id}) [Alias=${alias}]"
            else
                sd_uri="${option_uri#/redfish/v1}/SD"
                http_code=$(redfish_patch "$sd_uri" '{"BootOptionEnabled": false}')
                if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
                    echo "INFO: Disabled: ${display} (${option_id}) [Alias=${alias}]"
                else
                    echo "WARN: Could not disable: ${display} (${option_id}) (HTTP $http_code)"
                fi
            fi
        else
            echo "INFO: Keeping: ${display} (${option_id}) [Alias=${alias}]"
        fi
    done <<< "$boot_options"
else
    echo "WARN: No boot options found (BIOS inventory may not be available yet)"
fi
echo ""

# -- Step 4: Enable Remote Media Support (AMI OEM) ---------------------------
echo "[4/5] Enabling Remote Media Support (AMI OEM action)..."

# Check current RMedia status first
rmedia_status=$(redfish_get "/Managers/Self" | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('Oem',{}).get('Ami',{}).get('VirtualMedia',{}).get('RMediaStatus',''))" 2>/dev/null) || true

if [[ "$rmedia_status" == "Enabled" ]]; then
    echo "INFO: Remote Media Support already enabled"
else
    # POST to AMI OEM action target (from Managers/Self Actions.Oem)
    http_code=$(redfish_post "/Managers/Self/Actions/Oem/AMIVirtualMedia.EnableRMedia" '{"RMediaState": "Enable"}')
    check_http "$http_code" "Enable Remote Media Support"
fi
echo ""

# -- Step 5: Enable VirtualMedia protocol -------------------------------------
echo "[5/5] Enabling VirtualMedia protocol in ManagerNetworkProtocol..."

http_code=$(redfish_patch "/Managers/Self/NetworkProtocol" '{
    "VirtualMedia": {
        "ProtocolEnabled": true
    }
}')
check_http "$http_code" "Enable VirtualMedia protocol"
echo ""

# =============================================================================
echo "============================================================="
echo " Configuration complete"
echo "============================================================="
echo ""
echo "INFO: BIOS Fixed Boot Order: USB CD/DVD > Hard Disk > NVME (rest disabled)."
echo "INFO: UEFI PXE and Shell boot entries disabled."
echo "INFO: Remote Media Support enabled."
echo "INFO: VirtualMedia protocol enabled."
echo "INFO: Ironic can set one-time boot overrides to boot from virtual media."
echo ""
echo "NOTE: BIOS boot order changes require a host reboot to take effect."
