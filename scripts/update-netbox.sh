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

pushd /opt/configuration/environments/manager
bash run.sh netbox
popd

wait_for_container_healthy || exit

# The upgrade leaves the images it replaced without a name. They are unused
# and the local registry still has them, so they only take up disk space.
docker image prune -f
