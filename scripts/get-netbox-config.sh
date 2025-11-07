#!/usr/bin/env bash

set -e

# Check if name was provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <name>"
    exit 1
fi

NODE="$1"

pushd /opt/configuration/environments/manager
./venv/bin/python3 get-netbox-config.py $NODE
popd
