#!/bin/bash

node=$1

osism manage redfish list --format json $node NetworkDeviceFunctions 2>/dev/null | jq '. | map(select(.id | startswith("eth")) | .mac_address) | to_entries | map({mac_address:{mac_address:.value|ascii_upcase, assigned_object:{device:'\"$node\"', name:"Ethernet\(.key + 1)"}}})' | python3 -c 'import sys, json, yaml; print(yaml.safe_dump(json.loads(sys.stdin.read())))'
osism manage redfish list --format json $node EthernetInterfaces 2>/dev/null | jq '. | map(select(.id | startswith("1.")) | .permanent_mac_address) | to_entries | map({mac_address:{mac_address:.value|ascii_upcase, assigned_object:{device:'\"$node\"', name:"eth\(.key + 1)"}}})' | python3 -c 'import sys, json, yaml; print(yaml.safe_dump(json.loads(sys.stdin.read())))'
