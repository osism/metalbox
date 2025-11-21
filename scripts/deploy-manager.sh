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

# Validate that the site name has been configured
if grep -q "Discworld" /opt/configuration/environments/manager/configuration.yml; then
    echo "ERROR: Default site name 'Discworld' detected in configuration"
    echo ""
    echo "Please set your actual site name before deploying."
    echo "Run the following command with your site name:"
    echo ""
    echo "  netbox-site.sh <your_site_name>"
    echo ""
    exit 1
fi

pushd /opt/configuration/environments/manager
bash run.sh operator
bash run.sh manager
popd

wait_for_container_healthy

cat /opt/configuration/environments/.vault_pass | osism vault password set
