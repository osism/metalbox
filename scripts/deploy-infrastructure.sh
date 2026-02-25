#!/usr/bin/env bash

# Check if dnsmasq container is running, deploy if not
if ! docker ps --filter "name=dnsmasq" --format "table {{.Names}}" | grep -q "dnsmasq"; then
    echo "dnsmasq container not running, deploying dnsmasq service..."
    osism apply dnsmasq
    echo "dnsmasq service deployment completed!"
else
    echo "dnsmasq container is already running"
fi

# Check if httpd container is running, deploy if not
if ! docker ps --filter "name=httpd" --format "table {{.Names}}" | grep -q "httpd"; then
    echo "httpd container not running, deploying httpd service..."
    osism apply httpd
    echo "httpd service deployment completed!"
else
    echo "httpd container is already running"
fi

osism apply common
osism apply redis
osism apply memcached
osism apply rabbitmq
osism apply mariadb
