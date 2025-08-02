# metalbox

## Preparation

1. Download the Metalbox image [osism-metalbox-image.zip](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-metalbox-image.zip).
   Unzip the `osism-metalbox-image.zip` file. The unzipped file is named
   `osism-metalbox-image.raw`.
2. Download the latest small [Grml](https://grml.org/download/) live ISO file.
   When creating this document, the file name was `grml-small-2025.05-amd64.iso`.
3. Download the SONiC export image `sonic-export.img` from the well known URL.
4. Export the NetBox configuration repository with `netbox-manager export-archive -i`.
   When using a NetBox configuration repository provided by us, the file `netbox-export.img`
   can be downloaded from GitHub after a trigger of the `Run export` action.
5. Download the Ironic images:
   * [osism-ipa.initramfs](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-ipa.initramfs)
   * [osism-ipa.kernel](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-ipa.kernel)
   * [osism-node.qcow2](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-node.qcow2)
   * [osism-node.qcow2.CHECKSUM](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-node.qcow2.CHECKSUM)
   * [osism-esp.raw](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-esp.raw)

## Installation

### Without external connectivity

1. Use the `osism-metalbox-image.raw` file as virtual media (vHDD).
2. Use the `grml-small-2025.05-amd64.iso` file as virtual media (vDVD) and boot it.
3. Write the Metalbox image with `dd if=/dev/sdc of=/dev/sda bs=4M status=progress` to
   the first disk. Afterwards power off the node, remove all virtual media devices and
   power on the node again.
4. Use the `netbox-export.img` file as virtual media (vHDD) and run `netbox-import.sh`.
   Afterwards remove the virtual media (vHDD).
5. Run `deploy-netbox.sh` to deploy the NetBox service.
6. Run `netbox-manage.sh` to initialise the NetBox service.
7. Set the managed site by running `netbox-site.sh SITE`
   (replace `SITE` with the slug name of the site managed by this Metalbox)
8. Run `deploy-manager.sh` to deploy the OSISM manager service.
9. Run `osism sync inventory` to sync the inventory
10. Run `osism apply hosts` to sync the `/etc/hosts` file
11. Run `osism apply network` to sync the network configuration
12. Run `osism apply facts` to sync the facts
13. Run `osism apply chrony` to sync the NTP configuration
14. Use the file `sonic-export.img` as virtual media (vHDD).
15. Run `deploy-sonic.sh` to deploy the SONiC ZTP services. Afterwards remove the virtual
    media (vHDD).
16. Run `deploy-infrastructure.sh` to deploy the infrastructure services
17. Run `deploy-openstack.sh` to Deploy the OpenStack services
18. Upload the Ironic image files to `/opt/httpd/data/root`
19. Run `osism sync ironic` to sync the baremetal nodes

### With external connectivity

1. Use the `grml-small-2025.05-amd64.iso` file as virtual media (vDVD) and boot it.

## Update of the NetBox data

1. Export the NetBox configuration repository with `netbox-manager export-archive -i`.
   When using a NetBox configuration repository provided by us, the file can be downloaded
   from GitHub after a trigger of the `Run export` action. Copy `netbox-export.img` to
   `/home/dragon` on the Metalbox node
2. Run `mount-images.sh` to mount the `netbox-export.img` image
3. Run `netbox-import.sh` to sync the files in `/opt/configuration/netbox`
4. Run `unmount-images.sh` to unmount the `netbox-export.img` image
5. Run `netbox-manage.sh` to sync netbox with the state in `/opt/configuration/netbox`

## Update of the Ironic images

### Without external connectivity

1. Download the Ironic images:
   * [osism-ipa.initramfs](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-ipa.initramfs)
   * [osism-ipa.kernel](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-ipa.kernel)
   * [osism-node.qcow2](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-node.qcow2)
   * [osism-node.qcow2.CHECKSUM](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-node.qcow2.CHECKSUM)
   * [osism-esp.raw](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/openstack-ironic-images/osism-esp.raw)
2. Copy the downloaded files to `/home/dragon` on the Metalbox node
3. Run `SKIP_DOWNLOAD=true update-ironic-images.sh` to update the Ironic images

### With external connectivity

1. Run `update-ironic-images.sh` to update the Ironic images

## Update of the container registry

### Without external connectivity

1. Download [registry.tar.bz2](https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/metalbox/registry.tar.bz2)
2. Copy `registry.tar.bz2` to `/home/dragon` on the Metalbox node
3. Run `SKIP_DOWNLOAD=true update-registry.sh` to update the container registry

### With external connectivity

1. Run `update-registry.sh` to update the container registry

## Service updates

### Update of the manager service

1. The container registry must be updated first in order to receive service updates
2. Run `update-manager.sh` to update the manager service

### Update of the NetBox service

1. The container registry must be updated first in order to receive a Netbox update
2. Run `update-netbox.sh` to update the NetBox service

### Update of the infrastructure services

1. The container registry must be updated first in order to receive infrastructure service updates
2. Run `update-infrastructure.sh` to update the infrastructure services

### Update of the OpenStack services

1. The container registry must be updated first in order to receive OpenStack service updates
2. Run `update-openstack.sh` to update the OpenStack services
