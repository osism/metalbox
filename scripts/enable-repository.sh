#!/usr/bin/env bash

set -euo pipefail

CONFIG_FILE="environments/infrastructure/configuration.yml"

# Check if configuration file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file $CONFIG_FILE not found"
    exit 1
fi

# Enable Ubuntu repository by setting httpd_data_enable to true
sed -i 's/httpd_data_enable: false/httpd_data_enable: true/' "$CONFIG_FILE"

echo "Ubuntu repository enabled successfully"
echo "httpd_data_enable is now set to true in $CONFIG_FILE"