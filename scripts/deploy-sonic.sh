#!/usr/bin/env bash

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
