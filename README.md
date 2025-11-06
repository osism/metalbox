# metalbox

## Preparation

1. Download the Metalbox image [osism-metalbox-image.zip](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-metalbox-image.zip).
   Unzip the `osism-metalbox-image.zip` file. The unzipped file is named
   `osism-metalbox-image.raw`.
2. Download the latest small [Grml](https://grml.org/download/) live ISO file.
   When creating this document, the file name was `grml-small-2025.05-amd64.iso`.
3. Download the SONiC export image `sonic-export.img` from the well known URL. You can also
   create this file locally by running `sonic-export.sh` inside a directory containing
   your SONiC images.
4. Export the NetBox configuration repository with `netbox-manager export-archive -i`.
   When using a NetBox configuration repository provided by us, the file `netbox-export.img`
   can be downloaded from GitHub after a trigger of the `Run export` action.
5. Download the Ironic images:
   * [osism-ipa.initramfs](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-ipa.initramfs)
   * [osism-ipa.kernel](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-ipa.kernel)
   * [osism-node.qcow2](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-node.qcow2)
   * [osism-node.qcow2.CHECKSUM](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-node.qcow2.CHECKSUM)
   * [osism-esp.raw](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-esp.raw)

### Optional steps

1. If the Metalbox is to be used as an Ubuntu repository server for nodes inside the Cloudpod
   download
   [ubuntu-noble.tar.bz2](https://nbg1.your-objectstorage.com/osism/metalbox/ubuntu-noble.tar.bz2)
2. If the Metalbox is to be used as a container registry for nodes inside the Cloudpod
   download
   [registry-full.tar.bz2](https://nbg1.your-objectstorage.com/osism/metalbox/registry-full.tar.bz2)

## Installation

1. Use the `osism-metalbox-image.raw` file as virtual media (vHDD).
2. Use the `grml-small-2025.05-amd64.iso` file as virtual media (vDVD) and boot it.
3. Write the Metalbox image with `dd if=/dev/sdc of=/dev/sda bs=4M status=progress` to
   the first disk. Afterwards power off the node, remove all virtual media devices and
   power on the node again.
4. Import of the NetBox files.
   * Use the `netbox-export.img` file as virtual media (vHDD) and run `netbox-import.sh`
     to import the NetBox files. Afterwards remove the virtual media (vHDD).
   * <ins>OR</ins> Copy the `netbox-export.img` file to `/home/dragon` and run `mount-images.sh`.
     Run `netbox-import.sh` to import the NetBox files. Afterwards run `unmount-images.sh`.
5. Run `deploy-netbox.sh` to deploy the NetBox service.
6. Run `netbox-manage.sh` to initialise the NetBox service. Note that this can take a
   couple of minutes to complete depending on the size of your installation.
7. Set the managed site by running `netbox-site.sh SITE`
   (replace `SITE` with the slug name of the site managed by this Metalbox).
8. Run `deploy-manager.sh` to deploy the OSISM manager service.
9. Run `osism sync inventory` to sync the inventory.
10. Run `osism apply hosts` to sync the `/etc/hosts` file.
11. Run `osism apply network` and `osism apply frr` to sync the network configuration.
12. Run `osism apply facts` to sync the facts.
13. Run `osism apply chrony` to sync the NTP configuration.
14. Use as Ubuntu repository server.
    * If the Metalbox is to be used as an Ubuntu repository server for nodes inside the
      Cloudpod do all steps in "Using the Metalbox as an Ubuntu repository server".
    *  <ins>OR</ins> Disable the use of the Metalbox as repository server by running
      `disable-repository.sh`.
15. Import of the SONiC files.
    * Use the file `sonic-export.img` as virtual media (vHDD) and run `deploy-sonic.sh` to deploy
      the SONiC ZTP services. Afterwards remove the virtual media (vHDD).
    * <ins>OR</ins> Copy the `sonic-export.img` file to `/home/dragon` and run `mount-images.sh`.
      Run `deploy-sonic.sh` to deploy the SONiC ZTP services. Afterwards run `unmount-images.sh`.
16. Run `deploy-infrastructure.sh` to deploy the infrastructure services.
17. Run `deploy-openstack.sh` to Deploy the OpenStack services.
18. Upload the Ironic image files to `/opt/httpd/data/root`.
19. Run `osism sync ironic` to sync the baremetal nodes.
20. Optional: If the Metalbox is to be used as a container registry for nodes inside
    the Cloudpod do all steps in "Using Metalbox as a full container registry".

### Optional steps

#### Using the Metalbox as an Ubuntu repository server

1. Download the Ubuntu repository archive
   [ubuntu-noble.tar.bz2](https://nbg1.your-objectstorage.com/osism/metalbox/ubuntu-noble.tar.bz2).
2. Copy `ubuntu-noble.tar.bz2` to `/home/dragon` on the Metalbox node.
3. Run `SKIP_DOWNLOAD=true update-repository.sh` to import the Ubuntu repository files. Note that this
   can take a couple of minutes to finish.

#### Using Metalbox as a full container registry

1. Download [registry-full.tar.bz2](https://nbg1.your-objectstorage.com/osism/metalbox/registry-full.tar.bz2).
2. Rename `registry-full.tar.bz2` to `registry.tar.bz2`.
3. Copy `registry.tar.bz2` to `/home/dragon` on the Metalbox node.
4. Run `SKIP_DOWNLOAD=true update-registry.sh` to update the container registry. Note that this can
   take a couple of minutes to finish.

## Data updates

### Update of the NetBox data

1. Export the NetBox configuration repository with `netbox-manager export-archive -i`.
   When using a NetBox configuration repository provided by us, the file can be downloaded
   from GitHub after a trigger of the `Run export` action. Copy `netbox-export.img` to
   `/home/dragon` on the Metalbox node.
2. Run `mount-images.sh` to mount the `netbox-export.img` image.
3. Run `netbox-import.sh` to sync the files in `/opt/configuration/netbox`.
4. Run `unmount-images.sh` to unmount the `netbox-export.img` image.
5. Run `netbox-manage.sh` to sync netbox with the state in `/opt/configuration/netbox`.

It is also possible to update only the data from specific devices. To do this, the netbox-manager
can be used directly in the NetBox directory. In the following example, only files with the
prefix `300-node10` are processed.

```
cd /opt/configuration/netbox
netbox-manager run --limit 300-node10
```

### Update of the Ironic images

#### Without external connectivity

1. Download the Ironic images:
   * [osism-ipa.initramfs](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-ipa.initramfs)
   * [osism-ipa.kernel](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-ipa.kernel)
   * [osism-node.qcow2](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-node.qcow2)
   * [osism-node.qcow2.CHECKSUM](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-node.qcow2.CHECKSUM)
   * [osism-esp.raw](https://nbg1.your-objectstorage.com/osism/openstack-ironic-images/osism-esp.raw)
2. Copy the downloaded files to `/home/dragon` on the Metalbox node
3. Run `SKIP_DOWNLOAD=true update-ironic-images.sh` to update the Ironic images

#### With external connectivity

1. Run `update-ironic-images.sh` to update the Ironic images

### Update of the container registry

#### Without external connectivity

1. Download [registry.tar.bz2](https://nbg1.your-objectstorage.com/osism/metalbox/registry.tar.bz2)
2. Copy `registry.tar.bz2` to `/home/dragon` on the Metalbox node
3. Run `SKIP_DOWNLOAD=true update-registry.sh` to update the container registry

#### With external connectivity

1. Run `update-registry.sh` to update the container registry

### Update of the Ubuntu repository files

#### Without external connectivity

1. Download [ubuntu-noble.tar.bz2](https://nbg1.your-objectstorage.com/osism/metalbox/ubuntu-noble.tar.bz2)
2. Copy `ubuntu-noble.tar.bz2` to `/home/dragon` on the Metalbox node
3. Run `SKIP_DOWNLOAD=true update-repository.sh` to update the Ubuntu repository files

#### With external connectivity

1. Run `update-repository.sh` to update the Ubuntu repository

## Service updates

### Update of the manager service

1. The container registry must be updated first in order to receive service updates
2. Run `update-manager.sh` to update the manager service

### Update of the NetBox service

1. The container registry must be updated first in order to receive a NetBox update
2. Run `update-netbox.sh` to update the NetBox service

### Update of the infrastructure services

1. The container registry must be updated first in order to receive infrastructure service updates
2. Run `update-infrastructure.sh` to update the infrastructure services

### Update of the OpenStack services

1. The container registry must be updated first in order to receive OpenStack service updates
2. Run `update-openstack.sh` to update the OpenStack services
