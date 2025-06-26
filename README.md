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
   media (vHDD) and run the `netbox-import.sh` script.
   Afterwards remove the virtual media (vHDD).
5. Run the `deploy-netbox.sh` script to deploy the Netbox service.
6. Run the `netbox-manage.sh` script to initialise the Netbox service.
7. Set the managed site by running `netbox-site.sh SITE`
   (replace `SITE` with the slug name of the site managed by this Metalbox)
8. Run the `deploy-manager.sh` script to deploy the OSISM manager service.
9. Sync inventory with `osism sync inventory`
10. Sync `/etc/hosts` with `osism apply hosts`
11. Sync network configuration with `osism apply network`
12. Sync facts with `osism apply facts`
13. Download the SONiC export image from the well known URL. Use the file as
    virtual media (vHDD).
14. Deploy the SONiC ZTP services. Afterwards remove the virtual media (vHDD).

    ```
    osism apply httpd
    sonic-import.sh
    osism sync sonic
    osism apply dnsmasq
    ```

15. Deploy the infrastructure services

    ```
    osism apply common
    osism apply redis
    osism apply memcached
    osism apply rabbitmq
    osism apply mariadb
    ```

16. Deploy the OpenStack services

    ```
    osism apply keystone
    osism apply glance
    osism apply ironic
    osism apply openstackclient
    ```

17. Upload required Ironic image files

    ```
    osism apply -e custom ironic-upload-images
    ```

18. Sync baremetal nodes with `osism sync ironic`

## Update of the container registry

1. Download `registry.tar.bz2` from https://swift.services.a.regiocloud.tech/swift/v1/AUTH_b182637428444b9aa302bb8d5a5a418c/metalbox/registry.tar.bz2
2. Copy `registry.tar.bz2` to `/home/dragon` on the Metalbox node
3. Run the `update-registry.sh` script to update the container registry.

## Update of the manager service

1. Change to the `/opt/manager` directory on the Metalbox node
2. Run `docker compose pull` to pull latest container images
3. Run `docker compose up -d` to update the manager service
