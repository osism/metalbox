#!/usr/bin/env bash

# Check if SONiC is disabled in the configuration
INFRA_CONFIG="/opt/configuration/environments/infrastructure/configuration.yml"
if grep -q "httpd_sonic_ztp_enable: false" "$INFRA_CONFIG" 2>/dev/null; then
    echo "Error: SONiC is disabled (httpd_sonic_ztp_enable: false in $INFRA_CONFIG)"
    echo "If you want to deploy SONiC, re-enable it first."
    exit 1
fi

# Check if httpd container is running, deploy if not
if ! docker ps --filter "name=httpd" --format "table {{.Names}}" | grep -q "httpd"; then
    echo "httpd container not running, deploying httpd service..."
    osism apply httpd
    echo "httpd service deployment completed!"
else
    echo "httpd container is already running"
fi

sonic-import.sh
osism sync sonic
osism apply dnsmasq
