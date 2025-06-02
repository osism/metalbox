# metalbox

## Installation

1. Download the metalbox image from the well known URL use it as vHDD / virtual media
2. Write the metalbox image with the help of Grml to the first disk (afterwards remove
   the vHDD / virtual media) and boot it
3. Export your NetBox configuration repository with `netbox-manager export-archive -i`,
   use it as vHDD / virtual media and run the `/opt/configuration/scripts/netbox-import.sh`
   script (afterwards remove the vHDD / virtual media)
4. Run the `/opt/configuration/scripts/deploy-netbox.sh` script
5. Run the `/opt/configuration/scripts/netbox-manage.sh` script
6. Set the managed site with the `/opt/configuration/scripts/netbox-site.sh` script
7. Run the `/opt/configuration/scripts/deploy-manager.sh` script
8. Sync inventory with `osism sync inventory`
9. Sync `/etc/hosts` with `osism apply hosts`
10. Sync network configuration with `osism apply network`
11. Sync facts with `osism apply facts`
12. Deploy the infrastructure services

    ```
    osism apply common
    osism apply redis
    osism apply memcached
    osism apply rabbitmq
    osism apply mariadb
    osism apply httpd
    ```

13. Download the SONiC image from the well known URL, use it as vHDD / virtual media
    and run the `/opt/configuration/scripts/sonic-import.sh` script (afterwards
    remove the vHDD / virtual media)

14. Deploy the dnsmasq service

    ```
    osism apply dnsmasq
    ```

15. Deploy the OpenStack services

    ```
    osism apply keystone
    osism apply glance
    osism apply ironic
    osism apply openstackclient
    ```

16. Upload required Ironic image files

    ```
    osism apply -e custom ironic-upload-images
    ```

17. Sync baremetal nodes with `osism sync ironic`
