#!/usr/bin/env bash

osism apply -a pull keystone
osism apply -a pull glance
osism apply -a pull ironic
osism apply -a pull openstackclient

osism apply -a upgrade keystone
osism apply -a upgrade glance
osism apply -a upgrade ironic
osism apply -a upgrade openstackclient
