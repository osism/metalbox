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
   media (vHDD) and run the `/opt/configuration/scripts/netbox-import.sh` script.
   Afterwards remove the virtual media (vHDD).
5. Run the `/opt/configuration/scripts/deploy-netbox.sh` script
6. Run the `/opt/configuration/scripts/netbox-manage.sh` script
7. Set the managed site by running `/opt/configuration/scripts/netbox-site.sh SITE`
   (replace `SITE` with the slug name of the site managed by this Metalbox)
8. Run the `/opt/configuration/scripts/deploy-manager.sh` script
9. Sync inventory with `osism sync inventory`
10. Set vault password with `osism vault password set`
11. Sync `/etc/hosts` with `osism apply hosts`
12. Sync network configuration with `osism apply network`
13. Sync facts with `osism apply facts`
14. Deploy the infrastructure services

    ```
    osism apply common
    osism apply redis
    osism apply memcached
    osism apply rabbitmq
    osism apply mariadb
    osism apply httpd
    ```

15. Download the SONiC export image from the well known URL. Use the file as
    virtual media (vHDD) and run the `/opt/configuration/scripts/sonic-import.sh`
    script. Afterwards remove the virtual media (vHDD).

16. Deploy the dnsmasq service

    ```
    osism apply dnsmasq
    ```

17. Deploy the OpenStack services

    ```
    osism apply keystone
    osism apply glance
    osism apply ironic
    osism apply openstackclient
    ```

18. Upload required Ironic image files

    ```
    osism apply -e custom ironic-upload-images
    ```

19. Sync baremetal nodes with `osism sync ironic`
