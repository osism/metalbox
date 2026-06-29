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
osism apply -a upgrade mariadb
