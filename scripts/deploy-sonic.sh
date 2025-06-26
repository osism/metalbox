#!/usr/bin/env bash

osism apply httpd
sonic-import.sh
osism sync sonic
osism apply dnsmasq
