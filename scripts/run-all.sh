#!/usr/bin/env bash

MANAGED_SITE="$1"
ENABLE_SONIC="${ENABLE_SONIC:-true}"

wait_for_container_healthy() {
    local max_attempts=60
    local name=registry
    local attempt_num=1

    until [[ "$(/usr/bin/docker inspect -f '{{.State.Health.Status}}' $name)" == "healthy" ]]; do
        echo "Waiting for Manager to be ready ($attempt_num / $max_attempts)"
        if (( attempt_num++ == max_attempts )); then
            return 1
        else
            sleep 10
        fi
    done
}

wait_for_container_healthy

/opt/configuration/scripts/netbox-import.sh
/opt/configuration/scripts/deploy-netbox.sh
/opt/configuration/scripts/netbox-manage.sh
/opt/configuration/scripts/netbox-site.sh $MANAGED_SITE
/opt/configuration/scripts/deploy-manager.sh
osism sync inventory
osism apply hosts
osism apply network
osism apply facts
osism apply common
osism apply redis
osism apply memcached
osism apply rabbitmq
osism apply mariadb
osism apply httpd
if [[ "$ENABLE_SONIC" == "true" ]]; then
    /opt/configuration/scripts/sonic-import.sh
fi
osism apply dnsmasq
osism apply keystone
osism apply ironic
osism apply openstackclient
osism sync ironic
