# metalbox

1. Download the metalbox image from the well known URL
2. Write the metalbox image to the disk and boot it (initial boot takes some time)
3. Export your NetBox configuration repository with `netbox-manager export`
   and transfer it to `/opt/netbox-export.tar.gz`
4. Run the `import.sh` script in `/opt/configuration/netbox`
5. Deploy the NetBox service with `./run.sh netbox` in `/opt/configuration/environments/manager`
6. Run the `manage.sh` script in `/opt/configuration/netbox`
7. Adjust the NetBox site in `/opt/configuration/environments/manager/configuration.yml`
8. Deploy the Manager service with `./run.sh manager` in `/opt/configuration/environments/manager`
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

15. Copy required Ironic image files

   ```
   docker exec osism-ansible mkdir -p /share/ironic/ironic
   docker cp  /opt/ironic-agent.initramfs osism-ansible:/share/ironic/ironic/ironic-agent.initramfs
   docker cp  /opt/ironic-agent.kernel osism-ansible:/share/ironic/ironic/ironic-agent.kernel
   ```

16. Deploy the OpenStack services

   ```
   osism apply keystone
   osism apply ironic
   osism apply openstackclient
   ```

17. Sync baremetal nodes with `osism sync ironic`
