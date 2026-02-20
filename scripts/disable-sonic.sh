#!/usr/bin/env bash

set -euo pipefail

INFRA_CONFIG="/opt/configuration/environments/infrastructure/configuration.yml"
MANAGER_CONFIG="/opt/configuration/environments/manager/configuration.yml"

# Check if configuration files exist
if [ ! -f "$INFRA_CONFIG" ]; then
    echo "Error: Configuration file $INFRA_CONFIG not found"
    exit 1
fi

if [ ! -f "$MANAGER_CONFIG" ]; then
    echo "Error: Configuration file $MANAGER_CONFIG not found"
    exit 1
fi

# Disable SONiC ZTP by setting httpd_sonic_ztp_enable to false
sed -i 's/httpd_sonic_ztp_enable: true/httpd_sonic_ztp_enable: false/' "$INFRA_CONFIG"

# Remove SONiC-specific dnsmasq DHCP settings
sed -i '/^dnsmasq_dhcp_vendorclass:/,/^[^[:space:]-]/{ /^dnsmasq_dhcp_vendorclass:/d; /^[[:space:]]*-/d; }' "$INFRA_CONFIG"
sed -i '/^dnsmasq_dhcp_options:/,/^[^[:space:]-]/{ /^dnsmasq_dhcp_options:/d; /^[[:space:]]*-/d; }' "$INFRA_CONFIG"
sed -i '/^dnsmasq_dhcp_boot:/,/^[^[:space:]-]/{ /^dnsmasq_dhcp_boot:/d; /^[[:space:]]*-/d; }' "$INFRA_CONFIG"

# Remove netbox_filter_conductor_sonic from manager configuration
sed -i '/^netbox_filter_conductor_sonic:/,/^[^[:space:]-]/{
    /^netbox_filter_conductor_sonic:/d
    /^[[:space:]]*-/d
    /^[[:space:]]*[a-z]/d
}' "$MANAGER_CONFIG"

echo "SONiC disabled successfully"
echo "httpd_sonic_ztp_enable is now set to false in $INFRA_CONFIG"
echo "SONiC-specific dnsmasq settings removed from $INFRA_CONFIG"
echo "netbox_filter_conductor_sonic removed from $MANAGER_CONFIG"
