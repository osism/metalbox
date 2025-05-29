#!/usr/bin/env bash

# Script to replace the site "Discworld" in environments/manager/configuration.yml

set -e

# Check if site name was provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <managed_site>"
    exit 1
fi

NEW_SITE="$1"
CONFIG_FILE="/opt/configuration/environments/manager/configuration.yml"

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file $CONFIG_FILE not found"
    exit 1
fi

# Replace all occurrences of site: Discworld with the new site name
sed -i "s/site: Discworld/site: $NEW_SITE/g" "$CONFIG_FILE"

echo "Successfully replaced site 'Discworld' with '$NEW_SITE' in $CONFIG_FILE"
