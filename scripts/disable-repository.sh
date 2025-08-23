#!/usr/bin/env bash

set -euo pipefail

CONFIG_FILE="/opt/configuration/environments/infrastructure/configuration.yml"

# Check if configuration file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file $CONFIG_FILE not found"
    exit 1
fi

# Disable Ubuntu repository by setting httpd_data_enable to false
sed -i 's/httpd_data_enable: true/httpd_data_enable: false/' "$CONFIG_FILE"

echo "Ubuntu repository disabled successfully"
echo "httpd_data_enable is now set to false in $CONFIG_FILE"

bash /opt/configuration/scripts/remove-repository-config.sh
