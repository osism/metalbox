#!/usr/bin/env bash

wait_for_container_healthy() {
    local max_attempts=60
    local name=manager-inventory_reconciler-1
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

pushd /opt/configuration/environments/manager
bash run.sh manager
popd

wait_for_container_healthy

bash -c /opt/configuration/scripts/ironic-import.sh

cat /opt/configuration/environments/.vault_pass | osism vault password set
