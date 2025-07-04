#!/usr/bin/env bash

osism apply -a upgrade common
osism apply -a upgrade redis
osism apply -a upgrade memcached
osism apply -a upgrade rabbitmq
osism apply -a upgrade mariadb
