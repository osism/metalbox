#!/usr/bin/env bash

osism apply -a pull keystone
osism apply -a pull ironic
osism apply -a pull openstackclient

osism apply -a upgrade keystone
osism apply -a upgrade ironic
osism apply -a upgrade openstackclient || exit

# The upgrade leaves the images it replaced without a name. They are unused
# and the local registry still has them, so they only take up disk space.
docker image prune -f
