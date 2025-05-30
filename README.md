# metalbox

## Installation

1. Download the metalbox image from the well known URL
2. Write the metalbox image with the help of grml to the first disk
   and boot it (initial boot takes some time)
3. Export your NetBox configuration repository with `netbox-manager export-archive -i`
   and use it as vHDD / virtual media
4. Run the `/opt/configuration/scripts/netbox-import.sh` script (afterwards the vHDD / virtual
   media can be removed)
5. Run the `/opt/configuration/scripts/deploy-netbox.sh` script
6. Run the `/opt/configuration/scripts/netbox-manage.sh` script
7. Set the managed site with the `/opt/configuration/scripts/netbox-site.sh` script
8. Run the `/opt/configuration/scripts/deploy-manager.sh` script
9. Sync inventory with `osism sync inventory`
10. Sync `/etc/hosts` with `osism apply hosts`
11. Prepare network configuration with `osism apply network` and apply it with `sudo netplan apply`
12. Sync facts with `osism apply facts`
13. Deploy the infrastructure services

   ```
   osism apply common
   osism apply redis
   osism apply memcached
   osism apply rabbitmq
   osism apply mariadb
   osism apply dnsmasq
   osism apply httpd
   ```

14. Transfer the `sonic-broadcom-enterprise-base.bin` file to
    `/opt/httpd/data/sonic-broadcom-enterprise-base.bin`

15. Run the `/opt/configuration/scripts/ironic-import.sh` script

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
