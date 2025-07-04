#!/usr/bin/env bash

osism apply -a pull common
osism apply -a pull redis
osism apply -a pull memcached
osism apply -a pull rabbitmq
osism apply -a pull mariadb

osism apply -a upgrade common
osism apply -a upgrade redis
osism apply -a upgrade memcached
osism apply -a upgrade rabbitmq
osism apply -a upgrade mariadb
