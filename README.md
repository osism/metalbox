# metalbox

## Installation

1. Download the Metalbox image from the well known URL. Use the file as virtual
   media (vHDD).
2. Download the small [Grml](https://grml.org/download/) live ISO file. Use the
   file as virtual media (vDVD) and boot it.
3. Write the Metalbox image with `dd if=/dev/sdc of=/dev/sda bs=4M status=progress` to
   the first disk. Afterwards power off the node, remove all virtual media devices and
   power on the node again.
4. Export the NetBox configuration repository with `netbox-manager export-archive -i`.
   When using a NetBox configuration repository provided by us, the file can be downloaded
   from GitHub after a trigger of the `Run export` action. Use the file  as virtual
   media (vHDD) and run `netbox-import.sh`.
   Afterwards remove the virtual media (vHDD).
5. Run `deploy-netbox.sh` to deploy the Netbox service.
6. Run `netbox-manage.sh` to initialise the Netbox service.
7. Set the managed site by running `netbox-site.sh SITE`
   (replace `SITE` with the slug name of the site managed by this Metalbox)
8. Run `deploy-manager.sh` to deploy the OSISM manager service.
9. Run `osism sync inventory` to sync the inventory
10. Run `osism apply hosts` to sync the `/etc/hosts` file
11. Run `osism apply network` to sync the network configuration
12. Run `osism apply facts` to sync the facts
13. Run `osism apply chrony` to sync the NTP configuration
14. Download the SONiC export image from the well known URL. Use the file as
    virtual media (vHDD).
15. Run `deploy-sonic.sh` to deploy the SONiC ZTP services. Afterwards remove the virtual
    media (vHDD).
16. Run `deploy-infrastructure.sh` to deploy the infrastructure services
17. Run `deploy-openstack.sh` to Deploy the OpenStack services
18. Run `osism apply -e custom ironic-upload-images` to upload required Ironic image files
19. Run `osism sync ironic` to sync the baremetal nodes

## Update of the container registry

1. Download `registry.tar.bz2` from https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/metalbox/registry.tar.bz2
2. Copy `registry.tar.bz2` to `/home/dragon` on the Metalbox node
3. Run `SKIP_DOWNLOAD=true update-registry.sh` to update the container registry

## Update of the manager service

1. Change to the `/opt/manager` directory on the Metalbox node
2. Run `update-manager.sh` to update the manager service

## Update of the netbox data

1. Export the NetBox configuration repository with `netbox-manager export-archive -i`.
   When using a NetBox configuration repository provided by us, the file can be downloaded
   from GitHub after a trigger of the `Run export` action. Copy `netbox-export.img` to
   `/home/dragon` on the Metalbox node
2. Run `mount-images.sh` to mount the `netbox-export.img` image
3. Run `netbox-import.sh` to sync the files in `/opt/configuration/netbox`
4. Run `unmount-images.sh` to unmount the `netbox-export.img` image
5. Run `netbox-manage.sh` to sync netbox with the state in `/opt/configuration/netbox`
