#!/usr/bin/env bash

osism apply -a upgrade keystone
osism apply -a upgrade glance
osism apply -a upgrade ironic
osism apply -a upgrade openstackclient
