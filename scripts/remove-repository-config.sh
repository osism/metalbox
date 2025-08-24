#!/bin/bash

# Script to remove repository configuration block from environments/configuration.yml

CONFIG_FILE="/opt/configuration/environments/configuration.yml"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: $CONFIG_FILE not found!"
    exit 1
fi


# Use sed to remove the repository configuration block
sed -i.tmp '
# Start from "# repository" comment and remove repository configuration variables
/^# repository$/,/^$/{
    # Keep the comment and blank line pattern, but remove specific config lines
    /^docker_configure_repository: false$/d
    /^netbird_configure_repository: false$/d
    /^netdata_configure_repository: false$/d
}
# Remove repositories section with all its content
/^repositories:$/,/^[[:space:]]*deb822_trusted: "yes"$/{
    d
}
# Also remove the empty line after repositories section if it exists
/^repositories:$/{
    :loop
    n
    /^$/!b loop
    d
}
' "$CONFIG_FILE"

# Clean up temporary file
rm -f "${CONFIG_FILE}.tmp"

echo "Repository configuration block removed from $CONFIG_FILE"
