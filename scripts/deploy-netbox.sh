#!/usr/bin/env bash

wait_for_container_healthy() {
    local max_attempts=60
    local name=netbox-netbox-1
    local attempt_num=1

    until [[ "$(/usr/bin/docker inspect -f '{{.State.Health.Status}}' $name)" == "healthy" ]]; do
	echo "Waiting for NetBox to be ready ($attempt_num / $max_attempts)"
        if (( attempt_num++ == max_attempts )); then
            return 1
        else
            sleep 10
        fi
    done
}

until stat /var/lib/cloud/instance/boot-finished 2>/dev/null; do echo Wait for cloud-init to finish; sleep 1; done

pushd /opt/configuration/environments/manager
bash run.sh netbox
popd

wait_for_container_healthy
