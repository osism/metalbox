# MetalBox

The OSISM MetalBox is a hardware-provisioning appliance built around
[OpenStack Ironic](https://docs.openstack.org/ironic/latest/). It deploys bare-metal
hosts and bundles every component required to install an OSISM environment offline, so
that a pod can be brought up without external network access.

This repository holds the configuration repository that is deployed to
`/opt/configuration` on a MetalBox: the environments, the inventory, the scripts and
the Zuul jobs that build the mirror artifacts.

Documentation:

* Concept and architecture: https://osism.tech/docs/concepts/metalbox
* Installation: https://osism.tech/docs/guides/deploy-guide/metalbox
* Data and service updates: https://osism.tech/docs/guides/upgrade-guide/metalbox/
* Software RAID: https://osism.tech/docs/guides/configuration-guide/metalbox/software-raid
* Troubleshooting: https://osism.tech/docs/guides/troubleshooting-guide/metalbox
