#!/usr/bin/env bash

PARALLEL=${PARALLEL:-1}

pushd /opt/configuration/netbox
netbox-manager run --parallel $PARALLEL
popd
