#!/usr/bin/env bash

docker exec osism-ansible mkdir -p /share/ironic/ironic
docker cp /opt/ironic-agent.initramfs osism-ansible:/share/ironic/ironic/ironic-agent.initramfs
docker cp /opt/ironic-agent.kernel osism-ansible:/share/ironic/ironic/ironic-agent.kernel
docker cp /opt/osism.qcow2 osism-ansible:/share/ironic/ironic/osism.qcow2
