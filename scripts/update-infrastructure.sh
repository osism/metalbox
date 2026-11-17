#!/usr/bin/env bash

source /opt/configuration/scripts/include.sh
key_value_store=$(valkey_or_redis)

osism apply -a pull common
osism apply -a pull "$key_value_store"
osism apply -a pull memcached
osism apply -a pull rabbitmq
osism apply -a pull mariadb

osism apply -a upgrade common
osism apply -a upgrade "$key_value_store"
osism apply -a upgrade memcached
osism apply -a upgrade rabbitmq
osism apply -a upgrade mariadb || exit

# The upgrade leaves the images it replaced without a name. They are unused
# and the local registry still has them, so they only take up disk space.
docker image prune -f
